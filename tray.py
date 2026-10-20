"""Windows notification-area icon; all GUI actions travel through a queue."""
from __future__ import annotations

import threading


class TrayIcon:
    def __init__(self, events):
        # Keep non-Windows startup and source installs without tray dependencies usable.
        import pystray
        from PIL import Image, ImageDraw

        self.events = events
        self.ready = threading.Event()
        self.stopping = threading.Event()
        image = Image.new("RGBA", (32, 32), "#191919")
        draw = ImageDraw.Draw(image)
        for x, height in ((5, 8), (10, 18), (15, 26), (20, 14), (25, 8)):
            draw.rectangle((x, 16-height//2, x+2, 16+height//2), fill="#76b900")
        self.icon = pystray.Icon(
            "OpenBroadcast", image, "OpenBroadcast · 音频处理",
            menu=pystray.Menu(
                pystray.MenuItem("打开 OpenBroadcast", self._show, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出 OpenBroadcast", self._exit),
            ),
        )

    def _show(self, *_):
        self.events.put(("tray_show", None))

    def _exit(self, *_):
        self.events.put(("tray_exit", None))

    def start(self):
        threading.Thread(target=self._run, name="OpenBroadcast-tray", daemon=True).start()

    def _setup(self, icon):
        try:
            if not self.stopping.is_set():
                icon.visible = True
                self.events.put(("tray_ready", None))
        except Exception as exc:
            self.events.put(("tray_error", str(exc)))
        finally:
            self.ready.set()

    def _run(self):
        try:
            self.icon.run(setup=self._setup)
            if not self.stopping.is_set():
                self.events.put(("tray_error", "系统托盘已停止。"))
        except Exception as exc:
            if not self.stopping.is_set():
                self.events.put(("tray_error", str(exc)))
        finally:
            self.ready.set()

    def stop(self):
        if self.stopping.is_set():
            return
        self.stopping.set()

        def cleanup():
            # Never block Tk waiting for the tray's setup/message-loop thread.
            self.ready.wait()
            self.icon.stop()

        threading.Thread(target=cleanup, name="OpenBroadcast-tray-stop", daemon=True).start()
