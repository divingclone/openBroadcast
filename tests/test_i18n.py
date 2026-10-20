"""OS detection, catalog coverage, formatting and tray language behavior."""
import ast
from pathlib import Path
import string
import sys
import unittest
from unittest.mock import Mock, patch

from openbroadcast import i18n
from openbroadcast.tray import TrayIcon


class LanguageTests(unittest.TestCase):
    def test_windows_display_language_takes_priority_over_region(self):
        with patch.object(i18n.sys, "platform", "win32"), \
             patch.dict(i18n.os.environ, {"LANG": "en_US.UTF-8"}, clear=True):
            for language, expected in (("zh_CN", "zh-CN"), ("zh_TW", "zh-CN"),
                                       ("zh-HK", "zh-CN"), ("en_US", "en"),
                                       ("ja_JP", "en")):
                with self.subTest(language=language), \
                     patch.object(i18n, "_windows_ui_language", return_value=language):
                    self.assertEqual(i18n.detect_language(), expected)

    def test_windows_api_returns_user_ui_language(self):
        api = Mock()
        api.kernel32.GetUserDefaultUILanguage.return_value = 0x0804
        with patch.object(i18n.ctypes, "windll", api, create=True):
            self.assertEqual(i18n._windows_ui_language(), "zh_CN")
        with patch.object(i18n.ctypes, "windll", None, create=True):
            self.assertIsNone(i18n._windows_ui_language())

    def test_locale_environment_precedence_and_fallback(self):
        cases = [
            ({"LC_ALL": "en_US", "LC_MESSAGES": "zh_CN", "LANG": "zh_CN"}, "en"),
            ({"LC_MESSAGES": "zh_TW.UTF-8", "LANG": "en_US"}, "zh-CN"),
            ({"LANG": "zh.UTF-8"}, "zh-CN"),
            ({"LANG": "de_DE.UTF-8"}, "en"),
            ({"LANG": "C"}, "en"),
            ({"LANG": "nonsense"}, "en"),
            ({}, "zh-CN"),
        ]
        for env, expected in cases:
            with self.subTest(env=env), patch.object(i18n.sys, "platform", "linux"), \
                 patch.dict(i18n.os.environ, env, clear=True), \
                 patch.object(i18n.locale, "getlocale", return_value=("zh_CN", "UTF-8")):
                self.assertEqual(i18n.detect_language(), expected)
        with patch.object(i18n.sys, "platform", "darwin"), \
             patch.dict(i18n.os.environ, {}, clear=True), \
             patch.object(i18n.locale, "getlocale", side_effect=ValueError):
            self.assertEqual(i18n.detect_language(), "en")

    def test_language_remains_consistent_for_process_lifetime(self):
        i18n.get_language.cache_clear()
        self.addCleanup(i18n.get_language.cache_clear)
        with patch.object(i18n, "detect_language", side_effect=["en", "zh-CN"]) as detect:
            self.assertEqual(i18n.get_language(), "en")
            self.assertEqual(i18n.get_language(), "en")
            detect.assert_called_once()

    def test_templates_preserve_placeholders_and_formatting(self):
        formatter = string.Formatter()
        for catalog in (i18n.ENGLISH, i18n.CHINESE):
            for source, translation in catalog.items():
                with self.subTest(source=source):
                    fields = lambda text: sorted((name, spec, conv) for _, name, spec, conv
                                                 in formatter.parse(text) if name is not None)
                    self.assertEqual(fields(source), fields(translation))
        with patch.object(i18n, "get_language", return_value="en"):
            self.assertEqual(i18n.tr("正在处理… {value0:.0%}", value0=.25), "Processing… 25%")
            self.assertEqual(i18n.tr("是否替换已有文件？\n{dst}", dst="录音{1}.wav"),
                             "Replace the existing file?\n录音{1}.wav")
            self.assertEqual(i18n.tr("unrecognized diagnostic"), "unrecognized diagnostic")

    def test_all_translation_calls_have_catalog_entries(self):
        root = Path(i18n.__file__).parent
        files = list(root.glob("*.py")) + list(root.glob("*.pyw")) + list((root / "audio").glob("*.py"))
        for path in files:
            if path.name == "i18n.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
                    self.assertIsInstance(node.args[0], ast.Constant)
                    key = node.args[0].value
                    self.assertIn(key, i18n.ENGLISH | i18n.CHINESE, f"{path}:{node.lineno}")
                    required = {name for _, name, _, _ in string.Formatter().parse(key) if name}
                    self.assertEqual(required, {kw.arg for kw in node.keywords}, key)

    @unittest.skipUnless(sys.platform == "win32", "Native tray dependencies are Windows-only")
    def test_tray_and_user_guide_follow_selected_language(self):
        import pystray
        root = Path(i18n.__file__).parent
        for language, open_label, exit_label, guide in (
                ("en", "Open OpenBroadcast", "Exit OpenBroadcast", "README.md"),
                ("zh-CN", "打开 OpenBroadcast", "退出 OpenBroadcast", "README.zh-CN.md")):
            with self.subTest(language=language), \
                 patch.object(i18n, "get_language", return_value=language), \
                 patch.object(pystray, "Icon") as icon:
                events = Mock()
                tray = TrayIcon(events)
                menu = list(icon.call_args.kwargs["menu"])
                self.assertEqual(menu[0].text, open_label)
                self.assertEqual(menu[-1].text, exit_label)
                tray._show()
                events.put.assert_called_with(("tray_show", None))
                self.assertEqual(i18n.readme_filename(), guide)
                self.assertTrue((root / guide).is_file())
