import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from openbroadcast.settings import DEFAULT_SETTINGS, SettingsStore


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nested" / "settings.json"
        self.store = SettingsStore(self.path)

    def test_missing_malformed_and_independent_defaults(self):
        first = self.store.load()
        first["mic"]["noise"] = False
        self.assertTrue(self.store.load()["mic"]["noise"])
        self.path.parent.mkdir()
        for content in ("invalid", "[]", "null", '{"mic": null}', '\ufeffbad'):
            self.path.write_text(content, encoding="utf-8")
            self.assertEqual(self.store.load(), DEFAULT_SETTINGS)

    def test_round_trip_and_device_identity(self):
        values = copy.deepcopy(DEFAULT_SETTINGS)
        values["mic"].update(enabled=True, noise=False, dereverb=True, noise_strength=0.2,
                             input={"name": "麦克风", "hostapi": "Windows WASAPI"})
        values.update(threads=4, device_id=2, theme="light", show_performance=False, expanded=True)
        self.store.save(values)
        self.assertEqual(self.store.load(), values)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), values)

    def test_invalid_types_ranges_and_unknown_keys(self):
        self.store.save({
            "threads": True, "device_id": -1, "provider": [], "theme": "blue",
            "show_performance": "no", "expanded": "true", "unknown": 10,
            "mic": {"enabled": "true", "noise": 0, "dereverb": "true", "noise_strength": float("nan"),
                    "dereverb_strength": 1.1,
                    "input": {"name": "Test", "hostapi": 0},
                    "output": {"name": "", "hostapi": "API"}},
        })
        self.assertEqual(self.store.load(), DEFAULT_SETTINGS)

    def test_save_failure_preserves_previous_file_and_cleans_temporary(self):
        self.store.save(DEFAULT_SETTINGS)
        previous = self.path.read_bytes()
        with patch("openbroadcast.settings.os.replace", side_effect=PermissionError("locked")):
            with self.assertRaisesRegex(OSError, "Could not save OpenBroadcast settings"):
                self.store.save({"threads": 8})
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


if __name__ == "__main__":
    unittest.main()
