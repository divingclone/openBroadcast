"""Startup registration is tested against an isolated registry double."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from openbroadcast import startup


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.registry = MagicMock()
        self.registry.REG_SZ = 1
        self.registry.KEY_SET_VALUE = 2
        self.patch = patch.dict("sys.modules", winreg=self.registry)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.platform = patch.object(startup.sys, "platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)

    def test_enable_uses_current_user_and_disable_removes_only_our_value(self):
        with patch.object(startup, "startup_command", return_value='"C:\\App Space\\OpenBroadcast.exe" --background'):
            startup.set_enabled(True)
        self.registry.CreateKeyEx.assert_called_once_with(
            self.registry.HKEY_CURRENT_USER, startup.RUN_KEY, access=2)
        key = self.registry.CreateKeyEx.return_value.__enter__.return_value
        self.registry.SetValueEx.assert_called_once_with(
            key, "OpenBroadcast", 0, 1, '"C:\\App Space\\OpenBroadcast.exe" --background')
        startup.set_enabled(False)
        self.registry.DeleteValue.assert_called_once_with(
            self.registry.OpenKey.return_value.__enter__.return_value, "OpenBroadcast")

    def test_missing_entry_is_disabled_and_can_be_removed_again(self):
        self.registry.OpenKey.side_effect = FileNotFoundError()
        self.assertFalse(startup.is_enabled())
        startup.set_enabled(False)

    def test_permission_errors_are_not_reported_as_success(self):
        self.registry.OpenKey.side_effect = PermissionError("denied")
        with self.assertRaises(PermissionError):
            startup.set_enabled(False)

    def test_frozen_path_with_spaces_is_quoted_and_runs_in_background(self):
        path = str(Path("Portable App/OpenBroadcast.exe").resolve())
        with patch.object(startup.sys, "executable", path), patch.object(startup.sys, "frozen", True, create=True):
            self.assertEqual(startup.startup_command(), f'"{path}" --background')

    def test_source_uses_absolute_pythonw_and_launcher_paths(self):
        with tempfile.TemporaryDirectory(prefix="startup test ") as temp:
            python = Path(temp) / "python.exe"
            pythonw = Path(temp) / "pythonw.exe"
            pythonw.touch()
            with patch.object(startup.sys, "executable", str(python)), patch.object(startup.sys, "frozen", False, create=True):
                command = startup.startup_command()
            self.assertTrue(command.startswith(f'"{pythonw.resolve()}" '))
            self.assertIn(str(Path(startup.__file__).resolve().with_name("run_gui.pyw")), command)
            self.assertTrue(command.endswith(" --background"))
