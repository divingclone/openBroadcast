"""Opt-in native Qt tray tests. Linux must use an isolated Xvfb display."""
import os
import queue
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

from openbroadcast.tray_process import ProcessTray, helper_command


@unittest.skipUnless(os.environ.get("OPENBROADCAST_TEST_NATIVE_TRAY") == "1"
                     and sys.platform in ("linux", "darwin"), "Opt-in native Unix desktop tests")
class NativeTrayTests(unittest.TestCase):
    def setUp(self):
        self.host = None
        if sys.platform == "linux":
            self.assertTrue(shutil.which("trayer"), "Install trayer in the isolated test desktop")
            self.host = subprocess.Popen(
                ["trayer", "--edge", "top", "--align", "right",
                 "--widthtype", "request", "--height", "24"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            self.addCleanup(self.stop_host)

    def stop_host(self):
        if self.host and self.host.poll() is None:
            self.host.terminate()
            self.host.wait(timeout=5)

    def test_real_helper_ready_and_clean_stop(self):
        events = queue.Queue()
        tray = ProcessTray(events)
        self.addCleanup(tray.stop)
        tray.start()
        self.assertEqual(events.get(timeout=20), ("tray_ready", None))
        tray.stop()
        tray.thread.join(timeout=6)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(events.empty())

    @unittest.skipUnless(sys.platform == "linux", "Controlled XEmbed host")
    def test_host_loss_is_reported_to_restore_the_window(self):
        events = queue.Queue()
        tray = ProcessTray(events)
        self.addCleanup(tray.stop)
        tray.start()
        self.assertEqual(events.get(timeout=20), ("tray_ready", None))
        self.stop_host()
        self.assertEqual(events.get(timeout=6)[0], "tray_error")
        tray.thread.join(timeout=6)
        self.assertFalse(tray.thread.is_alive())

    def test_helper_exits_when_parent_pipe_closes(self):
        process = subprocess.Popen(helper_command(), stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        messages = queue.Queue()
        threading.Thread(target=lambda: messages.put(process.stdout.readline()),
                         daemon=True).start()
        try:
            self.assertIn("tray_ready", messages.get(timeout=20))
            process.stdin.close()
            self.assertEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()
            process.stderr.close()

    def test_missing_tray_never_reports_ready(self):
        events = queue.Queue()
        tray = ProcessTray(events)
        self.addCleanup(tray.stop)
        # Offscreen supplies no native tray, independent of the user's desktop.
        with patch.dict(os.environ, {"QT_QPA_PLATFORM": "offscreen"}):
            tray.start()
            self.assertEqual(events.get(timeout=20)[0], "tray_error")
        tray.thread.join(timeout=6)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(events.empty())
