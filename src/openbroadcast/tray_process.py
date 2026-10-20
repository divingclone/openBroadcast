"""Supervise a Unix tray helper without running a second toolkit inside Tk."""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from .i18n import tr


def helper_command():
    return [sys.executable, "-u", str(Path(__file__).with_name("tray_worker.py")),
            tr('OpenBroadcast · 音频处理'), tr('打开 OpenBroadcast'), tr('退出 OpenBroadcast'),
            tr('桌面托盘不可用。请启用 StatusNotifier / AppIndicator 或 XEmbed 托盘；GNOME 可能需要托盘扩展。')]


class ProcessTray:
    START_TIMEOUT = 15

    def __init__(self, events):
        self.events = events
        self.stopping = threading.Event()
        self.thread = None

    def start(self):
        if self.thread is not None:
            raise RuntimeError("Tray already started")
        self.thread = threading.Thread(target=self._run, name="OpenBroadcast-tray", daemon=True)
        self.thread.start()

    def stop(self):
        self.stopping.set()

    def _run(self):
        process = None
        messages = queue.Queue()
        try:
            if self.stopping.is_set():
                return
            # stderr may contain toolkit diagnostics. The helper reports failures
            # through stdout; an abort/exit without a report is handled below.
            process = subprocess.Popen(
                helper_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )

            def read_events():
                try:
                    while True:
                        line = process.stdout.readline(8192)
                        if not line:
                            break
                        try:
                            message = json.loads(line)
                            if (isinstance(message, list) and len(message) == 2
                                    and message[0] in ("tray_ready", "tray_show", "tray_exit", "tray_error")
                                    and (message[1] is None or isinstance(message[1], str))):
                                messages.put(tuple(message))
                        except (ValueError, TypeError):
                            pass
                finally:
                    messages.put(("helper_eof", None))

            reader = threading.Thread(target=read_events, name="tray-events", daemon=True)
            reader.start()
            deadline = time.monotonic() + self.START_TIMEOUT
            ready = False
            while not self.stopping.is_set():
                try:
                    kind, payload = messages.get(timeout=0.1)
                except queue.Empty:
                    if not ready and time.monotonic() >= deadline:
                        raise RuntimeError(tr('托盘启动超时，请检查桌面托盘支持和系统库。'))
                    continue
                if self.stopping.is_set():
                    break
                if kind == "helper_eof":
                    raise RuntimeError(tr('托盘进程已退出，请检查桌面托盘支持和系统库。'))
                if kind == "tray_ready":
                    ready = True
                self.events.put((kind, payload))
                if kind == "tray_error":
                    break
        except Exception as exc:
            if not self.stopping.is_set():
                self.events.put(("tray_error", str(exc)))
        finally:
            if process is not None:
                # EOF also shuts the helper down if the GUI crashes or is killed.
                process.stdin.close()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                process.stdout.close()
