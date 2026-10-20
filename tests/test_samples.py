import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from openbroadcast.audio.samples import installed_samples, read_sample, MAX_SAMPLE_BYTES


class SampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.archive = self.base / "NVIDIA Corporation/NVIDIA Broadcast/resources/app.asar"
        self.archive.parent.mkdir(parents=True)
        env = patch.dict(os.environ, {"ProgramFiles": str(self.base)})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def wav(rate=48000):
        memory = io.BytesIO()
        sf.write(memory, np.column_stack((np.full(15, .25), np.full(15, -.5))),
                 rate, format="WAV", subtype="PCM_16")
        return memory.getvalue()

    def fixture(self, entries=None, payload=None, header=None):
        payload = self.wav() if payload is None else payload
        if header is None:
            entries = entries or {"keyboard.abcd.wav": {"offset": "0", "size": len(payload)}}
            header = {"files": {"build": {"files": {"static": {
                "files": {"media": {"files": entries}}}}}}}
        raw = json.dumps(header).encode()
        padding = (-len(raw)) % 4
        header_size = len(raw) + padding + 8
        self.archive.write_bytes(
            struct.pack("<4I", 4, header_size, header_size - 4, len(raw))
            + raw + b"\0" * padding + payload
        )
        return 8 + header_size

    def test_real_asar_layout_extracts_and_decodes_without_copying_assets(self):
        offset = self.fixture()
        refs = installed_samples()
        self.assertEqual(set(refs), {"keyboard"})
        self.assertEqual(refs["keyboard"], (self.archive, offset, len(self.wav())))
        audio = read_sample(refs["keyboard"])
        np.testing.assert_array_equal(audio, np.tile([.25, -.5], (15, 1)))
        self.assertEqual(list(self.archive.parent.iterdir()), [self.archive])

    def test_missing_or_malformed_archive_returns_no_samples(self):
        self.assertEqual(installed_samples(), {})
        for payload in (b"", b"bad archive", struct.pack("<4I", 4, 100, 96, 900)):
            self.archive.write_bytes(payload)
            self.assertEqual(installed_samples(), {})
        for header in ([], None, {"files": []}, {"files": {"build": None}}):
            self.fixture(header=header if header is not None else {"files": None})
            self.assertEqual(installed_samples(), {})

    def test_skips_unpacked_links_silent_and_invalid_entries(self):
        size = len(self.wav())
        entries = {
            "good.hash.wav": {"offset": "0", "size": size},
            "silent_audio.wav": {"offset": "0", "size": size},
            "external.wav": {"offset": "0", "size": size, "unpacked": True},
            "linked.wav": {"link": "good.hash.wav"},
            "before.wav": {"offset": "-1", "size": size},
            "past.wav": {"offset": "1", "size": size},
            "huge.wav": {"offset": "0", "size": MAX_SAMPLE_BYTES + 1},
            "negative.wav": {"offset": "0", "size": -1},
            "wrong.wav": {"offset": [], "size": size},
            "bad.wav": None,
            "text.txt": {"offset": "0", "size": size},
        }
        self.fixture(entries)
        self.assertEqual(set(installed_samples()), {"good"})

    def test_rejects_wrong_sample_rate(self):
        self.fixture(payload=self.wav(rate=44100))
        with self.assertRaisesRegex(ValueError, "44100"):
            read_sample(installed_samples()["keyboard"])

    def test_reference_bounds_and_archive_replacement(self):
        self.fixture()
        reference = installed_samples()["keyboard"]
        for offset, size in ((-1, 20), (0, -1), (0, 0), (0, MAX_SAMPLE_BYTES + 1),
                             ("0", 20), (0, True), (100000, 20)):
            with self.subTest(offset=offset, size=size):
                with self.assertRaises(ValueError):
                    read_sample((self.archive, offset, size))
        self.archive.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "已损坏|damaged"):
            read_sample(reference)


if __name__ == "__main__":
    unittest.main()
