"""Native POSIX lock races, activation-before-GUI and private-file checks."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from openbroadcast.posix_instance import PosixInstance


@unittest.skipIf(os.name == "nt", "Requires native POSIX flock/pread/pwrite")
class PosixTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def make(self, name="test"):
        instance = PosixInstance(name, self.folder)
        self.addCleanup(instance.close)
        return instance

    def test_activation_during_owner_startup_is_preserved_and_consumed_once(self):
        owner = self.make()
        self.assertTrue(owner.acquire())
        for _ in range(3):
            duplicate = self.make()
            self.assertFalse(duplicate.acquire())
            duplicate.close()
        self.assertTrue(owner.activation_requested())
        self.assertFalse(owner.activation_requested())
        owner.close()
        replacement = self.make()
        self.assertTrue(replacement.acquire())
        self.assertFalse(replacement.activation_requested())

    def test_simultaneous_launches_have_one_owner(self):
        code = (
            "import sys,time; from openbroadcast.posix_instance import PosixInstance\n"
            "gate=PosixInstance('race',sys.argv[1]); print(gate.acquire(),flush=True)\n"
            "sys.stdin.read(); gate.close()\n"
        )
        processes = [subprocess.Popen(
            [sys.executable, "-I", "-c", code, str(self.folder)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        ) for _ in range(6)]
        try:
            with concurrent.futures.ThreadPoolExecutor() as pool:
                futures = [pool.submit(p.stdout.readline) for p in processes]
                owners = [f.result(timeout=15).strip() for f in futures]
            self.assertEqual(owners.count("True"), 1, owners)
            self.assertEqual(owners.count("False"), 5, owners)
        finally:
            for process in processes:
                try:
                    process.communicate("", timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate()

    def test_shared_or_symlink_directory_is_rejected(self):
        self.folder.chmod(0o755)
        with self.assertRaises(OSError):
            self.make().acquire()
        self.folder.chmod(0o700)
        link = self.folder / "link"
        target = self.folder / "private"
        target.mkdir(mode=0o700)
        link.symlink_to(target, target_is_directory=True)
        instance = PosixInstance("test", link)
        with self.assertRaises(OSError):
            instance.acquire()

    def test_symlink_lock_does_not_touch_target(self):
        instance = self.make()
        victim = self.folder / "unrelated"
        victim.write_text("keep")
        instance.lock_path.symlink_to(victim)
        with self.assertRaises(OSError):
            instance.acquire()
        self.assertEqual(victim.read_text(), "keep")

    def test_linux_display_sessions_are_independent(self):
        with patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, {"DISPLAY": ":1", "WAYLAND_DISPLAY": ""}):
            first = self.make()
        with patch.object(sys, "platform", "linux"), \
             patch.dict(os.environ, {"DISPLAY": ":2", "WAYLAND_DISPLAY": ""}):
            second = self.make()
        self.assertNotEqual(first.lock_path, second.lock_path)
        self.assertTrue(first.acquire())
        self.assertTrue(second.acquire())
