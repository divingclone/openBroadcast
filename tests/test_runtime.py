"""Audio runtime tests with deterministic devices and delayed mock models."""
import threading
import time
import unittest
from unittest.mock import Mock, patch
from collections import deque
from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np

from openbroadcast.audio.denoiser import Denoiser, HOP, LATENCY, RATE
from openbroadcast.audio.runtime import (
    AudioRoute, DeviceInfo, EffectSettings, list_devices, resolve_device,
)


def eventually(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("Timed out waiting for worker")


class FakeStream:
    def __init__(self, owner, kind, **kwargs):
        self.owner = owner
        self.kind = kind
        self.callback = kwargs["callback"]
        self.active = False
        self.closed = False
        owner.streams.append(self)

    def start(self):
        if self.owner.fail_start == self.kind:
            raise RuntimeError("device start failed")
        self.active = True

    def close(self):
        self.active = False
        self.closed = True


class FakeSD:
    def __init__(self):
        self.streams = []
        self.fail_start = None
        self.default = SimpleNamespace(device=(0, 1))

    def query_hostapis(self):
        return [{"name": "Test API"}]

    def query_devices(self):
        return [
            dict(name="Mic", hostapi=0, max_input_channels=1, max_output_channels=0),
            dict(name="Speaker", hostapi=0, max_input_channels=0, max_output_channels=2),
            dict(name="Unavailable", hostapi=0, max_input_channels=0, max_output_channels=0),
        ]

    def check_input_settings(self, **kwargs):
        pass

    def check_output_settings(self, **kwargs):
        pass

    def InputStream(self, **kwargs):
        return FakeStream(self, "input", **kwargs)

    def OutputStream(self, **kwargs):
        return FakeStream(self, "output", **kwargs)


class FakeEngine:
    latency = HOP

    def __init__(self, model_file, intensity, **kwargs):
        self.model_file = model_file
        self.intensity = intensity
        self.created_thread = threading.get_ident()
        self.reset()

    def reset(self):
        self.delay = deque([np.zeros(HOP, np.float32)])

    def set_intensity(self, value):
        self.intensity = value

    def process(self, block):
        amount = 0.5 if self.model_file.startswith("denoiser") else 0.75
        self.delay.append(block.copy() * (1 - amount * self.intensity))
        return self.delay.popleft()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.sd = FakeSD()
        self.engines = []
        def factory(**kwargs):
            engine = FakeEngine(**kwargs)
            self.engines.append(engine)
            return engine
        self.route = AudioRoute(sd_module=self.sd, engine_factory=factory)

    def tearDown(self):
        self.route.stop(wait=True)

    def test_audio_worker_initializes_com_before_open_and_releases_after_close(self):
        calls = []
        @contextmanager
        def apartment():
            calls.append(("init", threading.get_ident()))
            try:
                yield
            finally:
                calls.append(("cleanup", threading.get_ident(),
                              all(s.closed for s in self.sd.streams)))
        def check(**_):
            self.assertEqual(calls[-1][0], "init")
        with patch("openbroadcast.audio.runtime.audio_thread", apartment), \
                patch.object(self.sd, "check_input_settings", side_effect=check):
            self.start()
            self.route.stop(wait=True)
        self.assertEqual([c[0] for c in calls], ["init", "cleanup"])
        self.assertNotEqual(calls[0][1], threading.get_ident())
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertTrue(calls[1][2])

    def start(self, effects=None, channels=1):
        self.route.start(0, 1, channels=channels, effects=effects)
        eventually(lambda: self.route.snapshot()["state"] in ("running", "error"))
        self.assertEqual(self.route.snapshot()["state"], "running")

    def feed(self, value, channels=1):
        block = np.full((HOP, channels), value, np.float32)
        self.route._input_callback(block, HOP, None, False)
        eventually(lambda: not self.route._outgoing.empty()
                   or self.route.snapshot()["state"] == "error")
        self.assertEqual(self.route.snapshot()["state"], "running")
        result = np.zeros_like(block)
        self.route._output_callback(result, HOP, None, False)
        return result

    def test_single_denoiser_exposes_latency_without_loading_model(self):
        self.assertEqual(Denoiser.__new__(Denoiser).latency, LATENCY)

    def test_devices_filter_and_resolve_stable_identity(self):
        with patch("openbroadcast.audio.runtime.sys.platform", "linux"):
            devices = list_devices(self.sd)
        self.assertEqual(len(devices), 2)
        self.assertTrue(devices[0].default_input)
        self.assertTrue(devices[1].default_output)
        saved = devices[0].key
        moved = [DeviceInfo(17, "Mic", "Test API", 1, 0)]
        self.assertEqual(resolve_device(saved, "input", moved), 17)
        self.assertIsNone(resolve_device(saved, "output", moved))
        self.assertIsNone(resolve_device({"name": "Removed", "hostapi": "Test API"},
                                         "input", devices))
        self.assertIsNone(resolve_device(saved, "input", moved * 2))
        with self.assertRaises(ValueError):
            resolve_device(saved, "invalid", devices)

    def test_windows_lists_only_active_wasapi_endpoints_and_uses_their_defaults(self):
        sd = Mock()
        sd.default.device = (0, 1)  # Global defaults point at legacy MME.
        sd.query_hostapis.return_value = [
            dict(name="MME"),
            dict(name="Windows WASAPI", default_input_device=2, default_output_device=3),
            dict(name="Windows WDM-KS"),
        ]
        sd.query_devices.return_value = [
            dict(name="Mic", hostapi=0, max_input_channels=2, max_output_channels=0),
            dict(name="Speaker", hostapi=0, max_input_channels=0, max_output_channels=2),
            dict(name="Mic", hostapi=1, max_input_channels=2, max_output_channels=0),
            dict(name="Speaker", hostapi=1, max_input_channels=0, max_output_channels=2),
            dict(name="Disabled driver pin", hostapi=2, max_input_channels=2, max_output_channels=0),
            dict(name="Empty endpoint", hostapi=1, max_input_channels=0, max_output_channels=0),
        ]
        with patch("openbroadcast.audio.runtime.sys.platform", "win32"):
            devices = list_devices(sd, refresh=True)
        self.assertEqual([d.index for d in devices], [2, 3])
        self.assertTrue(devices[0].default_input)
        self.assertTrue(devices[1].default_output)
        self.assertEqual(devices[0].label, "Mic")
        self.assertLess(sd.mock_calls.index(unittest.mock.call._terminate()),
                        sd.mock_calls.index(unittest.mock.call._initialize()))
        self.assertLess(sd.mock_calls.index(unittest.mock.call._initialize()),
                        sd.mock_calls.index(unittest.mock.call.query_devices()))

    def test_windows_does_not_fall_back_to_driver_pins_if_wasapi_is_empty(self):
        with patch("openbroadcast.audio.runtime.sys.platform", "win32"):
            self.assertEqual(list_devices(self.sd), [])

    def test_legacy_device_migration_requires_complete_unique_name(self):
        devices = [DeviceInfo(22, "Microphone (USB audio)", "Windows WASAPI", 2, 0)]
        self.assertEqual(resolve_device(dict(name="Microphone (USB audio)", hostapi="MME"),
                                        "input", devices), 22)
        self.assertIsNone(resolve_device(dict(name="Microphone (USB", hostapi="MME"),
                                         "input", devices))
        self.assertIsNone(resolve_device(dict(name="Microphone (USB audio)", hostapi="MME"),
                                         "input", devices * 2))

    def test_bypass_and_restart_no_stale_buffers(self):
        self.start(EffectSettings(noise=False))
        np.testing.assert_array_equal(self.feed(0.2), np.full((HOP, 1), 0.2, np.float32))
        self.assertEqual(self.engines, [])
        self.route._outgoing.put_nowait(np.ones((HOP, 1), np.float32))
        self.route.stop(wait=True)
        self.assertEqual(self.route.snapshot()["state"], "idle")
        self.assertTrue(all(s.closed for s in self.sd.streams))
        self.start(EffectSettings(noise=False))
        self.assertTrue(self.route._outgoing.empty())
        np.testing.assert_array_equal(self.feed(0.3), np.full((HOP, 1), 0.3, np.float32))

    def test_stereo_independent_models_loaded_in_worker(self):
        self.start(EffectSettings(noise=True, dereverb=True), channels=2)
        self.assertEqual(len(self.engines), 4)
        self.assertTrue(all(e.created_thread != threading.get_ident() for e in self.engines))
        self.assertEqual(self.route.snapshot()["latency_ms"], 20)
        self.feed(0.5, channels=2)
        self.feed(0.5, channels=2)
        result = self.feed(0.5, channels=2)
        np.testing.assert_allclose(result, 0.0625)
        block = np.column_stack((np.full(HOP, 0.2), np.full(HOP, 0.8))).astype(np.float32)
        self.route._input_callback(block, HOP, None, False)
        eventually(lambda: not self.route._outgoing.empty())
        self.route._outgoing.get_nowait()
        self.feed(0, channels=2)
        result = self.feed(0, channels=2)
        np.testing.assert_allclose(result[:, 0], 0.025)
        np.testing.assert_allclose(result[:, 1], 0.1)

    def test_effect_toggle_and_strength_apply(self):
        self.start(EffectSettings(noise=False))
        self.route.update_effects(EffectSettings(noise=True, noise_strength=0.0))
        eventually(lambda: self.route.snapshot()["latency_ms"] == 10)
        self.feed(0.4)
        np.testing.assert_allclose(self.feed(0.4), 0.4)
        self.route.update_effects(EffectSettings(noise=True, noise_strength=1.0))
        eventually(lambda: self.engines[0].intensity == 1.0)
        self.feed(0.4)
        np.testing.assert_allclose(self.feed(0.4), 0.2)
        self.route.update_effects(EffectSettings(noise=False))
        eventually(lambda: self.route.snapshot()["latency_ms"] == 0)
        np.testing.assert_allclose(self.feed(0.4), 0.4)

    def test_recording_aligned_and_duration_bounded(self):
        self.start()
        self.feed(0.9)
        self.route.start_recording(max_seconds=0.025)
        self.feed(0.2)
        self.feed(0.4)
        self.feed(0.6)
        self.feed(0.8)
        raw, clean = self.route.get_recording()
        self.assertEqual(raw.shape, (1200, 1))
        np.testing.assert_allclose(raw[:HOP], 0.2)
        np.testing.assert_allclose(raw[HOP:2*HOP], 0.4)
        np.testing.assert_allclose(raw[2*HOP:], 0.6)
        np.testing.assert_allclose(clean, raw * 0.5)
        self.assertTrue(self.route.snapshot()["recording_ready"])
        self.assertAlmostEqual(self.route.snapshot()["recorded_seconds"], 0.025)
        with self.assertRaises(ValueError):
            self.route.start_recording(21)

    def test_recording_stop_and_topology_change(self):
        self.start(EffectSettings(noise=False))
        self.route.start_recording()
        self.feed(0.3)
        self.route.stop_recording()
        self.assertEqual(self.route.get_recording()[0].shape, (HOP, 1))
        self.route.start_recording()
        self.route.update_effects(EffectSettings())
        eventually(lambda: self.route.snapshot()["latency_ms"] == 10)
        self.assertFalse(self.route.snapshot()["recording"])
        self.assertTrue(self.route.snapshot()["recording_error"])
        self.assertIsNone(self.route.get_recording())

    def test_device_start_failure_closes_both_streams(self):
        self.sd.fail_start = "input"
        self.route.start(0, 1, effects=EffectSettings(noise=False))
        eventually(lambda: self.route.snapshot()["state"] == "error")
        self.route.stop(wait=True)
        self.assertIn("device start failed", self.route.snapshot()["error"])
        self.assertEqual(len(self.sd.streams), 2)
        self.assertTrue(all(s.closed for s in self.sd.streams))

    def test_worker_failure_is_observable_and_closes_streams(self):
        self.start()
        def fail(_block):
            raise RuntimeError("inference failure")
        self.engines[0].process = fail
        self.route._input_callback(np.ones((HOP, 1), np.float32), HOP, None, False)
        eventually(lambda: self.route.snapshot()["state"] == "error")
        self.route.stop(wait=True)
        self.assertIn("inference failure", self.route.snapshot()["error"])
        self.assertTrue(all(s.closed for s in self.sd.streams))

    def test_callback_and_device_disconnect_errors(self):
        self.start(EffectSettings(noise=False))
        self.route._input_callback(np.ones((13, 1), np.float32), 13, None, False)
        eventually(lambda: self.route.snapshot()["state"] == "error")
        self.route.stop(wait=True)
        self.assertRegex(self.route.snapshot()["error"], "13 frames|13 帧")
        self.start(EffectSettings(noise=False))
        self.sd.streams[-1].active = False
        eventually(lambda: self.route.snapshot()["state"] == "error")
        self.assertRegex(self.route.snapshot()["error"], "disconnected|断开连接")

    def test_output_underrun_and_queue_overflow_statistics(self):
        self.start(EffectSettings(noise=False))
        output = np.ones((HOP, 1), np.float32)
        self.route._output_callback(output, HOP, None, True)
        np.testing.assert_array_equal(output, 0)
        self.assertEqual(self.route.snapshot()["output_underrun"], 1)
        self.assertEqual(self.route.snapshot()["device_status"], 1)
        for _ in range(12):
            self.route._offer(self.route._outgoing, output, "output_drop")
        self.assertEqual(self.route.snapshot()["output_drop"], 4)

    def test_routes_have_independent_lifecycles_and_effects(self):
        other = AudioRoute("speaker", sd_module=FakeSD(), engine_factory=FakeEngine)
        try:
            self.start(EffectSettings(noise=False))
            other.start(0, 1, channels=2, effects=EffectSettings())
            eventually(lambda: other.snapshot()["state"] == "running")
            self.route.stop(wait=True)
            self.assertEqual(other.snapshot()["state"], "running")
            self.assertEqual(other.snapshot()["channels"], 2)
            self.assertEqual(other.snapshot()["latency_ms"], 10)
        finally:
            other.stop(wait=True)

    def test_stop_during_model_loading_never_opens_stream(self):
        entered, released = threading.Event(), threading.Event()
        def factory(**kwargs):
            entered.set()
            released.wait(2)
            return FakeEngine(**kwargs)
        self.route = AudioRoute(sd_module=self.sd, engine_factory=factory)
        self.route.start(0, 1)
        self.assertTrue(entered.wait(1))
        self.route.stop()
        self.assertEqual(self.route.snapshot()["state"], "stopping")
        with self.assertRaises(RuntimeError):
            self.route.start(0, 1)
        released.set()
        self.route.stop(wait=True)
        self.assertEqual(self.route.snapshot()["state"], "idle")
        self.assertEqual(self.sd.streams, [])

    def test_validation(self):
        with self.assertRaises(ValueError):
            EffectSettings(noise_strength=float("nan"))
        with self.assertRaises(ValueError):
            EffectSettings(dereverb_strength=1.1)
        with self.assertRaises(ValueError):
            self.route.start(0, 1, channels=3)
        with self.assertRaises(RuntimeError):
            self.route.start_recording()


if __name__ == "__main__":
    unittest.main()
