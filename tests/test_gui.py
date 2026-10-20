"""Real Tk widgets, isolated settings, mocked devices and asynchronous services."""
from pathlib import Path
import gc
import tempfile
import threading
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import numpy as np

from openbroadcast import gui
from openbroadcast.audio.runtime import AudioRoute, DeviceInfo
from openbroadcast.settings import SettingsStore
from openbroadcast.audio.inference import GpuDevice, DML, CPU


DEVICES = [
    DeviceInfo(2, "Microphone", "Windows WASAPI", 2, 0, default_input=True),
    DeviceInfo(3, "Cable capture", "Windows WASAPI", 2, 0),
    DeviceInfo(5, "Headphones", "Windows WASAPI", 0, 2, default_output=True),
    DeviceInfo(8, "Cable playback", "Windows WASAPI", 0, 2),
]


class FakeRoute:
    def __init__(self, name):
        self.name = name
        self.data = None
        self.updates = []
        self.started = []
        self.stops = 0
        self.snap = AudioRoute._initial_stats()
        self.snap.update(recording=False, recorded_seconds=0,
                         recording_ready=False, recording_error="")

    def snapshot(self):
        return self.snap.copy()

    @property
    def busy(self):
        return self.snap["state"] in ("loading", "running", "stopping")

    def update_effects(self, effects):
        self.updates.append(effects)

    def start(self, *args, **kwargs):
        self.started.append((args, kwargs))
        self.snap.update(state="running", channels=kwargs["channels"])

    def stop(self):
        self.stops += 1
        self.snap["state"] = "idle"

    def start_recording(self, max_seconds):
        if self.snap["state"] != "running":
            raise RuntimeError("Start the route first")
        self.snap.update(recording=True, recording_ready=False, recorded_seconds=0)

    def stop_recording(self):
        self.snap.update(recording=False, recording_ready=self.data is not None)

    def get_recording(self):
        return self.data


class GuiTests(unittest.TestCase):
    def setUp(self):
        # Collect Tk cycles on the GUI thread, after mock cleanup releases callbacks.
        self.addCleanup(gc.collect)
        self.temp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(Path(self.temp.name) / "settings.json")
        self.patches = [
            patch.object(gui, "AudioRoute", FakeRoute),
            patch.object(gui, "list_devices", return_value=DEVICES),
            patch.object(gui, "installed_samples", return_value={}),
            patch.object(gui, "discover_gpus", return_value=[
                GpuDevice("NVIDIA GeForce RTX 5090", DML, 2, "dxgi:test")]),
            patch.object(gui, "PreviewPlayer"),
            patch.object(gui, "TrayIcon"),
            patch.object(gui.startup, "is_enabled", return_value=False),
            patch.object(gui.startup, "set_enabled"),
            patch.object(gui.messagebox, "showinfo"),
            patch.object(gui.messagebox, "showerror"),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.player = gui.PreviewPlayer.return_value
        self.player.active = self.player.busy = False
        self.player.error = ""
        self.player.position = self.player.total = 0
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.temp.cleanup()
            self.skipTest(f"Tk display unavailable: {exc}")
        self.root.withdraw()
        self.app = gui.App(self.root, self.store)
        self.root.update_idletasks()

    def tearDown(self):
        if hasattr(self, "root"):
            try:
                self.root.update_idletasks()
                # Avoid Tcl callbacks referencing widgets destroyed by another test.
                for timer in self.root.tk.call("after", "info"):
                    self.root.after_cancel(timer)
                self.root.destroy()
            except tk.TclError:
                pass
        self.temp.cleanup()
        self.app = self.root = None

    def choose(self, key, role, index):
        combo = self.app.ui[key][role]
        combo.current(next(i for i, d in enumerate(combo._devices) if d.index == index))
        self.app.device_changed(key, role)

    def test_inference_controls_are_exclusive_and_preserve_selected_gpu(self):
        self.assertEqual(self.app.cpu_settings.winfo_manager(), "pack")
        self.assertEqual(self.app.gpu_settings.winfo_manager(), "")
        self.app.inference_mode.set("gpu")
        self.app.change_inference_mode()
        self.assertEqual(self.app.cpu_settings.winfo_manager(), "")
        self.assertEqual(self.app.gpu_settings.winfo_manager(), "pack")
        self.assertIn("RTX 5090", self.app.gpu_combo.get())
        self.app.inference_mode.set("cpu")
        self.app.change_inference_mode()
        self.app.save_config()
        saved = self.store.load()
        self.assertEqual(saved["inference_mode"], "cpu")
        self.assertEqual(saved["gpu"]["identity"], "dxgi:test")
        self.choose("mic", "output", 8)
        self.app.toggle_route("mic")
        self.assertEqual(self.app.routes["mic"].started[-1][1]["provider"], CPU)

    def test_live_device_change_coalesces_and_only_restarts_affected_route(self):
        self.choose("mic", "output", 8)
        self.choose("speaker", "input", 3)
        self.app.toggle_route("mic")
        self.app.toggle_route("speaker")
        self.choose("mic", "input", 3)
        self.choose("mic", "input", 2)
        self.app.pending_routes["mic"] = 0
        self.app.tick()
        self.assertEqual(len(self.app.routes["mic"].started), 2)
        self.assertEqual(self.app.routes["mic"].started[-1][0], (2, 8))
        self.assertEqual(len(self.app.routes["speaker"].started), 1)

    def test_cpu_threads_and_gpu_selection_apply_to_running_routes(self):
        self.choose("mic", "output", 8)
        self.app.toggle_route("mic")
        self.app.setting("threads", 7)
        self.app.pending_routes["mic"] = 0
        self.app.tick()
        self.assertEqual(self.app.routes["mic"].started[-1][1]["threads"], 7)
        self.app.inference_mode.set("gpu")
        self.app.change_inference_mode()
        self.app.pending_routes["mic"] = 0
        with patch.object(gui, "inference_options", return_value=dict(provider=DML, threads=7, device_id=2)):
            self.app.tick()
        self.assertEqual(self.app.routes["mic"].started[-1][1]["provider"], DML)

    def test_manual_stop_cancels_pending_reconfiguration_and_persists(self):
        self.choose("mic", "output", 8)
        self.app.toggle_route("mic")
        self.app.setting("threads", 3)
        self.app.toggle_route("mic")
        self.app.tick()
        self.assertEqual(len(self.app.routes["mic"].started), 1)
        self.assertFalse(self.store.load()["mic"]["enabled"])
        self.assertNotIn("mic", self.app.pending_routes)

    def test_exit_preserves_enabled_state_and_next_launch_restores_route(self):
        self.choose("mic", "output", 8)
        self.app.toggle_route("mic")
        self.app.request_exit()
        self.assertTrue(self.store.load()["mic"]["enabled"])
        self.assertFalse(self.store.load()["speaker"]["enabled"])
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.app = gui.App(self.root, self.store)
        self.assertEqual(len(self.app.routes["mic"].started), 1)
        self.assertEqual(self.app.routes["speaker"].started, [])

    def test_unavailable_saved_route_stays_stopped_until_device_is_selected(self):
        self.app.config["mic"].update(enabled=True, output=DEVICES[3].key,
                                      input={"name": "Disconnected", "hostapi": "Windows WASAPI"})
        self.app.save_config()
        for timer in self.root.tk.call("after", "info"):
            self.root.after_cancel(timer)
        self.app = gui.App(self.root, self.store)
        self.assertEqual(self.app.routes["mic"].started, [])
        self.assertIn("无法恢复", self.app.ui["mic"]["state"].cget("text"))
        gui.messagebox.showerror.assert_not_called()
        self.choose("mic", "input", 2)
        self.app.pending_routes["mic"] = 0
        self.app.tick()
        self.assertEqual(len(self.app.routes["mic"].started), 1)

    def test_monitor_switch_resumes_remaining_preview_on_new_device(self):
        audio = np.ones((960, 1), np.float32)
        self.app.play(audio, "mic")
        self.player.busy = True
        self.player.position = 480
        self.choose("mic", "monitor", 8)
        self.app.tick()
        self.assertEqual(self.player.play.call_count, 1)
        self.player.busy = False
        self.app.tick()
        self.assertEqual(self.player.play.call_args.args[1], 8)
        self.assertEqual(len(self.player.play.call_args.args[0]), 480)

    def test_sample_change_discards_stale_result_and_restarts_with_latest_settings(self):
        self.app.sample_job = True
        self.app.sample_effect.set(False)
        self.app.sample_settings_changed()
        self.app.events.put(("sample", np.ones((480, 1), np.float32)))
        self.app.sample_restart_due = 0
        with patch.object(self.app, "play_sample") as play:
            self.app.tick()
            play.assert_called_once()
        self.player.play.assert_not_called()

    def test_file_setting_change_restarts_original_job_and_cancel_wins(self):
        self.app.file_thread = Mock()
        self.app.file_thread.is_alive.return_value = True
        self.app.file_request = ("source.wav", "destination.wav")
        self.app.setting("threads", 4)
        self.assertTrue(self.app.file_cancel.is_set())
        self.assertTrue(self.app.file_restart)
        self.app.file_thread.is_alive.return_value = False
        self.app.file_restart_due = 0
        with patch.object(self.app, "process_file") as process:
            self.app.tick()
            process.assert_called_once_with(restart=True)
        self.app.file_thread.is_alive.return_value = True
        self.app.setting("threads", 5)
        self.app.cancel_file()
        self.app.file_thread.is_alive.return_value = False
        with patch.object(self.app, "process_file") as process:
            self.app.tick()
            process.assert_not_called()

    def test_startup_toggle_applies_immediately_and_rolls_back_on_failure(self):
        self.app.startup_enabled.set(True)
        self.app.change_startup()
        gui.startup.set_enabled.assert_called_once_with(True)
        gui.startup.set_enabled.side_effect = PermissionError("denied")
        self.app.startup_enabled.set(False)
        self.app.change_startup()
        self.assertTrue(self.app.startup_enabled.get())
        gui.messagebox.showerror.assert_called_once()

    def test_native_combobox_popdown_focus_does_not_break_tick(self):
        # ttk creates this Tcl window without registering a Python widget.
        self.root.deiconify()
        self.app.show_page("settings")
        self.root.update()
        combo = self.app.gpu_combo
        popdown = self.root.tk.call("ttk::combobox::PopdownWindow", str(combo))
        self.root.tk.call("focus", "-force", str(popdown) + ".f.l")
        self.app.tick()
        self.assertFalse(self.app.closed)

    def test_wheel_cannot_change_any_closed_combobox(self):
        self.root.deiconify()
        self.root.update()
        def combos(parent):
            for child in parent.winfo_children():
                if isinstance(child, gui.ttk.Combobox):
                    yield child
                yield from combos(child)
        selections = []
        for combo in combos(self.root):
            with self.subTest(widget=str(combo)):
                combo.configure(values=("First", "Second", "Third"))
                combo.current(1)
                combo.bind("<<ComboboxSelected>>", lambda _: selections.append(True))
                for sequence, options in (
                    ("<MouseWheel>", dict(delta=120)),
                    ("<MouseWheel>", dict(delta=-120)),
                    ("<Shift-MouseWheel>", dict(delta=-120)),
                    ("<Button-4>", {}), ("<Button-5>", {}),
                ):
                    combo.event_generate(sequence, **options)
                    self.root.update()
                    self.assertEqual(combo.get(), "Second")
        self.assertEqual(selections, [])

    def test_dropdown_wheel_scrolls_list_without_moving_background(self):
        self.root.deiconify()
        combo = self.app.ui["mic"]["input"]
        combo.configure(values=[f"Microphone {i}" for i in range(40)], height=5)
        combo.current(0)
        scroller = combo.master
        while not isinstance(scroller, gui.Scroller):
            scroller = scroller.master
        self.root.update()
        scroller.event_generate("<Enter>")
        canvas = scroller.canvas
        canvas.yview_moveto(0.15)
        self.root.tk.call("ttk::combobox::Post", str(combo))
        self.root.update()
        popup = str(self.root.tk.call("ttk::combobox::PopdownWindow", str(combo))) + ".f.l"
        before_page = canvas.yview()
        before_list = self.root.tk.call(popup, "yview")
        self.root.tk.call("event", "generate", popup, "<MouseWheel>", "-delta", -120)
        self.root.update()
        self.assertEqual(canvas.yview(), before_page)
        self.assertNotEqual(self.root.tk.call(popup, "yview"), before_list)
        self.assertEqual(combo.current(), 0)
        self.root.tk.call("ttk::combobox::Unpost", str(combo))

    def test_click_in_dropdown_still_selects_device(self):
        self.root.deiconify()
        combo = self.app.ui["mic"]["input"]
        combo.current(0)
        self.root.update()
        self.root.tk.call("ttk::combobox::Post", str(combo))
        self.root.update()
        popup = str(self.root.tk.call("ttk::combobox::PopdownWindow", str(combo))) + ".f.l"
        x, y, width, height = map(int, self.root.tk.call(popup, "bbox", 1))
        for event in ("<Button-1>", "<ButtonRelease-1>"):
            self.root.tk.call("event", "generate", popup, event,
                              "-x", x + 5, "-y", y + height // 2)
        self.root.update()
        self.assertEqual(combo.current(), 1)
        self.assertEqual(self.app.config["mic"]["input"], DEVICES[1].key)

    def test_page_wheel_still_scrolls_after_dropdown_closes(self):
        self.root.deiconify()
        combo = self.app.ui["mic"]["input"]
        scroller = combo.master
        while not isinstance(scroller, gui.Scroller):
            scroller = scroller.master
        self.root.update()
        self.root.tk.call("ttk::combobox::Post", str(combo))
        self.root.tk.call("ttk::combobox::Unpost", str(combo))
        scroller.canvas.yview_moveto(0)
        self.root.update()
        before = scroller.canvas.yview()
        scroller.body.event_generate("<MouseWheel>", delta=-120)
        self.root.update()
        self.assertGreater(scroller.canvas.yview()[0], before[0])

    def test_theme_and_compact_rebuild_preserve_form_and_device_state(self):
        self.app.toggle_layout()
        self.choose("mic", "output", 8)
        self.choose("speaker", "input", 3)
        self.choose("mic", "monitor", 5)
        self.app.vars["mic"]["noise_strength"].set(0.42)
        self.app.effects_changed("mic")
        self.app.file_input.set("source.wav")
        self.app.show_page("files")
        routes = self.app.routes.copy()
        self.app.theme("light")
        self.app.toggle_layout()
        self.root.update_idletasks()
        self.assertFalse(self.app.expanded)
        self.assertEqual(self.app.c, gui.PALETTES["light"])
        self.assertEqual(self.app.page, "files")
        self.assertEqual(self.app.selected("mic", "output").index, 8)
        self.assertEqual(self.app.selected("speaker", "input").index, 3)
        self.assertAlmostEqual(self.app.effects("mic").noise_strength, 0.42)
        self.assertEqual(self.app.file_input.get(), "source.wav")
        self.assertEqual(self.app.routes, routes)
        self.app.toggle_layout()
        self.app.theme("dark")
        self.app.tick()
        self.assertTrue(self.app.expanded)
        self.assertEqual(self.app.root.cget("bg"), gui.PALETTES["dark"]["bg"])

    def test_compact_default_and_layout_restored_after_restart(self):
        self.assertFalse(self.app.expanded)
        self.assertEqual(self.root.geometry().split("x")[0], "560")
        for expected in (True, False):
            self.app.toggle_layout()
            self.assertEqual(self.store.load()["expanded"], expected)
            self.root.update_idletasks()
            for timer in self.root.tk.call("after", "info"):
                self.root.after_cancel(timer)
            self.root.destroy()
            self.root = tk.Tk()
            self.root.withdraw()
            self.app = gui.App(self.root, self.store)
            self.root.update_idletasks()
            self.assertEqual(self.app.expanded, expected)
            self.assertEqual(self.root.geometry().split("x")[0], "1120" if expected else "560")

    @unittest.skipUnless(gui.sys.platform == "win32", "Windows tray")
    def test_tray_starts_with_visible_window_and_survives_restore(self):
        gui.TrayIcon.assert_called_once_with(self.app.events)
        gui.TrayIcon.return_value.start.assert_called_once()
        self.root.deiconify()
        self.app.events.put(("tray_ready", None))
        self.app.tick()
        self.assertEqual(self.root.state(), "normal")
        self.app.on_close()
        self.assertEqual(self.root.state(), "withdrawn")
        self.app.restore_window()
        self.assertEqual(self.root.state(), "normal")
        gui.TrayIcon.assert_called_once()
        gui.TrayIcon.return_value.stop.assert_not_called()

    def test_effects_update_only_the_selected_route_and_persist(self):
        self.app.vars["speaker"]["noise"].set(False)
        self.app.vars["speaker"]["dereverb"].set(True)
        self.app.vars["speaker"]["dereverb_strength"].set(0.27)
        before = len(self.app.routes["mic"].updates)
        self.app.effects_changed("speaker")
        update = self.app.routes["speaker"].updates[-1]
        self.assertFalse(update.noise)
        self.assertTrue(update.dereverb)
        self.assertAlmostEqual(update.dereverb_strength, 0.27)
        self.assertEqual(len(self.app.routes["mic"].updates), before)
        self.app.save_config()
        stored = self.store.load()
        self.assertFalse(stored["speaker"]["noise"])
        self.assertAlmostEqual(stored["speaker"]["dereverb_strength"], 0.27)

    def test_start_routes_choose_mono_and_stereo_and_allow_device_changes(self):
        self.choose("mic", "output", 8)
        self.choose("speaker", "input", 3)
        self.app.toggle_route("mic")
        self.app.toggle_route("speaker")
        self.app.tick()
        mic, speaker = self.app.routes["mic"], self.app.routes["speaker"]
        self.assertEqual(mic.started[-1][0], (2, 8))
        self.assertEqual(mic.started[-1][1]["channels"], 1)
        self.assertEqual(speaker.started[-1][0], (3, 5))
        self.assertEqual(speaker.started[-1][1]["channels"], 2)
        self.assertEqual(str(self.app.ui["mic"]["input"].cget("state")), "readonly")
        self.app.toggle_route("mic")
        self.app.tick()
        self.assertEqual(str(self.app.ui["mic"]["input"].cget("state")), "readonly")
        self.assertEqual(speaker.snap["state"], "running")

    def test_missing_device_requires_explicit_selection(self):
        self.app.config["mic"]["input"] = {"name": "Removed mic", "hostapi": "Windows WASAPI"}
        self.app.populate_devices()
        with self.assertRaises(ValueError):
            self.app.selected("mic", "input")
        self.app.toggle_route("mic")
        self.assertEqual(self.app.routes["mic"].started, [])
        gui.messagebox.showerror.assert_called_once()
        self.assertIn("Removed mic", self.app.ui["mic"]["input"].get())

    def test_refresh_stops_routes_and_restores_enabled_routes(self):
        self.choose("speaker", "input", 3)
        self.app.toggle_route("speaker")
        self.app.routes["speaker"].snap["state"] = "loading"
        gui.list_devices.reset_mock()
        self.app.refresh_devices()
        gui.list_devices.assert_not_called()
        self.assertTrue(self.app.refresh_pending)
        self.app.tick()
        gui.list_devices.assert_called_once_with(refresh=True)
        self.assertEqual(self.app.routes["speaker"].snap["state"], "running")
        self.assertEqual(len(self.app.routes["speaker"].started), 2)

    def test_refresh_retries_enabled_route_after_device_returns(self):
        self.app.config["mic"].update(enabled=True, input=DEVICES[0].key, output=DEVICES[3].key)
        self.app.route_errors["mic"] = "device unavailable"
        self.app.refresh_devices()
        self.app.tick()
        self.assertEqual(self.app.routes["mic"].snap["state"], "running")
        self.assertNotIn("mic", self.app.route_errors)

    def test_refresh_waits_for_preview_to_release_portaudio(self):
        self.player.busy = True
        gui.list_devices.reset_mock()
        self.app.refresh_devices()
        gui.list_devices.assert_not_called()
        self.player.stop.assert_called_once()
        self.app.tick()
        gui.list_devices.assert_not_called()
        self.player.busy = False
        self.app.tick()
        gui.list_devices.assert_called_once_with(refresh=True)

    def test_refresh_removes_unavailable_devices_and_clears_stale_selection(self):
        self.choose("mic", "input", 2)
        gui.list_devices.return_value = [d for d in DEVICES if d.index != 2]
        self.app.refresh_devices()
        gui.list_devices.assert_called_with(refresh=True)
        self.assertNotIn(2, [d.index for d in self.app.ui["mic"]["input"]._devices])
        with self.assertRaises(ValueError):
            self.app.selected("mic", "input")
        self.assertIn("不可用", self.app.ui["mic"]["input"].get())

    def test_legacy_selection_migrates_to_named_wasapi_endpoint(self):
        self.app.config["mic"]["input"] = dict(name="Microphone", hostapi="MME")
        self.app.populate_devices()
        self.assertEqual(self.app.selected("mic", "input").index, 2)
        self.assertEqual(self.app.config["mic"]["input"], DEVICES[0].key)
        self.assertEqual(self.app.ui["mic"]["input"].get(), "Microphone")

    def test_ambiguous_saved_device_requires_explicit_selection(self):
        self.app.config["mic"]["input"] = DEVICES[0].key
        self.app.devices = DEVICES + [
            DeviceInfo(42, DEVICES[0].name, DEVICES[0].hostapi, 2, 0),
        ]
        self.app.populate_devices()
        with self.assertRaises(ValueError):
            self.app.selected("mic", "input")
        self.assertIn("同名", self.app.ui["mic"]["input"].get())

    def test_event_dispatch_updates_file_status_and_sample_preview(self):
        self.app.events.put(("progress", 0.25))
        self.app.tick()
        self.assertAlmostEqual(self.app.file_progress.get(), 0.25)
        self.assertIn("25%", self.app.file_status.get())
        self.app.events.put(("file_done", {"output": "clean.wav"}))
        self.app.tick()
        self.assertEqual(self.app.file_progress.get(), 1)
        self.assertIn("clean.wav", self.app.file_status.get())
        self.app.sample_job = True
        data = np.ones((480, 1), np.float32)
        self.app.events.put(("sample", data))
        self.app.tick()
        self.assertFalse(self.app.sample_job)
        self.player.play.assert_called_once()
        np.testing.assert_array_equal(self.player.play.call_args.args[0], data)
        self.assertEqual(self.player.play.call_args.args[1], 5)
        self.app.events.put(("file_error", "invalid format"))
        self.app.events.put(("sample_error", "missing sample"))
        self.app.tick()
        self.assertIn("invalid format", self.app.file_status.get())
        self.assertIn("missing sample", self.app.ui["speaker"]["preview_status"].cget("text"))
        self.app.events.put(("file_cancelled", None))
        self.app.events.put(("sample_cancelled", None))
        self.app.tick()
        self.assertIn("已取消", self.app.file_status.get())

    def test_file_worker_runs_off_tk_thread_and_dispatches_results(self):
        main_thread = threading.get_ident()
        observed = []
        def process(src, dst, **kwargs):
            observed.append((threading.get_ident(), src, dst, kwargs))
            kwargs["progress"](0.5)
            return {"output": dst}
        self.app.file_input.set("input.wav")
        self.app.file_output.set(str(Path(self.temp.name) / "out.wav"))
        with patch("openbroadcast.audio.files.process_file", side_effect=process):
            self.app.process_file()
            self.app.file_thread.join(timeout=2)
        self.assertFalse(self.app.file_thread.is_alive())
        self.assertNotEqual(observed[0][0], main_thread)
        self.assertIn("noise_strength", observed[0][3])
        self.assertNotIn("out.wav", self.app.file_status.get())
        self.app.tick()
        self.assertIn("out.wav", self.app.file_status.get())
        self.assertEqual(str(self.app.file_start.cget("state")), "normal")

    def test_stop_preview_discards_already_queued_sample_result(self):
        self.app.sample_job = True
        self.app.events.put(("sample", np.ones((480, 1), np.float32)))
        self.app.stop_preview()
        self.app.tick()
        self.assertEqual(self.player.play.call_count, 0)
        self.assertFalse(self.app.sample_job)
        self.assertIn("取消", self.app.ui["speaker"]["preview_status"].cget("text"))

    def test_recorded_audio_updates_preview_and_rebuild_restores_it(self):
        route = self.app.routes["mic"]
        route.snap["state"] = "running"
        self.app.record("mic")
        self.assertTrue(route.snap["recording"])
        raw = np.full((480, 1), 0.2, np.float32)
        clean = raw * 0.5
        route.data = raw, clean
        route.snap.update(recording=False, recording_ready=True, recorded_seconds=0.01)
        self.app.tick()
        np.testing.assert_array_equal(self.app.ui["mic"]["wave1"].audio, clean)
        self.assertEqual(str(self.app.ui["mic"]["play1"].cget("state")), "normal")
        self.app.theme("light")
        self.app.tick()
        np.testing.assert_array_equal(self.app.ui["mic"]["wave0"].audio, raw)
        self.app.play_recording("mic", 1)
        np.testing.assert_array_equal(self.player.play.call_args.args[0], clean)

    def test_close_to_tray_preserves_work_and_can_restore_repeatedly(self):
        self.app.routes["mic"].snap["state"] = "running"
        self.root.deiconify()
        self.root.update_idletasks()
        with patch.object(gui.sys, "platform", "win32"):
            self.app.on_close()
            self.app.on_close()
        gui.TrayIcon.assert_called_once_with(self.app.events)
        gui.TrayIcon.return_value.start.assert_called_once()
        self.assertNotEqual(self.root.state(), "withdrawn")
        self.app.events.put(("tray_ready", None))
        self.app.tick()
        self.assertEqual(self.root.state(), "withdrawn")
        self.assertFalse(self.app.closing)
        self.assertFalse(self.app.file_cancel.is_set())
        self.assertTrue(all(route.stops == 0 for route in self.app.routes.values()))
        self.player.stop.assert_not_called()
        self.app.events.put(("tray_show", None))
        self.app.tick()
        self.assertEqual(self.root.state(), "normal")
        with patch.object(gui.sys, "platform", "win32"):
            self.app.on_close()
        self.assertEqual(self.root.state(), "withdrawn")
        gui.TrayIcon.assert_called_once()
        self.app.events.put(("tray_exit", None))
        self.app.tick()
        self.assertTrue(self.app.closed)
        self.assertTrue(self.app.file_cancel.is_set())
        self.assertTrue(all(route.stops == 1 for route in self.app.routes.values()))
        gui.TrayIcon.return_value.stop.assert_called_once()

    def test_second_launch_restores_hidden_window_without_stopping_audio(self):
        self.app.routes["mic"].snap["state"] = "running"
        self.app.instance = Mock()
        self.app.instance.activation_requested.return_value = True
        self.app.tray_hide_pending = True
        self.app.events.put(("tray_ready", None))
        self.app.tick()
        self.assertEqual(self.root.state(), "normal")
        self.assertFalse(self.app.tray_hide_pending)
        self.assertEqual(self.app.routes["mic"].stops, 0)
        self.assertFalse(self.app.closing)

    def test_second_launch_does_not_create_gui_or_audio_routes(self):
        with patch.object(gui, "SingleInstance") as gate, patch.object(gui.tk, "Tk") as root:
            gate.return_value.__enter__.return_value.acquire.return_value = False
            self.assertEqual(gui.main(), 0)
            root.assert_not_called()

    def test_tray_failure_keeps_window_accessible_and_audio_running(self):
        self.app.routes["mic"].snap["state"] = "running"
        with patch.object(gui.sys, "platform", "win32"):
            self.app.on_close()
        self.app.events.put(("tray_ready", None))
        self.app.tick()
        self.app.events.put(("tray_error", "notification area unavailable"))
        self.app.tick()
        self.assertEqual(self.root.state(), "normal")
        self.assertFalse(self.app.closing)
        self.assertEqual(self.app.routes["mic"].stops, 0)
        self.assertIsNone(self.app.tray)
        gui.messagebox.showerror.assert_called_once()

    def test_exit_during_tray_startup_does_not_hide_window(self):
        busy = Mock()
        busy.is_alive.return_value = True
        self.app.file_thread = busy
        self.root.deiconify()
        self.root.update_idletasks()
        with patch.object(gui.sys, "platform", "win32"):
            self.app.on_close()
        self.app.request_exit()
        self.app.events.put(("tray_ready", None))
        self.app.tick()
        self.assertTrue(self.app.closing)
        self.assertNotEqual(self.root.state(), "withdrawn")
        gui.TrayIcon.return_value.stop.assert_called_once()

    def test_close_waits_for_background_work_and_saves_preferences(self):
        busy = Mock()
        busy.is_alive.return_value = True
        self.app.file_thread = busy
        self.app.config["theme"] = "light"
        self.app.request_exit()
        self.assertTrue(self.app.closing)
        self.assertTrue(self.app.file_cancel.is_set())
        self.assertTrue(self.app.sample_cancel.is_set())
        self.assertTrue(all(route.stops == 1 for route in self.app.routes.values()))
        self.player.stop.assert_called()
        self.assertEqual(self.store.load()["theme"], "light")
        self.app.tick()
        self.assertFalse(self.app.closed)
        self.assertEqual(str(self.app.file_start.cget("state")), "disabled")
        self.app.request_exit()
        self.assertTrue(all(route.stops == 1 for route in self.app.routes.values()))
        busy.is_alive.return_value = False
        self.app.tick()
        self.assertTrue(self.app.closed)

    def test_settings_save_failure_is_reported_without_crashing(self):
        with patch.object(self.store, "save", side_effect=OSError("disk is read only")):
            self.app.save_config()
        self.assertIn("disk is read only", self.app.status.get())
        self.assertFalse(self.app.closed)
        self.app.tick()
        self.assertIn("disk is read only", self.app.status.get())
        self.app.save_config()
        self.app.tick()
        self.assertNotIn("disk is read only", self.app.status.get())


if __name__ == "__main__":
    unittest.main()
