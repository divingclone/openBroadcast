import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import time
from unittest.mock import patch

from openbroadcast import startup


class UnixStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def test_macos_plist_roundtrip_and_disable_preserves_neighbors(self):
        path = self.folder / "LaunchAgents" / (startup.AGENT_LABEL + ".plist")
        args = ["/App Space/环境/bin/python3", "/App Space/run_gui.pyw", "--background"]
        with patch.object(startup.sys, "platform", "darwin"), \
             patch.object(startup, "startup_path", return_value=path), \
             patch.object(startup, "startup_args", return_value=args):
            self.assertFalse(startup.is_enabled())
            startup.set_enabled(True)
            config = plistlib.loads(path.read_bytes())
            self.assertEqual(config["ProgramArguments"], args)
            self.assertEqual(config["LimitLoadToSessionType"], "Aqua")
            self.assertNotIn("KeepAlive", config)
            self.assertTrue(startup.is_enabled())
            neighbor = path.with_name("other.plist")
            neighbor.write_text("untouched")
            startup.set_enabled(False)
            startup.set_enabled(False)
            self.assertFalse(startup.is_enabled())
            self.assertEqual(neighbor.read_text(), "untouched")

    def test_linux_roundtrip_hidden_flag_and_failed_replacement(self):
        path = self.folder / "autostart" / "openbroadcast.desktop"
        with patch.object(startup.sys, "platform", "linux"), \
             patch.object(startup, "startup_path", return_value=path), \
             patch.object(startup, "startup_args", return_value=["/venv/bin/python", "/app/run_gui.pyw", "--background"]):
            startup.set_enabled(True)
            self.assertTrue(startup.is_enabled())
            original = path.read_bytes()
            with patch.object(startup.os, "replace", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    startup.set_enabled(True)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
            path.write_bytes(original + b"Hidden=true\n")
            self.assertFalse(startup.is_enabled())
            startup.set_enabled(True)
            self.assertTrue(startup.is_enabled())
            startup.set_enabled(False)
            self.assertFalse(path.exists())

    def test_exec_escaping_roundtrips_two_spec_layers(self):
        # Decode Desktop Entry string escapes, then the quoted Exec arguments.
        args = ["/环境/a b/bin/python", '/app/a"$`\\%/run_gui.pyw', "--background"]
        encoded = startup._desktop_exec(args)
        value = encoded.replace("\\\\", "\\")
        decoded, buffer, quoted, escaped = [], "", False, False
        for c in value:
            if escaped:
                buffer += c
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                quoted = not quoted
            elif c == " " and not quoted:
                decoded.append(buffer.replace("%%", "%"))
                buffer = ""
            else:
                buffer += c
        decoded.append(buffer.replace("%%", "%"))
        self.assertEqual(decoded, args)
        for invalid in ("/app/a\nb", "/app/a\rb", "/app/a\0b"):
            with self.assertRaises(OSError):
                startup._desktop_exec([invalid])

    @unittest.skipUnless(startup.sys.platform == "linux" and shutil.which("gio"),
                         "Requires the Linux GIO desktop launcher")
    def test_exec_escaping_with_real_desktop_launcher(self):
        special = self.folder / 'space $`%\\"字'
        special.mkdir()
        script = special / "capture.py"
        output = self.folder / "captured.json"
        script.write_text("import json,sys; from pathlib import Path\n"
                          "Path(sys.argv[1]).write_text(json.dumps(sys.argv[2:]))\n")
        expected = ['spaces a b', 'quote"backslash\\dollar$backtick`percent%']
        entry = self.folder / "test.desktop"
        entry.write_text("[Desktop Entry]\nType=Application\nName=Test\nExec="
                         + startup._desktop_exec([startup.sys.executable, str(script),
                                                 str(output), *expected]) + "\n")
        result = subprocess.run(["gio", "launch", str(entry)], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 5
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(json.loads(output.read_text()), expected)

    def test_paths_use_user_locations_and_ignore_relative_xdg(self):
        with patch.object(startup.Path, "home", return_value=self.folder):
            with patch.object(startup.sys, "platform", "darwin"):
                self.assertEqual(startup.startup_path().parent, self.folder / "Library" / "LaunchAgents")
            with patch.object(startup.sys, "platform", "linux"), \
                 patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
                self.assertEqual(startup.startup_path().parent, self.folder / ".config" / "autostart")

    @unittest.skipIf(os.name == "nt", "Unix venv symlinks")
    def test_venv_interpreter_symlink_is_preserved(self):
        venv_python = self.folder / "python"
        venv_python.symlink_to(sys_executable := startup.sys.executable)
        with patch.object(startup.sys, "executable", str(venv_python)), \
             patch.object(startup.sys, "platform", "linux"):
            self.assertEqual(startup.startup_args()[0], str(venv_python))
            self.assertNotEqual(startup.startup_args()[0], sys_executable)
