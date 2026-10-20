import queue
import sys
import time
import unittest
from unittest.mock import patch

from openbroadcast.tray_process import ProcessTray


class TrayProcessTests(unittest.TestCase):
    def start_helper(self, code, timeout=2):
        events = queue.Queue()
        tray = ProcessTray(events)
        tray.START_TIMEOUT = timeout
        with patch("openbroadcast.tray_process.helper_command",
                   return_value=[sys.executable, "-u", "-c", code]):
            tray.start()
            # Keep the command patch active until Popen has consumed it.
            event = events.get(timeout=6)
        self.addCleanup(tray.stop)
        return tray, events, event

    def test_ready_show_exit_and_parent_shutdown(self):
        tray, events, first = self.start_helper(
            "import json,sys\n"
            "for name in ['tray_ready','tray_show','tray_exit']:\n"
            " print(json.dumps([name,None]),flush=True)\n"
            "sys.stdin.read()\n")
        self.assertEqual(first, ("tray_ready", None))
        self.assertEqual(events.get(timeout=2), ("tray_show", None))
        self.assertEqual(events.get(timeout=2), ("tray_exit", None))
        tray.stop()
        tray.thread.join(timeout=5)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(events.empty())

    def test_crash_after_ready_restores_window_via_error(self):
        tray, events, first = self.start_helper(
            "import json\nprint(json.dumps(['tray_ready',None]),flush=True)\n")
        self.assertEqual(first[0], "tray_ready")
        self.assertEqual(events.get(timeout=3)[0], "tray_error")
        tray.thread.join(timeout=5)
        self.assertFalse(tray.thread.is_alive())

    def test_timeout_terminates_unresponsive_helper(self):
        tray, events, first = self.start_helper(
            "import time; time.sleep(30)", timeout=0.2)
        self.assertEqual(first[0], "tray_error")
        tray.thread.join(timeout=6)
        self.assertFalse(tray.thread.is_alive())
        self.assertTrue(events.empty())

    def test_stop_before_start_does_not_spawn_helper(self):
        tray = ProcessTray(queue.Queue())
        tray.stop()
        with patch("openbroadcast.tray_process.subprocess.Popen") as popen:
            tray.start()
            tray.thread.join(timeout=2)
            popen.assert_not_called()
