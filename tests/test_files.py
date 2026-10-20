from concurrent.futures import CancelledError
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from openbroadcast.audio import files


class FakeDenoiser:
    """A truly delayed gain stage to exercise cascade flush/compensation."""
    instances = []

    def __init__(self, **kwargs):
        self.options = kwargs
        self.delay = np.zeros(files.LATENCY, dtype=np.float32)
        self.gain = 1 - kwargs["intensity"] * 0.5
        self.instances.append(self)

    def process(self, block):
        delayed = np.concatenate((self.delay, block * self.gain))
        result = delayed[:files.HOP]
        self.delay = delayed[files.HOP:]
        return result


class FileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.input = self.folder / "input.wav"
        self.output = self.folder / "output.wav"
        FakeDenoiser.instances = []

    def write_source(self, rate=48000, frames=5003):
        t = np.arange(frames, dtype=np.float32)
        data = np.column_stack((np.sin(t * 0.1) * 0.2, np.cos(t * 0.13) * 0.3))
        sf.write(self.input, data, rate, subtype="FLOAT")
        return data

    def test_bypass_has_no_models_and_preserves_channels_frames(self):
        data = self.write_source()
        progress = []
        with patch.object(files, "Denoiser", side_effect=AssertionError("constructed")):
            result = files.process_file(self.input, self.output, noise=False,
                                        progress=progress.append)
        clean, rate = sf.read(self.output, dtype="float32", always_2d=True)
        np.testing.assert_allclose(clean, data, atol=1 / 32768)
        self.assertEqual(rate, 48000)
        self.assertEqual(result["frames"], len(data))
        self.assertEqual(result["channels"], 2)
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], 1)
        self.assertEqual(progress, sorted(progress))

    def test_chain_separate_strengths_states_and_complete_tail(self):
        data = self.write_source(frames=4999)
        with patch.object(files, "Denoiser", FakeDenoiser):
            result = files.process_file(self.input, self.output, dereverb=True,
                                        noise_strength=0.2, dereverb_strength=0.6)
        clean, _ = sf.read(self.output, dtype="float32", always_2d=True)
        np.testing.assert_allclose(clean, data * 0.9 * 0.7, atol=1 / 32768)
        self.assertEqual(result["latency_samples"], files.LATENCY * 2)
        self.assertEqual(len(FakeDenoiser.instances), 4)
        self.assertEqual([x.options["model_file"] for x in FakeDenoiser.instances],
                         ["dereverb_48k.onnx"] * 2 + ["denoiser_48k.onnx"] * 2)
        self.assertEqual([x.options["intensity"] for x in FakeDenoiser.instances],
                         [0.6, 0.6, 0.2, 0.2])

    def test_linear_resampling_is_continuous_at_block_boundaries(self):
        for rate in (8000, 44100, 96000):
            with self.subTest(rate=rate):
                data = self.write_source(rate=rate, frames=9001)
                result = files.process_file(self.input, self.output, noise=False)
                clean, _ = sf.read(self.output, dtype="float32", always_2d=True)
                count = (len(data) * 48000 + rate // 2) // rate
                positions = np.arange(count) * rate / 48000
                expected = np.column_stack([
                    np.interp(positions, np.arange(len(data)), data[:, c])
                    for c in range(2)
                ])
                self.assertEqual(len(clean), count)
                self.assertEqual(result["resampling"], "linear")
                np.testing.assert_allclose(clean, expected, atol=1.01 / 32768)

    def test_cancel_preserves_existing_destination(self):
        self.write_source()
        self.output.write_bytes(b"previous destination")
        cancel = Event()

        def progress(value):
            if value > 0:
                cancel.set()

        with self.assertRaises(CancelledError):
            files.process_file(self.input, self.output, noise=False,
                               progress=progress, cancel=cancel)
        self.assertEqual(self.output.read_bytes(), b"previous destination")
        self.assertEqual(set(self.folder.iterdir()), {self.input, self.output})

    def test_progress_does_not_flood_gui_queue_during_fast_bypass(self):
        self.write_source(frames=480 * 1000)
        progress = []
        files.process_file(self.input, self.output, noise=False, progress=progress.append)
        self.assertLessEqual(len(progress), 202)
        self.assertEqual(progress[-1], 1)

    def test_source_cannot_be_overwritten(self):
        self.write_source()
        before = self.input.read_bytes()
        with self.assertRaisesRegex(ValueError, "different output path|不同的输出路径"):
            files.process_file(self.input, self.input, noise=False)
        self.assertEqual(self.input.read_bytes(), before)

    def test_failed_commit_preserves_previous_destination(self):
        self.write_source()
        self.output.write_bytes(b"previous destination")
        with patch.object(files.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                files.process_file(self.input, self.output, noise=False)
        self.assertEqual(self.output.read_bytes(), b"previous destination")
        self.assertEqual(set(self.folder.iterdir()), {self.input, self.output})

    def test_empty_wav_input(self):
        sf.write(self.input, np.empty((0, 2)), 48000)
        result = files.process_file(self.input, self.output, noise=False)
        info = sf.info(self.output)
        self.assertEqual((info.frames, info.channels, info.samplerate), (0, 2, 48000))
        self.assertEqual(result["frames"], 0)

    def test_empty_flac_output_rejected(self):
        sf.write(self.input, np.empty((0, 2)), 48000)
        with self.assertRaisesRegex(ValueError, "Empty audio|空音频"):
            files.process_file(self.input, self.folder / "output.flac", noise=False)

    def test_ogg_input_and_flac_output(self):
        self.write_source()
        data, rate = sf.read(self.input, always_2d=True)
        ogg = self.folder / "input.ogg"
        sf.write(ogg, data, rate, format="OGG", subtype="VORBIS")
        result = files.process_file(ogg, self.folder / "output.flac", noise=False)
        self.assertEqual(result["channels"], 2)
        self.assertEqual(result["frames"], len(data))

    def test_invalid_samples_do_not_replace_destination(self):
        sf.write(self.input, np.array([0, np.nan], dtype=np.float32), 48000, subtype="FLOAT")
        self.output.write_bytes(b"previous destination")
        with self.assertRaisesRegex(ValueError, "NaN"):
            files.process_file(self.input, self.output, noise=False)
        self.assertEqual(self.output.read_bytes(), b"previous destination")


if __name__ == "__main__":
    unittest.main()
