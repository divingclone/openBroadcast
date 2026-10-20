import unittest
from unittest.mock import patch

from openbroadcast import launcher


class LauncherTests(unittest.TestCase):
    def test_gui_entry_point_passes_explicit_background_state(self):
        with patch("openbroadcast.gui.main", return_value=0) as gui:
            self.assertEqual(launcher.main([]), 0)
            gui.assert_called_once_with(background=False)
        with patch.object(launcher.sys, "platform", "win32"), \
             patch("openbroadcast.gui.main", return_value=0) as gui:
            self.assertEqual(launcher.main(["--background"]), 0)
            gui.assert_called_once_with(background=True)

    def test_background_is_supported_on_unix(self):
        for platform in ("darwin", "linux"):
            with patch.object(launcher.sys, "platform", platform), \
                 patch("openbroadcast.gui.main", return_value=0) as gui:
                launcher.main(["--background"])
            gui.assert_called_once_with(background=True)

    def test_runtime_check_propagates_failure(self):
        with patch("openbroadcast.runtime_check.run", return_value=1) as check:
            self.assertEqual(launcher.main(["--check-runtime", "report.json"]), 1)
            check.assert_called_once_with("report.json")
