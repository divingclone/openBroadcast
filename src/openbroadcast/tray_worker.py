"""Standalone Qt tray helper. Main-thread GUI loop, no audio or Tk imports."""
import json
import os
import sys
import threading
import time


def emit(kind, payload=None):
    print(json.dumps([kind, payload], ensure_ascii=True), flush=True)


def run(title, show_label, exit_label, unavailable_message):
    if sys.platform == "darwin":
        # This process owns only a menu-bar item, not a second Dock application.
        os.environ["QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM"] = "1"
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

    app = QApplication(["OpenBroadcast tray"])
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("OpenBroadcast")
    app.setDesktopFileName("openbroadcast")
    tray = QSystemTrayIcon()
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    for x, height in ((5, 8), (10, 18), (15, 26), (20, 14), (25, 8)):
        painter.fillRect(x, 16 - height // 2, 3, height, QColor("#76b900"))
    painter.end()
    tray.setIcon(QIcon(pixmap))
    tray.setToolTip(title)
    menu = QMenu()
    menu.addAction(show_label, lambda: emit("tray_show"))
    menu.addSeparator()
    menu.addAction(exit_label, lambda: emit("tray_exit"))
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: emit("tray_show") if reason in (
        QSystemTrayIcon.ActivationReason.Trigger,
        QSystemTrayIcon.ActivationReason.DoubleClick,
    ) else None)

    stopping = threading.Event()

    def watch_parent():
        # No toolkit calls from this thread, including on parent process death.
        try:
            sys.stdin.read()
        finally:
            stopping.set()

    threading.Thread(target=watch_parent, name="tray-parent", daemon=True).start()
    deadline = time.monotonic() + 10
    ready = False

    def tick():
        nonlocal ready
        if stopping.is_set():
            tray.hide()
            app.quit()
            return
        available = QSystemTrayIcon.isSystemTrayAvailable()
        if available and not ready:
            tray.show()
            ready = True
            emit("tray_ready")
        elif not available and (ready or time.monotonic() >= deadline):
            emit("tray_error", unavailable_message)
            tray.hide()
            app.quit()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(250)
    return app.exec()


if __name__ == "__main__":
    try:
        raise SystemExit(run(*sys.argv[1:]))
    except Exception as exc:
        emit("tray_error", str(exc))
        raise SystemExit(1)
