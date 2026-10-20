"""Actual cross-process Windows mutex/event tests, isolated from the app."""
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from openbroadcast.single_instance import SingleInstance


@unittest.skipUnless(sys.platform == "win32", "Windows single-instance implementation")
class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        self.name = "Local\\OpenBroadcast-test-" + uuid.uuid4().hex
        self.cwd = str(Path(__file__).resolve().parents[2])

    def secondary(self):
        return subprocess.run(
            [sys.executable, "-c",
             "import sys; from openbroadcast.single_instance import SingleInstance\n"
             "with SingleInstance(sys.argv[1]) as instance:\n"
             " print(instance.acquire(), flush=True)\n", self.name],
            cwd=self.cwd, capture_output=True, text=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )

    def test_duplicate_exits_and_queues_activation_before_gui_exists(self):
        with SingleInstance(self.name) as first:
            self.assertTrue(first.acquire())
            self.assertFalse(first.activation_requested())
            for _ in range(2):
                result = self.secondary()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "False")
                self.assertTrue(first.activation_requested())
                self.assertFalse(first.activation_requested())
        with SingleInstance(self.name) as replacement:
            self.assertTrue(replacement.acquire())

    def test_abandoned_mutex_can_be_acquired_after_process_crash(self):
        child = subprocess.Popen(
            [sys.executable, "-c",
             "import sys; from openbroadcast.single_instance import SingleInstance\n"
             "with SingleInstance(sys.argv[1]) as instance:\n"
             " print(instance.acquire(), flush=True)\n"
             " sys.stdin.read()\n", self.name],
            cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            self.assertEqual(child.stdout.readline().strip(), "True")
            # Keep a handle alive to exercise WAIT_ABANDONED, rather than merely
            # creating a fresh kernel object after the last handle disappears.
            with SingleInstance(self.name) as waiting:
                self.assertFalse(waiting.acquire())
                child.kill()
                child.communicate(timeout=10)
                with SingleInstance(self.name) as replacement:
                    self.assertTrue(replacement.acquire())
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=10)
