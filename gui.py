"""Broadcast 2.3-style audio controls, implemented with standard Tkinter."""
from __future__ import annotations

from .i18n import tr, readme_filename

import queue
import sys
import time
import threading
from concurrent.futures import CancelledError
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np

from . import __version__
from .audio.denoiser import RATE, HOP, Denoiser
from .audio.runtime import AudioRoute, EffectSettings, list_devices, device_matches
from .audio.player import PreviewPlayer
from .audio.samples import installed_samples, read_sample
from .audio.inference import discover_gpus, selected_gpu, inference_options
from .settings import SettingsStore
from .ui_widgets import IconButton, NavButton, ThinSlider, draw_icon
from .tray import TrayIcon
from . import startup
from .single_instance import SingleInstance

GREEN = "#76b900"
FONT = "Microsoft YaHei UI"
PALETTES = {
    "dark": dict(bg="#191919", header="#262626", field="#363636", line="#333333",
                 text="#e7e7e7", muted="#a9a9a9", track="#555555"),
    "light": dict(bg="#fafafa", header="#eeeeee", field="#e2e2e2", line="#d1d1d1",
                  text="#202020", muted="#666666", track="#b0b0b0"),
}


class Switch(tk.Canvas):
    def __init__(self, parent, app, variable, command=None, disabled=False):
        super().__init__(parent, width=36, height=24, bg=app.c["bg"],
                         highlightthickness=0, takefocus=not disabled,
                         cursor="arrow" if disabled else "hand2")
        self.app, self.var, self.command, self.disabled = app, variable, command, disabled
        self.bind("<Button-1>", self.toggle)
        self.bind("<space>", self.toggle)
        self.bind("<Return>", self.toggle)
        self.bind("<FocusIn>", lambda _: self.draw())
        self.bind("<FocusOut>", lambda _: self.draw())
        self.draw()

    def toggle(self, _=None):
        if not self.disabled:
            self.var.set(not self.var.get())
            self.draw()
            if self.command:
                self.command()
        return "break"

    def draw(self):
        self.delete("all")
        enabled = self.var.get() and not self.disabled
        color = GREEN if enabled else self.app.c["track"]
        self.create_line(10, 12, 27, 12, width=16, fill=color, capstyle="round")
        x = 27 if enabled else 10
        self.create_oval(x-6, 6, x+6, 18, fill="#ffffff" if not self.disabled else "#999999", outline="")
        if self.tk.call("focus") == str(self):
            self.create_rectangle(1, 1, 35, 23, outline=GREEN)


class Meter(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, height=17, bg=app.c["bg"], highlightthickness=0)
        self.app, self.level = app, 0.0
        self.bind("<Configure>", lambda _: self.draw(self.level))

    def draw(self, peak):
        self.level = max(float(peak), self.level * .78)
        self.delete("all")
        segments = max(12, self.winfo_width() // 13)
        value = max(0, min(1, (20*np.log10(max(self.level, 1e-8)) + 60)/60))
        width = self.winfo_width()/segments
        for i in range(segments):
            color = (GREEN if i < segments*.85 else "#d9b548") if i < value*segments else self.app.c["track"]
            self.create_rectangle(i*width+1, 5, (i+1)*width-3, 11, fill=color, outline="")


class Waveform(tk.Canvas):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c["bg"], height=34, highlightthickness=0, width=100)
        self.app, self.audio = app, None
        self.bind("<Configure>", lambda _: self.draw())

    def set_audio(self, audio):
        self.audio = None if audio is None else np.asarray(audio)
        self.draw()

    def draw(self):
        self.delete("all")
        w = max(1, self.winfo_width())
        self.create_line(0, 17, w, 17, fill=self.app.c["line"])
        if self.audio is None or not self.audio.size:
            return
        values = self.audio if self.audio.ndim == 1 else np.max(np.abs(self.audio), axis=1)
        for x, chunk in enumerate(np.array_split(values, min(w//3 or 1, len(values)))):
            height = min(15, float(np.max(np.abs(chunk))) * 40)
            self.create_line(x*3, 17-height, x*3, 17+height, fill=GREEN)


class Scroller(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.c["bg"])
        self.canvas = tk.Canvas(self, bg=app.c["bg"], highlightthickness=0, width=420)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=app.c["bg"])
        self.item = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.item, width=e.width))


class App:
    def __init__(self, root, store=None):
        self.root = root
        self.instance = None
        self.store = store or SettingsStore()
        self.config = self.store.load()
        self.gpus = discover_gpus()
        legacy_gpu = selected_gpu(self.config, self.gpus)
        if legacy_gpu and not self.config["gpu"] and self.config["inference_mode"] == "gpu":
            self.config["gpu"] = legacy_gpu.key
        self.c = PALETTES[self.config["theme"]]
        self.routes = {key: AudioRoute(key) for key in ("mic", "speaker")}
        self.events = queue.Queue()
        self.player = PreviewPlayer()
        self.devices = []
        self.sample_refs = installed_samples()
        self.sample_audio = None
        self.sample_job = False
        self.sample_cancel = threading.Event()
        self.file_thread = None
        self.file_cancel = threading.Event()
        self.file_request = None
        self.file_restart = False
        self.file_restart_due = 0
        self.closed = self.closing = False
        self.tray = None
        self.tray_ready = False
        self.tray_hide_pending = False
        self.pending_routes = {}
        self.route_errors = {}
        self.refresh_pending = False
        self.preview_request = None
        self.preview_context = None
        self.sample_restart = False
        self.sample_playing = False
        self.sample_restart_due = 0
        self.save_timer = None
        self.layout_timer = None
        self.page = "audio"
        self.expanded = self.config["expanded"]
        self.expansions = {}
        self.ui, self.vars = {}, {}
        self._shown_recordings = {}
        self._playback_error = ""
        self._settings_error = ""
        for key in self.routes:
            cfg = self.config[key]
            self.vars[key] = {
                "noise": tk.BooleanVar(value=cfg["noise"]),
                "dereverb": tk.BooleanVar(value=cfg["dereverb"]),
                "noise_strength": tk.DoubleVar(value=cfg["noise_strength"]),
                "dereverb_strength": tk.DoubleVar(value=cfg["dereverb_strength"]),
            }
        self.sample_effect = tk.BooleanVar(value=True)
        self.sample_selection = tk.StringVar(value=next(iter(self.sample_refs), ""))
        self.file_input, self.file_output = tk.StringVar(), tk.StringVar()
        self.file_status = tk.StringVar(value=tr('选择音频文件，应用麦克风效果设置。'))
        self.file_progress = tk.DoubleVar()
        self.status = tk.StringVar(value=tr('就绪 · 仅音频'))
        root.title("OPENBROADCAST")
        root.geometry("1120x820" if self.expanded else "560x820")
        root.minsize(560, 620)
        root.option_add("*Font", (FONT, -12))
        self._icon = tk.PhotoImage(width=32, height=32)
        self._icon.put("#191919", to=(0, 0, 32, 32))
        for x, height in ((5, 8), (10, 18), (15, 26), (20, 14), (25, 8)):
            self._icon.put(GREEN, to=(x, 16-height//2, x+3, 16+height//2))
        root.iconphoto(True, self._icon)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        # Bind only our main window; ttk popdowns have their own toplevel.
        root.bind("<MouseWheel>", self._wheel, add="+")
        root.bind("<Control-1>", lambda _: self.show_page("audio"))
        root.bind("<Control-2>", lambda _: self.show_page("files"))
        root.bind("<Control-3>", lambda _: self.show_page("settings"))
        root.bind("<Escape>", lambda _: self.stop_preview())
        root.bind("<Configure>", self.resize, add="+")
        root.bind("<Map>", lambda e: root.after_idle(self.native_theme) if e.widget == root else None, add="+")
        self.build()
        # Closed selection fields must never change on a stray wheel gesture.
        # The separate ComboboxListbox bindings still scroll an open popup.
        for sequence in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            root.tk.call("bind", "TCombobox", sequence, "break")
        self.refresh_devices()
        self.ensure_tray()
        self.tick()

    def frame(self, parent, **kwargs):
        return tk.Frame(parent, bg=self.c["bg"], **kwargs)

    def label(self, parent, text="", muted=False, **kwargs):
        opts = dict(text=text, bg=self.c["bg"], fg=self.c["muted"] if muted else self.c["text"])
        opts.update(kwargs)
        label = tk.Label(parent, **opts)
        if "wraplength" in kwargs:
            maximum = kwargs["wraplength"]
            parent.bind("<Configure>", lambda e: label.configure(
                wraplength=min(maximum, max(120, e.width-8))) if label.winfo_exists() else None, add="+")
        return label

    def button(self, parent, text, command, accent=False, **kwargs):
        opts = dict(text=text, command=command, relief="flat", bd=0,
                    bg=GREEN if accent else self.c["field"],
                    fg="#111111" if accent else self.c["text"],
                    activebackground="#8bcb20" if accent else self.c["track"],
                    activeforeground=self.c["text"], disabledforeground=self.c["muted"],
                    padx=12, pady=5, cursor="hand2", highlightthickness=1,
                    highlightbackground=GREEN if accent else self.c["line"],
                    highlightcolor=GREEN)
        opts.update(kwargs)
        button = tk.Button(parent, **opts)
        base = opts["bg"]
        button.bind("<Enter>", lambda _: button.configure(
            bg="#8bcb20" if accent else self.c["header"]) if str(button["state"]) != "disabled" else None)
        button.bind("<Leave>", lambda _: button.configure(bg=base))
        return button

    def disclosure(self, parent, title, opened=False, state_key=None):
        """Low-profile expandable options; routing does not crowd the effects."""
        box = self.frame(parent)
        box.pack(fill="x")
        header = self.frame(box)
        header.pack(fill="x")
        content = self.frame(box)
        content.header = header
        state_key = state_key or title
        opened = self.expansions.get(state_key, opened)
        expanded = tk.BooleanVar(value=opened)
        def toggle():
            expanded.set(not expanded.get())
            self.expansions[state_key] = expanded.get()
            heading.configure(text=("⌄  " if expanded.get() else "›  ")+title)
            if expanded.get():
                content.pack(fill="x", pady=(6, 10))
            else:
                content.pack_forget()
        heading = self.button(header, ("⌄  " if opened else "›  ")+title, toggle,
                              bg=self.c["bg"], fg=self.c["muted"], highlightthickness=0,
                              padx=0, pady=6, anchor="w", font=(FONT, -12))
        heading.pack(side="left", fill="x", expand=True)
        content.heading = heading
        if opened:
            content.pack(fill="x", pady=(6, 10))
        return content

    def native_theme(self):
        """Color this application's own title bar; keep OS resize/accessibility."""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            self.root.update_idletasks()
            user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
            user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
            user32.GetAncestor.restype = ctypes.c_void_p
            hwnd = user32.GetAncestor(self.root.winfo_id(), 2)
            dark = ctypes.c_int(int(self.config["theme"] == "dark"))
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), 20, ctypes.byref(dark), 4)
            def colorref(hex_color):
                r, g, b = (int(hex_color[i:i+2], 16) for i in (1, 3, 5))
                return ctypes.c_uint(r | g << 8 | b << 16)
            for attribute, value in ((35, self.c["bg"]), (36, self.c["text"]), (34, self.c["line"])):
                color = colorref(value)
                dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attribute, ctypes.byref(color), 4)
        except (AttributeError, OSError, tk.TclError):
            pass

    def line(self, parent):
        tk.Frame(parent, height=1, bg=self.c["line"]).pack(fill="x", pady=16)

    def build(self):
        # Preserve selections not yet explicitly changed (e.g. initial default monitor).
        for key in self.routes:
            for role in ("input", "output", "monitor"):
                if role in self.ui.get(key, {}):
                    try:
                        self.config[key][role] = self.selected(key, role).key
                    except ValueError:
                        pass
        for child in self.root.winfo_children():
            child.destroy()
        self.ui = {}
        self.c = PALETTES[self.config["theme"]]
        self.root.configure(bg=self.c["bg"])
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=self.c["field"],
                        background=self.c["field"], foreground=self.c["text"],
                        arrowcolor=self.c["muted"], borderwidth=0, padding=(9, 5),
                        bordercolor=self.c["field"], lightcolor=self.c["field"],
                        darkcolor=self.c["field"], relief="flat",
                        font=(FONT, -12), arrowsize=12)
        style.map("TCombobox", fieldbackground=[("readonly", self.c["field"])],
                  foreground=[("disabled", self.c["muted"]), ("readonly", self.c["text"])],
                  selectbackground=[("readonly", self.c["field"])],
                  selectforeground=[("readonly", self.c["text"])],
                  bordercolor=[("focus", GREEN), ("!focus", self.c["field"])],
                  lightcolor=[("!disabled", self.c["field"])],
                  darkcolor=[("!disabled", self.c["field"])],
                  background=[("active", self.c["field"])])
        style.configure("Vertical.TScrollbar", background=self.c["field"],
                        troughcolor=self.c["bg"], borderwidth=0, arrowsize=7,
                        bordercolor=self.c["bg"], lightcolor=self.c["field"],
                        darkcolor=self.c["field"], gripcount=0)
        style.layout("Vertical.TScrollbar", [
            ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
                ("Vertical.Scrollbar.thumb", {"sticky": "nswe", "expand": "1"})]})])
        style.map("Vertical.TScrollbar", background=[("active", self.c["track"])])
        style.configure("Horizontal.TProgressbar", background=GREEN, troughcolor=self.c["field"],
                        lightcolor=GREEN, darkcolor=GREEN, bordercolor=self.c["field"], borderwidth=0)
        style.configure("TSpinbox", fieldbackground=self.c["field"], background=self.c["field"],
                        foreground=self.c["text"], arrowcolor=self.c["muted"],
                        bordercolor=self.c["field"], lightcolor=self.c["field"],
                        darkcolor=self.c["field"], padding=(8, 5), arrowsize=12,
                        font=(FONT, -12))
        style.map("TSpinbox", background=[("active", self.c["track"])],
                  bordercolor=[("focus", GREEN), ("!focus", self.c["field"])])
        self.root.option_add("*TCombobox*Listbox.background", self.c["field"])
        self.root.option_add("*TCombobox*Listbox.foreground", self.c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", GREEN)
        shell = self.frame(self.root)
        shell.pack(fill="both", expand=True)
        sidebar = self.frame(shell, width=62)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self.nav = {}
        for name, icon, title in [("audio", "headphones", tr('音频')), ("files", "file", tr('文件')),
                                  ("settings", "settings", tr('设置'))]:
            b = NavButton(sidebar, self, icon, title, lambda p=name: self.show_page(p))
            b.pack(fill="x", pady=(0, 2))
            self.nav[name] = b
        tk.Frame(shell, width=1, bg=self.c["line"]).pack(side="left", fill="y")
        main = self.frame(shell)
        main.pack(side="left", fill="both", expand=True)
        header = tk.Frame(main, bg=self.c["header"], height=56)
        header.pack(fill="x")
        header.pack_propagate(False)
        self.heading = tk.Label(header, bg=self.c["header"], fg=self.c["text"], font=(FONT, -20, "bold"))
        self.heading.pack(side="left", padx=18)
        expand = IconButton(header, self, "collapse" if self.expanded else "expand", self.toggle_layout)
        expand.configure(bg=self.c["header"])
        expand.pack(side="right", padx=(12, 18))
        tk.Label(header, text=tr('仅音频'), fg=self.c["muted"], bg=self.c["header"],
                 font=(FONT,-11)).pack(side="right")
        footer = tk.Frame(main, bg=self.c["header"])
        footer.pack(side="bottom", fill="x")
        tk.Label(footer, textvariable=self.status, bg=self.c["header"],
                 fg=self.c["muted"], anchor="w", font=(FONT, -12)).pack(fill="x", padx=16, pady=10)
        self.pages = {name: self.frame(main) for name in ("audio", "files", "settings")}
        self.build_audio(self.pages["audio"])
        self.build_files(self.pages["files"])
        self.build_settings(self.pages["settings"])
        self.show_page(self.page)
        self.populate_devices()
        self._shown_recordings.clear()
        self.root.after_idle(self.native_theme)

    def show_page(self, page):
        self.page = page
        for name, frame in self.pages.items():
            frame.pack_forget()
            self.nav[name].select(name == page)
        self.pages[page].pack(fill="both", expand=True)
        self.heading.configure(text={"audio": tr('音频'), "files": tr('文件'), "settings": tr('设置')}[page])

    def toggle_layout(self):
        self.expanded = not self.expanded
        self.config["expanded"] = self.expanded
        self.save_config()
        self.root.geometry("1120x820" if self.expanded else "560x820")
        self.build()

    def resize(self, event):
        if event.widget != self.root or event.width < 100 or self.closing:
            return
        desired = event.width >= 920
        if desired == self.expanded:
            return
        if self.layout_timer:
            self.root.after_cancel(self.layout_timer)
        def apply():
            self.layout_timer = None
            desired_now = self.root.winfo_width() >= 920
            if desired_now != self.expanded and not self.closing:
                self.expanded = desired_now
                self.config["expanded"] = self.expanded
                self.save_config()
                self.build()
        self.layout_timer = self.root.after(150, apply)

    def _wheel(self, event):
        widget = event.widget
        # Native Tcl popdowns may not have a Python Widget wrapper. Controls
        # with their own wheel bindings must not also scroll the page.
        if not isinstance(widget, tk.Misc) or widget.winfo_class() in (
                "TCombobox", "Listbox", "Text", "Spinbox", "TSpinbox",
                "Scrollbar", "TScrollbar"):
            return
        while widget is not None and not isinstance(widget, Scroller):
            widget = widget.master
        if widget is not None:
            canvas = widget.canvas
            bounds = canvas.bbox("all")
            if bounds and bounds[3] > canvas.winfo_height():
                canvas.yview_scroll(-int(event.delta/120), "units")
                return "break"

    def build_audio(self, parent):
        left = Scroller(parent, self)
        left.pack(side="left", fill="both", expand=not self.expanded)
        if self.expanded:
            left.configure(width=440)
            left.pack_propagate(False)
            right = Scroller(parent, self)
            right.pack(side="left", fill="both", expand=True)
            preview = right.body
        else:
            preview = left.body
        for key, title in (("mic", tr('麦克风')), ("speaker", tr('扬声器'))):
            controls = self.frame(left.body)
            controls.pack(fill="x", padx=16, pady=(16, 12))
            self.build_route(controls, key, title)
            tests = self.frame(preview)
            tests.pack(fill="x", padx=28 if self.expanded else 16, pady=(32 if key == "mic" else 22, 12))
            self.build_preview(tests, key, title)
        self.button(left.body, tr('刷新设备'), self.refresh_devices, bg=self.c["bg"],
                    fg=self.c["muted"], highlightthickness=0, padx=0).pack(anchor="w", padx=16, pady=14)

    def device_combo(self, parent, key, role):
        combo = ttk.Combobox(parent, state="readonly", width=12)
        combo.pack(fill="x", pady=(4, 8))
        combo.bind("<<ComboboxSelected>>", lambda _: self.device_changed(key, role))
        self.ui[key][role] = combo
        return combo

    def build_route(self, parent, key, title):
        self.ui[key] = {}
        self.device_combo(parent, key, "input" if key == "mic" else "output")
        self.label(parent, tr('{title}效果', title=title), font=(FONT, -16, "bold"), fg=GREEN).pack(anchor="w", pady=(18, 14))
        self.effect(parent, key, "noise", tr('噪音消除'),
                    tr('降低背景噪音') if key == "mic" else tr('降低在扬声器上播放音频的背景噪音'))
        self.effect(parent, key, "dereverb", tr('房间回声消除'),
                    tr('降低混响音效') if key == "mic" else tr('降低在扬声器上播放音频的混响声音'))
        if key == "mic":
            row = self.frame(parent)
            row.pack(fill="x", pady=(8, 4))
            self.label(row, tr('›  音棚音效'), font=(FONT, -14, "bold"), muted=True).pack(side="left")
            Switch(row, self, tk.BooleanVar(value=False), disabled=True).pack(side="right")
            self.label(parent, tr('提升音质，模拟高端录音室效果'), muted=True,
                       font=(FONT, -12)).pack(anchor="w", padx=16, pady=3)
            self.label(parent, tr('尚未移植 · 当前项目未包含音棚音效模型'), muted=True,
                       font=(FONT, -12)).pack(anchor="w", padx=16, pady=(6, 2))
            self.line(parent)
        routing = self.disclosure(parent, tr('音频路由'), state_key=f"{key}:routing")
        self.ui[key]["routing"] = routing
        self.label(routing, tr('发送到（虚拟声卡 / 监听设备）') if key == "mic" else tr('接收来自（虚拟声卡录音端）'),
                   muted=True, font=(FONT, -12)).pack(anchor="w")
        self.device_combo(routing, key, "output" if key == "mic" else "input")
        if key == "speaker":
            self.label(routing, tr('将会议或播放器的输出设为虚拟声卡播放端。'), muted=True,
                       font=(FONT, -12)).pack(anchor="w")
        self.ui[key]["start"] = self.button(routing.header, tr("启用麦克风") if key == "mic" else tr("启用扬声器"),
                                          lambda: self.toggle_route(key),
                                          accent=True, pady=4, font=(FONT, -12))
        self.ui[key]["start"].pack(side="right")
        self.ui[key]["state"] = self.label(parent, tr('未启用'), muted=True, anchor="w",
                                         wraplength=400, justify="left", font=(FONT, -12))
        self.ui[key]["state"].pack(fill="x", pady=(4, 8))

    def effect(self, parent, key, effect, title, description):
        box = self.frame(parent)
        box.pack(fill="x")
        row = self.frame(box)
        row.pack(fill="x")
        details = self.frame(box)
        state_key = f"{key}:{effect}"
        expanded = tk.BooleanVar(value=self.expansions.get(state_key, False))

        def expand():
            expanded.set(not expanded.get())
            self.expansions[state_key] = expanded.get()
            heading.configure(text=("⌄  " if expanded.get() else "›  ")+title)
            if expanded.get():
                details.pack(fill="x", padx=(16, 0), pady=(8, 2))
            else:
                details.pack_forget()

        heading = self.button(row, ("⌄  " if expanded.get() else "›  ")+title, expand, font=(FONT, -14, "bold"),
                              bg=self.c["bg"], padx=0, anchor="w", highlightthickness=0)
        heading.pack(side="left", fill="x", expand=True)
        Switch(row, self, self.vars[key][effect], lambda: self.effects_changed(key)).pack(side="right")
        self.label(box, description, muted=True, font=(FONT, -12)).pack(anchor="w", padx=16, pady=(0, 4))
        self.label(details, tr('强度'), muted=True, font=(FONT, -12)).pack(side="left")
        percent = self.label(details, f"{self.vars[key][effect+'_strength'].get():.0%}", muted=True,
                             width=4, font=(FONT, -12))
        percent.pack(side="right")
        def change(value):
            percent.configure(text=f"{float(value):.0%}")
            self.effects_changed(key)
        ThinSlider(details, self, self.vars[key][effect+"_strength"], change).pack(
            side="right", fill="x", expand=True, padx=18)
        if expanded.get():
            details.pack(fill="x", padx=(16, 0), pady=(8, 2))
        self.line(parent)

    def build_preview(self, parent, key, title):
        meter = Meter(parent, self)
        self.ui[key]["meter"] = meter
        if key == "mic":
            self.label(parent, tr('{title}输出', title=title), muted=True, font=(FONT, -12)).pack(anchor="w")
            meter.pack(fill="x", pady=(4, 28))
        if not self.expanded:
            card = self.frame(parent, highlightbackground=self.c["line"], highlightthickness=1,
                              padx=12, pady=8)
            card.pack(fill="x")
            parent = self.disclosure(card, tr('测试{title}效果', title=title), state_key=f"{key}:test")
            parent.heading.configure(fg=self.c["text"], font=(FONT, -14, "bold"))
        else:
            heading = self.frame(parent)
            heading.pack(fill="x", pady=(0, 8))
            icon = tk.Canvas(heading, width=24, height=24, bg=self.c["bg"], highlightthickness=0)
            icon.pack(side="left", padx=(0, 7))
            draw_icon(icon, "microphone" if key == "mic" else "speaker", 2, 2, 20, self.c["text"])
            self.label(heading, tr('测试{title}效果', title=title), font=(FONT, -14, "bold")).pack(side="left")
        self.label(parent, tr('录制一个样本，对比输入音频与处理后的输出音频。') if key == "mic" else
                   tr('播放样本，了解音频处理如何减少噪音与混响。'),
                   muted=True, font=(FONT, -12), wraplength=450, justify="left").pack(anchor="w")
        if key == "speaker":
            sample_box = self.frame(parent, highlightbackground=self.c["line"], highlightthickness=1)
            sample_box.pack(fill="x", pady=(16, 8))
            sample_row = self.frame(sample_box)
            sample_row.pack(fill="x", padx=12, pady=12)
            values = ([self.sample_audio.name] if self.sample_audio else []) + list(self.sample_refs)
            self.sample_choice = ttk.Combobox(sample_row, state="readonly", values=values, width=16,
                                              textvariable=self.sample_selection)
            self.sample_choice.pack(side="left", fill="x", expand=True, padx=(0, 14))
            self.sample_choice.bind("<<ComboboxSelected>>", self.sample_settings_changed)
            self.ui[key]["sample"] = IconButton(sample_row, self, "play", self.play_sample)
            self.ui[key]["sample"].pack(side="left")
            IconButton(sample_row, self, "stop", self.stop_preview).pack(side="left", padx=(8, 0))
            options = self.frame(parent)
            options.pack(fill="x", pady=(4, 12))
            self.button(options, tr('导入音频…'), self.import_sample, bg=self.c["bg"], fg=self.c["muted"],
                        highlightthickness=0, padx=0).pack(side="left")
            Switch(options, self, self.sample_effect, self.sample_settings_changed).pack(side="right")
            self.label(options, tr('应用效果'), muted=True, font=(FONT, -12)).pack(side="right", padx=10)
            record_parent = self.disclosure(parent, tr('录制当前扬声器音频'), opened=False)
        else:
            record_parent = parent
        box = self.frame(record_parent, highlightbackground=self.c["line"], highlightthickness=1)
        box.pack(fill="x", pady=(14, 10))
        record = self.frame(box)
        record.pack(fill="x", padx=18, pady=11)
        self.label(record, tr('录制语音') if key == "mic" else tr('录制音频'), width=10, anchor="w").pack(side="left")
        b = IconButton(record, self, "record", lambda: self.record(key))
        b.pack(side="left")
        self.ui[key]["record"] = b
        self.ui[key]["record_time"] = self.label(record, "00:00 / 00:20", muted=True, font=("Segoe UI", -11))
        self.ui[key]["record_time"].pack(side="right")
        for which, text in ((0, tr('输入音频')), (1, tr('输出音频'))):
            tk.Frame(box, height=1, bg=self.c["line"]).pack(fill="x")
            row = self.frame(box)
            row.pack(fill="x", padx=18, pady=10)
            self.label(row, text, width=10, anchor="w").pack(side="left")
            button = IconButton(row, self, "play", lambda k=key, n=which: self.play_recording(k, n),
                                state="disabled")
            button.pack(side="left")
            wave = Waveform(row, self)
            wave.pack(side="left", fill="x", expand=True, padx=10)
            self.ui[key][f"play{which}"], self.ui[key][f"wave{which}"] = button, wave
        self.ui[key]["save"] = self.button(record_parent, tr('保存录制的音频样本'), lambda: self.save_recording(key),
                                          state="disabled", bg=self.c["bg"], highlightthickness=0,
                                          padx=0, fg=self.c["muted"], font=(FONT,-12))
        self.ui[key]["save"].pack(anchor="w")
        monitor = self.disclosure(parent, tr('试听设备'), state_key=f"{key}:monitor")
        self.device_combo(monitor, key, "monitor")
        if key == "mic":
            self.button(monitor, tr('停止试听'), self.stop_preview, bg=self.c["bg"],
                        highlightthickness=0).pack(anchor="w")
        self.ui[key]["preview_status"] = self.label(parent, "", muted=True, wraplength=450,
                                                   justify="left", font=(FONT, -12))
        self.ui[key]["preview_status"].pack(fill="x")

    def refresh_devices(self):
        if self.closing or self.refresh_pending:
            return
        self.pending_routes.update({key: 0 for key in self.routes if self.config[key]["enabled"]})
        if self.player.busy or self.sample_job or any(r.busy for r in self.routes.values()):
            self.refresh_pending = True
            self.stop_preview()
            for key, route in self.routes.items():
                if self.config[key]["enabled"]:
                    self.pending_routes[key] = 0
                route.stop()
            self.status.set(tr('正在刷新设备，完成后自动恢复音频…'))
            return
        self._refresh_devices()

    def _refresh_devices(self):
        try:
            self.devices = list_devices(refresh=True)
            self.populate_devices()
        except Exception as exc:
            self.devices = []
            self.populate_devices()
            messagebox.showerror(tr('音频设备'), str(exc), parent=self.root)

    def populate_devices(self):
        for key in self.routes:
            if key not in self.ui:
                continue
            for role in ("input", "output", "monitor"):
                if role not in self.ui[key]:
                    continue
                combo = self.ui[key][role]
                devices = [d for d in self.devices if (d.input_channels if role == "input" else d.output_channels) > 0]
                devices.sort(key=lambda d: ("WASAPI" not in d.hostapi, d.index))
                combo._devices = devices
                combo.configure(values=[d.label for d in devices])
                saved = self.config[key].get(role)
                matches = [i for i, d in enumerate(devices) if saved and device_matches(saved, d)]
                if len(matches) == 1:
                    combo.current(matches[0])
                    self.config[key][role] = devices[matches[0]].key
                elif len(matches) > 1:
                    combo.set(tr('存在同名设备，请重新选择'))
                elif saved:
                    combo.set(tr('设备不可用：')+saved["name"])
                elif not devices:
                    combo.set(tr('没有已启用且已连接的设备'))
                elif devices:
                    if role == "monitor" or (key == "speaker" and role == "output"):
                        combo.current(next((i for i, d in enumerate(devices) if d.default_output), 0))
                    elif key == "mic" and role == "input":
                        combo.current(next((i for i, d in enumerate(devices) if d.default_input), 0))
                    else:
                        combo.set(tr('请选择设备'))

    def selected(self, key, role):
        combo = self.ui[key][role]
        index = combo.current()
        if index < 0:
            raise ValueError({"input": tr('请先选择输入设备。'), "output": tr('请先选择输出设备。'),
                              "monitor": tr('请先选择试听设备。')}[role])
        return combo._devices[index]

    def device_changed(self, key, role):
        self.config[key][role] = self.selected(key, role).key
        self.schedule_save()
        if role == "monitor":
            if self.preview_context and self.preview_context[1] == key and self.player.busy:
                audio, _ = self.preview_context
                position = int(self.player.position)
                self.preview_request = (audio[position:], key)
                self.player.stop()
        else:
            self.reconfigure_route(key)

    def effects(self, key):
        return EffectSettings(**{name: var.get() for name, var in self.vars[key].items()})

    def effects_changed(self, key):
        if self.closing:
            return
        self.config[key].update({name: var.get() for name, var in self.vars[key].items()})
        self.routes[key].update_effects(self.effects(key))
        self.schedule_save()
        if key == "speaker":
            self.sample_settings_changed()
        else:
            self.file_settings_changed()

    def schedule_save(self):
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
        self.save_timer = self.root.after(500, self.save_config)

    def save_config(self):
        self.save_timer = None
        try:
            self.store.save(self.config)
            self._settings_error = ""
        except OSError as exc:
            self._settings_error = tr('设置保存失败：')+str(exc)
            self.status.set(self._settings_error)
            if self.closing:
                messagebox.showerror(tr('设置保存失败'), str(exc), parent=self.root)

    def toggle_route(self, key):
        if self.closing:
            return
        route = self.routes[key]
        if key in self.pending_routes or route.snapshot()["state"] in ("loading", "running", "stopping"):
            self.config[key]["enabled"] = False
            self.pending_routes.pop(key, None)
            self.route_errors.pop(key, None)
            route.stop()
            self.save_config()
            return
        if self.start_route(key, report=True):
            self.config[key]["enabled"] = True
            self.save_config()

    def start_route(self, key, report=False):
        try:
            source, target = self.selected(key, "input"), self.selected(key, "output")
            if ("cable" in source.name.lower() and "cable" in target.name.lower()
                    and source.name.lower().replace("output", "input") == target.name.lower()):
                raise ValueError(tr('同一虚拟声卡的两端不能互相连接，会形成音频回路。'))
            for role in ("input", "output"):
                self.config[key][role] = self.selected(key, role).key
            self.schedule_save()
            self.routes[key].start(source.index, target.index,
                        channels=1 if key == "mic" else min(2, source.input_channels, target.output_channels),
                        effects=self.effects(key), **inference_options(self.config))
            self.route_errors.pop(key, None)
            return True
        except Exception as exc:
            self.route_errors[key] = str(exc)
            if report:
                messagebox.showerror(tr('无法启动音频'), str(exc), parent=self.root)
            return False

    def reconfigure_route(self, key):
        if not self.closing and self.config[key]["enabled"]:
            self.pending_routes[key] = time.monotonic() + .2
            self.routes[key].stop()

    def inference_changed(self):
        for key in self.routes:
            self.reconfigure_route(key)
        self.sample_settings_changed()
        self.file_settings_changed()

    def record(self, key):
        route = self.routes[key]
        try:
            if route.snapshot()["recording"]:
                route.stop_recording()
            else:
                route.start_recording(max_seconds=20)
                self._shown_recordings.pop(key, None)
                for n in (0, 1):
                    self.ui[key][f"wave{n}"].set_audio(None)
        except Exception as exc:
            messagebox.showinfo(tr('录音测试'), str(exc), parent=self.root)

    def play_recording(self, key, which):
        audio = self.routes[key].get_recording()
        if audio is not None:
            self.sample_playing = False
            self.play(audio[which], key)

    def play(self, audio, key):
        try:
            device = self.selected(key, "monitor")
            self.player.play(audio, device.index)
            self.preview_context = (audio, key)
            self._playback_error = ""
            self.ui[key]["preview_status"].configure(text=tr('正在试听 · Esc 停止'))
        except Exception as exc:
            messagebox.showerror(tr('试听'), str(exc), parent=self.root)

    def stop_preview(self):
        self.preview_request = None
        self.preview_context = None
        self.sample_restart = self.sample_playing = False
        self.player.stop()
        self.sample_cancel.set()

    def sample_settings_changed(self, *_):
        if self.closing:
            return
        if self.sample_job or (self.sample_playing and self.player.busy) or self.sample_restart:
            self.sample_restart = True
            self.sample_restart_due = time.monotonic() + .3
            self.preview_request = None
            self.sample_cancel.set()
            self.player.stop()

    def save_recording(self, key):
        audio = self.routes[key].get_recording()
        if audio is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".wav",
                                           initialfile=key+"-processed.wav", filetypes=[(tr('WAV 音频'), "*.wav")])
        if path:
            try:
                import soundfile as sf
                sf.write(path, audio[1], RATE, subtype="PCM_16")
                self.ui[key]["preview_status"].configure(text=tr('录音已保存：')+Path(path).name)
            except Exception as exc:
                messagebox.showerror(tr('保存录音'), str(exc), parent=self.root)

    def import_sample(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[(tr('音频'), "*.wav *.flac *.ogg")])
        if path:
            self.sample_audio = Path(path)
            self.sample_choice.configure(values=[Path(path).name]+list(self.sample_refs))
            self.sample_selection.set(Path(path).name)
            self.sample_settings_changed()

    def play_sample(self):
        if self.player.busy:
            self.sample_restart = True
            self.player.stop()
            return
        if self.sample_job:
            return
        try:
            self.selected("speaker", "monitor")
            choice = self.sample_selection.get()
            effects = self.effects("speaker") if self.sample_effect.get() else EffectSettings(noise=False, dereverb=False)
            reference = self.sample_refs.get(choice)
            custom = self.sample_audio
            if reference is None and custom is None:
                raise ValueError(tr('未找到本机 Broadcast 样本，请导入试听文件。'))
            options = (inference_options(self.config) if effects.noise or effects.dereverb else {})
        except Exception as exc:
            messagebox.showinfo(tr('试听样本'), str(exc), parent=self.root)
            return
        self.sample_job = True
        self.sample_playing = True
        self.sample_cancel.clear()
        self.ui["speaker"]["preview_status"].configure(text=tr('正在处理试听样本…'))
        def worker():
            try:
                if reference:
                    data = read_sample(reference)
                else:
                    import soundfile as sf
                    with sf.SoundFile(custom) as source:
                        if source.samplerate != RATE:
                            raise ValueError(tr('试听文件需为 48 kHz；可先在文件页转换。'))
                        data = source.read(RATE*30, dtype="float32", always_2d=True)
                data = data[:RATE*30, :2]
                stages = []
                if effects.dereverb:
                    stages.append(("dereverb_48k.onnx", effects.dereverb_strength))
                if effects.noise:
                    stages.append(("denoiser_48k.onnx", effects.noise_strength))
                engines = []
                for model, intensity in stages:
                    engines.append([Denoiser(model_file=model, intensity=intensity, **options)
                                    for _ in range(data.shape[1])])
                    if self.sample_cancel.is_set():
                        raise CancelledError
                if engines:
                    latency = sum(stage[0].latency for stage in engines)
                    total = ((len(data) + latency + HOP - 1)//HOP)*HOP
                    padded = np.pad(data, ((0, total-len(data)), (0, 0)))
                    result = np.empty_like(padded)
                    for start in range(0, total, HOP):
                        if self.sample_cancel.is_set():
                            raise CancelledError
                        block = padded[start:start+HOP]
                        for stage in engines:
                            block = np.stack([engine.process(block[:, ch])
                                              for ch, engine in enumerate(stage)], axis=1)
                        result[start:start+HOP] = block
                    data = result[latency:latency+len(data)]
                self.events.put(("sample_cancelled" if self.sample_cancel.is_set() else "sample", data))
            except CancelledError:
                self.events.put(("sample_cancelled", None))
            except Exception as exc:
                self.events.put(("sample_error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="sample-processing").start()

    def build_files(self, parent):
        scroll = Scroller(parent, self)
        scroll.pack(fill="both", expand=True)
        box = self.frame(scroll.body)
        box.pack(fill="x", padx=26, pady=26)
        self.label(box, tr('音频文件处理'), font=(FONT, -18, "bold")).pack(anchor="w")
        self.label(box, tr('使用音频页中的麦克风效果与各自强度，保留声道并导出 48 kHz 音频。'),
                   muted=True, wraplength=780, justify="left").pack(anchor="w", pady=12)
        for var, title, save in ((self.file_input, tr('输入文件'), False), (self.file_output, tr('输出文件'), True)):
            self.label(box, title).pack(anchor="w", pady=(18, 6))
            row = self.frame(box)
            row.pack(fill="x")
            tk.Entry(row, textvariable=var, bg=self.c["field"], fg=self.c["text"],
                     insertbackground=self.c["text"], relief="flat").pack(side="left", fill="x", expand=True, ipady=9)
            self.button(row, tr('浏览…'), lambda s=save: self.choose_file(s)).pack(side="right", padx=(10, 0))
        self.line(box)
        self.file_effect_label = self.label(box, "", muted=True, wraplength=780, justify="left")
        self.file_effect_label.pack(anchor="w", pady=6)
        self.button(box, tr('调整音频效果'), lambda: self.show_page("audio")).pack(anchor="w", pady=8)
        ttk.Progressbar(box, variable=self.file_progress, maximum=1).pack(fill="x", pady=(22, 14))
        self.label(box, textvariable=self.file_status, wraplength=800, justify="left").pack(anchor="w")
        actions = self.frame(box)
        actions.pack(fill="x", pady=20)
        self.file_start = self.button(actions, tr('开始处理'), self.process_file, accent=True)
        self.file_start.pack(side="left")
        self.file_stop = self.button(actions, tr('取消'), self.cancel_file, state="disabled")
        self.file_stop.pack(side="left", padx=12)
        self.label(box, tr('支持 WAV / FLAC / OGG 输入，WAV / FLAC 输出。\n视频功能尚未实现。'),
                   muted=True, justify="left").pack(anchor="w", pady=20)

    def choose_file(self, save):
        if save:
            path = filedialog.asksaveasfilename(parent=self.root, defaultextension=".wav",
                                               filetypes=[(tr('WAV 音频'), "*.wav"), (tr('FLAC 音频'), "*.flac")])
        else:
            path = filedialog.askopenfilename(parent=self.root, filetypes=[(tr('音频文件'), "*.wav *.flac *.ogg")])
        if path:
            (self.file_output if save else self.file_input).set(path)
            if not save and not self.file_output.get():
                src = Path(path)
                self.file_output.set(str(src.with_name(src.stem+"-processed.wav")))

    def file_settings_changed(self):
        if not self.closing and self.file_request and (
                self.file_restart or (self.file_thread and self.file_thread.is_alive())):
            self.file_restart = True
            self.file_restart_due = time.monotonic() + .3
            self.file_cancel.set()
            self.file_status.set(tr('设置已更改，正在按新设置重新处理…'))

    def cancel_file(self):
        self.file_restart = False
        self.file_cancel.set()

    def process_file(self, restart=False):
        if self.file_thread and self.file_thread.is_alive():
            return
        src, dst = (self.file_request if restart else
                    (self.file_input.get().strip(), self.file_output.get().strip()))
        if not src or not dst:
            messagebox.showinfo(tr('音频文件'), tr('请选择输入文件和输出位置。'), parent=self.root)
            return
        if not restart and Path(dst).exists() and Path(src).resolve() != Path(dst).resolve():
            if not messagebox.askyesno(tr('替换输出文件'), tr('是否替换已有文件？\n{dst}', dst=dst), parent=self.root):
                return
        try:
            inference = inference_options(self.config)
        except ValueError as exc:
            messagebox.showerror(tr('推理设备'), str(exc), parent=self.root)
            return
        self.file_cancel.clear()
        self.file_request = (src, dst)
        self.file_progress.set(0)
        self.file_status.set(tr('正在载入模型…'))
        options = {k: v.get() for k, v in self.vars["mic"].items()}
        options.update(inference)
        def worker():
            try:
                from .audio.files import process_file
                result = process_file(src, dst, **options, cancel=self.file_cancel,
                                      progress=lambda p: self.events.put(("progress", p)))
                self.events.put(("file_done", result))
            except CancelledError:
                self.events.put(("file_cancelled", None))
            except Exception as exc:
                self.events.put(("file_error", str(exc)))
        self.file_thread = threading.Thread(target=worker, daemon=True, name="file-processing")
        self.file_thread.start()

    def build_settings(self, parent):
        scroll = Scroller(parent, self)
        scroll.pack(fill="both", expand=True)
        box = self.frame(scroll.body)
        box.pack(fill="x", padx=26, pady=26)
        self.label(box, "OpenBroadcast", font=("Segoe UI", -26, "bold")).pack(anchor="w")
        self.label(box, tr('版本 {__version__}  ·  Tkinter / ONNX Runtime', __version__=__version__), muted=True).pack(anchor="w", pady=8)
        self.label(box, tr('参考本机 NVIDIA Broadcast 2.3.0 的音频界面。\n独立移植项目，仅实现音频；视频功能尚未实现。'),
                   muted=True, justify="left", wraplength=750).pack(anchor="w", pady=8)
        self.line(box)
        self.label(box, tr('音频处理'), font=(FONT, -16, "bold")).pack(anchor="w")
        self.label(box, tr('设置自动应用于正在运行的音频；切换设备时可能短暂中断。'), muted=True,
                   wraplength=750).pack(anchor="w", pady=10)
        row = self.frame(box)
        row.pack(fill="x", pady=10)
        self.label(row, tr('推理设备'), width=13, anchor="w").pack(side="left")
        self.inference_mode = tk.StringVar(value=self.config["inference_mode"])
        for value, title in (("cpu", tr('CPU 处理器')), ("gpu", tr('GPU 显卡'))):
            tk.Radiobutton(row, text=title, variable=self.inference_mode, value=value,
                           command=self.change_inference_mode, font=(FONT, -13),
                           bg=self.c["bg"], fg=self.c["text"], selectcolor=self.c["field"],
                           activebackground=self.c["bg"], activeforeground=GREEN,
                           highlightthickness=0).pack(side="left", padx=(0, 16))
        self.cpu_settings = self.frame(box)
        self.label(self.cpu_settings, tr('CPU 线程'), width=13, anchor="w").pack(side="left")
        threads = tk.StringVar(value=str(self.config["threads"]))
        spin = ttk.Spinbox(self.cpu_settings, from_=1, to=256, textvariable=threads, width=6)
        spin.pack(side="left")
        def commit(_=None):
            try:
                value = int(threads.get())
                if not 1 <= value <= 256:
                    raise ValueError
                self.setting("threads", value)
            except ValueError:
                threads.set(str(self.config["threads"]))
        spin.configure(command=commit)
        def threads_edited(*_):
            try:
                value = int(threads.get())
                if 1 <= value <= 256 and value != self.config["threads"]:
                    self.setting("threads", value)
            except ValueError:
                pass
        threads.trace_add("write", threads_edited)
        spin.bind("<FocusOut>", commit)
        spin.bind("<Return>", commit)
        self.gpu_settings = self.frame(box)
        self.label(self.gpu_settings, tr('推理显卡'), muted=True).pack(anchor="w", pady=(0, 8))
        self.gpu_combo = ttk.Combobox(self.gpu_settings, values=[d.label for d in self.gpus],
                                      state="readonly", width=28)
        self.gpu_combo.pack(fill="x")
        device = selected_gpu(self.config, self.gpus)
        if device:
            self.gpu_combo.current(self.gpus.index(device))
        elif self.config["gpu"]:
            self.gpu_combo.set(tr('显卡已变更：') + self.config["gpu"]["name"])
        else:
            self.gpu_combo.set(tr('请选择显卡') if self.gpus else tr('未检测到可选择的显卡'))
        self.gpu_combo.bind("<<ComboboxSelected>>", self.change_gpu)
        self.inference_hint = self.label(box, "", muted=True, justify="left", wraplength=390)
        self.inference_hint.pack(anchor="w", pady=(10, 0))
        self.update_inference_controls()
        self.line(box)
        self.label(box, tr('外观'), font=(FONT, -16, "bold")).pack(anchor="w", pady=(0, 14))
        row = self.frame(box)
        row.pack(fill="x")
        self.label(row, tr('显示实时处理性能')).pack(side="left")
        perf = tk.BooleanVar(value=self.config["show_performance"])
        Switch(row, self, perf, lambda: self.setting("show_performance", perf.get())).pack(side="left", padx=18)
        row = self.frame(box)
        row.pack(fill="x", pady=18)
        self.label(row, tr('主题')).pack(side="left", padx=(0, 24))
        self.button(row, tr('深色'), lambda: self.theme("dark")).pack(side="left", padx=4)
        self.button(row, tr('浅色'), lambda: self.theme("light")).pack(side="left", padx=4)
        self.line(box)
        self.label(box, tr('音频连接'), font=(FONT, -16, "bold")).pack(anchor="w")
        help_text = (
            tr('麦克风：真实麦克风 → OpenBroadcast → 虚拟声卡播放端 → 通话软件。\n扬声器：通话软件 → 另一条虚拟声卡 → OpenBroadcast → 耳机。\n\n两路同时使用时，请用不同的虚拟声卡，避免循环。程序不安装虚拟驱动。\n音棚音效模型尚未移植，界面中已禁用该项。降噪与去混响可独立使用。\n\n快捷键：Ctrl+1 音频 · Ctrl+2 文件 · Ctrl+3 设置 · Esc 停止试听。\n设备与强度自动保存；启动程序时自动恢复上次启用的音频路由。')
        )
        self.label(box, help_text, muted=True, wraplength=750, justify="left").pack(anchor="w", pady=14)
        self.button(box, tr('打开使用说明'), self.show_readme).pack(anchor="w", pady=8)
        self.line(box)
        self.label(box, tr('后台运行'), font=(FONT, -16, "bold")).pack(anchor="w")
        row = self.frame(box)
        row.pack(fill="x", pady=12)
        self.label(row, tr('开机自启（登录 Windows 后）')).pack(side="left")
        try:
            enabled = startup.is_enabled()
        except OSError:
            enabled = False
        self.startup_enabled = tk.BooleanVar(value=enabled)
        self.startup_switch = Switch(row, self, self.startup_enabled, self.change_startup,
                                     disabled=sys.platform != "win32")
        self.startup_switch.pack(side="left", padx=18)
        self.label(box, tr('登录后进入托盘，并恢复上次启用的音频路由。\n移动便携目录后，请关闭再开启此选项以更新路径。'),
                   muted=True, wraplength=750, justify="left").pack(anchor="w")
        self.label(box, tr('Windows：关闭主窗口会隐藏到右下角系统托盘，音频处理继续运行。\n点击托盘图标可恢复窗口；右键选择“退出 OpenBroadcast”可完全退出。\n标题栏的最小化按钮仍最小化到任务栏。'),
                   muted=True, wraplength=750, justify="left").pack(anchor="w", pady=14)
        self.button(box, tr('退出 OpenBroadcast'), self.request_exit).pack(anchor="w", pady=8)

    def change_inference_mode(self):
        self.config["inference_mode"] = self.inference_mode.get()
        if self.inference_mode.get() == "gpu" and not self.config["gpu"] and self.gpus:
            index = next((i for i, d in enumerate(self.gpus) if d.available), 0)
            self.gpu_combo.current(index)
            self.change_gpu()
        self.update_inference_controls()
        self.schedule_save()
        self.inference_changed()

    def change_gpu(self, _=None):
        index = self.gpu_combo.current()
        if index >= 0:
            device = self.gpus[index]
            self.config.update(gpu=device.key, provider=device.provider, device_id=device.device_id)
            self.schedule_save()
            if self.config["inference_mode"] == "gpu":
                self.inference_changed()
        self.update_inference_controls()

    def update_inference_controls(self):
        cpu = self.config["inference_mode"] == "cpu"
        self.cpu_settings.pack_forget()
        self.gpu_settings.pack_forget()
        (self.cpu_settings if cpu else self.gpu_settings).pack(
            fill="x", pady=10, before=self.inference_hint)
        if cpu:
            hint = tr('使用 CPU 处理音频，已选显卡不会参与推理。')
        else:
            device = selected_gpu(self.config, self.gpus)
            if device and device.available:
                hint = tr('使用所选显卡处理音频；切换后自动重新载入模型，无需重启程序。')
            elif device:
                hint = tr('已检测到显卡，但当前运行库不支持该 GPU 后端。\n请按使用说明安装 GPU 运行库并重启，或切换到 CPU。')
            else:
                hint = tr('请重新选择显卡；若列表为空，请检查驱动及 GPU 运行库。')
        self.inference_hint.configure(text=hint)

    def setting(self, key, value):
        if self.config[key] == value:
            return
        self.config[key] = value
        self.schedule_save()
        if key == "threads" and self.config["inference_mode"] == "cpu":
            self.inference_changed()

    def change_startup(self):
        try:
            startup.set_enabled(self.startup_enabled.get())
        except OSError as exc:
            self.startup_enabled.set(not self.startup_enabled.get())
            self.startup_switch.draw()
            messagebox.showerror(tr('开机自启'), str(exc), parent=self.root)

    def theme(self, name):
        self.setting("theme", name)
        self.build()

    def show_readme(self):
        window = tk.Toplevel(self.root)
        window.title(tr('OpenBroadcast 使用说明'))
        window.geometry("800x650")
        text = tk.Text(window, wrap="word", bg=self.c["bg"], fg=self.c["text"],
                       font=(FONT, -13), padx=20, pady=20)
        scroll = ttk.Scrollbar(window, command=text.yview)
        scroll.pack(side="right", fill="y")
        text.configure(yscrollcommand=scroll.set)
        text.pack(fill="both", expand=True)
        text.insert("1.0", Path(__file__).with_name(readme_filename()).read_text(encoding="utf-8"))
        text.configure(state="disabled")

    def tick(self):
        if self.closed:
            return
        if self.instance and self.instance.activation_requested():
            self.restore_window()
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "tray_ready":
                self.tray_ready = True
                if self.tray_hide_pending and not self.closing:
                    self.root.withdraw()
                    self.tray_hide_pending = False
            elif kind == "tray_show":
                self.restore_window()
            elif kind == "tray_exit":
                self.request_exit()
            elif kind == "tray_error":
                if self.tray:
                    self.tray.stop()
                self.tray = None
                self.tray_ready = self.tray_hide_pending = False
                if not self.closing:
                    self.restore_window()
                    messagebox.showerror(tr('系统托盘不可用'),
                                         tr('窗口已保留，音频处理继续运行。\n{payload}\n\n可使用标题栏最小化，或在设置页选择“退出 OpenBroadcast”。', payload=payload),
                                         parent=self.root)
            elif kind == "progress":
                self.file_progress.set(float(payload))
                self.file_status.set(tr('正在处理… {value0:.0%}', value0=float(payload)))
            elif kind == "file_done":
                self.file_progress.set(1)
                self.file_status.set(tr('已完成：')+str(payload["output"]))
            elif kind in ("file_error", "file_cancelled"):
                self.file_status.set(tr('已取消，目标文件保持不变。') if kind == "file_cancelled" else tr('处理失败：')+payload)
            elif kind.startswith("sample"):
                self.sample_job = False
                if kind == "sample" and not self.closing and not self.sample_cancel.is_set():
                    self.play(payload, "speaker")
                else:
                    self.ui["speaker"]["preview_status"].configure(
                        text=tr('试听已取消') if kind in ("sample_cancelled", "sample") else str(payload))
        if not self.closing:
            if self.refresh_pending and not (self.player.busy or self.sample_job or
                                            any(r.busy for r in self.routes.values())):
                self._refresh_devices()
                self.refresh_pending = False
            if not self.refresh_pending:
                for key, due in list(self.pending_routes.items()):
                    if time.monotonic() >= due and not self.routes[key].busy:
                        self.pending_routes.pop(key)
                        if self.config[key]["enabled"]:
                            self.start_route(key)
            if (self.sample_restart and time.monotonic() >= self.sample_restart_due
                    and not self.sample_job and not self.player.busy and not self.refresh_pending):
                self.sample_restart = False
                self.play_sample()
            elif self.preview_request is not None and not self.player.busy and not self.refresh_pending:
                audio, key = self.preview_request
                self.preview_request = None
                if len(audio):
                    self.play(audio, key)
            if (self.file_restart and time.monotonic() >= self.file_restart_due and
                    not (self.file_thread and self.file_thread.is_alive())):
                self.file_restart = False
                self.process_file(restart=True)
        total_ms, active = 0, []
        for key, route in self.routes.items():
            snap = route.snapshot()
            state = snap["state"]
            ui = self.ui[key]
            running = state in ("loading", "running", "stopping")
            ui["start"].configure(
                text=tr('取消切换') if key in self.pending_routes else {"loading":tr('停止加载'), "running":tr('停止'), "stopping":tr('正在停止…')}.get(
                    state, tr('启用麦克风') if key == "mic" else tr('启用扬声器')),
                state="disabled" if self.closing else "normal")
            for role in ("input", "output"):
                ui[role].configure(state="disabled" if self.closing else "readonly")
            ui["meter"].draw(snap["output_peak"] if state == "running" else 0)
            text = {"idle":tr('未启用'), "loading":tr('正在载入模型与打开音频设备…'),
                    "stopping":tr('正在释放音频设备…'), "error":tr('错误：')+str(snap["error"])}.get(state)
            if key in self.pending_routes:
                text = tr('正在应用新设置，完成后自动恢复…')
            elif key in self.route_errors:
                text = tr('无法恢复音频：')+self.route_errors[key]
            if state == "running":
                active.append(tr('麦克风') if key == "mic" else tr('扬声器'))
                total_ms += snap["process_ms"]
                text = tr('运行中 · {value0} 声道 · 模型延迟 {value1:.0f} ms + 缓冲', value0=snap['channels'], value1=snap['latency_ms'])
                if self.config["show_performance"]:
                    text += tr('\n处理 {value0:.1f} ms / 10 ms · 丢帧 {value1} · 欠载 {value2}', value0=snap['process_ms'], value1=snap['input_drop'] + snap['output_drop'], value2=snap['output_underrun'])
            ui["state"].configure(text=text or state)
            ui["record"].configure(icon="stop" if snap["recording"] else "record",
                                    state="normal" if state == "running" else "disabled")
            ui["record_time"].configure(text=f"00:{int(snap['recorded_seconds']):02d} / 00:20")
            ready = snap["recording_ready"] and not snap["recording"]
            for item in ("play0", "play1", "save"):
                ui[item].configure(state="normal" if ready else "disabled")
            if ready and self._shown_recordings.get(key) != snap["recorded_seconds"]:
                data = route.get_recording()
                if data is not None:
                    for i in (0, 1):
                        ui[f"wave{i}"].set_audio(data[i])
                    self._shown_recordings[key] = snap["recorded_seconds"]
            if snap.get("recording_error"):
                ui["preview_status"].configure(text=snap["recording_error"])
        self.ui["speaker"]["sample"].configure(state="disabled" if self.sample_job else "normal")
        if self.player.error and self._playback_error != self.player.error:
            self._playback_error = self.player.error
            self.status.set(tr('试听失败：')+self.player.error)
        elif not self.player.error:
            if self.player.active:
                self.status.set(tr('试听 {value0:.1f} / {value1:.1f} 秒 · Esc 停止', value0=self.player.position / RATE, value1=self.player.total / RATE))
            elif active:
                self.status.set(" + ".join(active)+tr('运行中')+(tr(' · 每 10 ms 处理耗时 {total_ms:.1f} ms', total_ms=total_ms) if self.config["show_performance"] else ""))
            else:
                self.status.set(tr('就绪 · 仅音频 · 视频功能尚未实现'))
        file_busy = bool(self.file_thread and self.file_thread.is_alive()) or self.file_restart
        self.file_start.configure(state="disabled" if file_busy or self.closing else "normal")
        self.file_stop.configure(state="normal" if file_busy else "disabled")
        e = self.effects("mic")
        self.file_effect_label.configure(text=tr('当前效果：噪音消除 {value0} ({value1:.0%})  ·  房间回声消除 {value2} ({value3:.0%})', value0=tr('开启') if e.noise else tr('关闭'), value1=e.noise_strength, value2=tr('开启') if e.dereverb else tr('关闭'), value3=e.dereverb_strength))
        if self.closing:
            busy = file_busy or self.player.busy or self.sample_job or any(
                r.busy for r in self.routes.values())
            if not busy:
                self.closed = True
                self.root.destroy()
                return
            self.status.set(tr('正在停止音频并释放资源…'))
        elif self._settings_error:
            self.status.set(self._settings_error)
        self.root.after(100, self.tick)

    def on_close(self):
        if self.closing:
            return
        if sys.platform != "win32":
            self.request_exit()
            return
        self.save_config()
        if self.tray_ready:
            self.root.withdraw()
            return
        if self.tray_hide_pending:
            return
        self.tray_hide_pending = True
        self.ensure_tray()

    def ensure_tray(self):
        """Keep one icon for the whole session, including while the GUI is visible."""
        if sys.platform != "win32" or self.closing or self.tray is not None:
            return
        try:
            self.tray = TrayIcon(self.events)
            self.tray.start()
        except Exception as exc:
            self.events.put(("tray_error", str(exc)))

    def restore_window(self):
        if self.closing:
            return
        self.tray_hide_pending = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def request_exit(self):
        if self.closing:
            return
        self.closing = True
        self.pending_routes.clear()
        self.refresh_pending = False
        self.tray_hide_pending = False
        if self.tray:
            self.tray.stop()
        if self.save_timer:
            self.root.after_cancel(self.save_timer)
        if self.layout_timer:
            self.root.after_cancel(self.layout_timer)
        self.save_config()
        self.cancel_file()
        self.stop_preview()
        for route in self.routes.values():
            route.stop()


def main():
    with SingleInstance() as instance:
        if not instance.acquire():
            return 0
        root = tk.Tk()
        if "--background" in sys.argv:
            root.withdraw()
        app = App(root)
        app.instance = instance
        if "--background" in sys.argv:
            root.after_idle(app.on_close)
        root.mainloop()
    return 0
