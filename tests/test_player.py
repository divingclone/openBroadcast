import sys
import threading
import unittest
from unittest.mock import Mock, patch

import numpy as np

from openbroadcast.audio.player import PreviewPlayer


class FakeSoundDevice:
    def __init__(self, maximum=2, accepted=(2,), gated=False, fail_write=False):
        self.maximum, self.accepted = maximum, accepted
        self.writes, self.streams, self.checked = [], [], []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.gated, self.fail_write = gated, fail_write
        self.stop, self.play = Mock(), Mock()

    def query_devices(self, device):
        return {"max_output_channels": self.maximum}

    def check_output_settings(self, **options):
        self.checked.append(options)
        if options["channels"] not in self.accepted:
            raise ValueError("unsupported channels")

    def OutputStream(self, **options):
        owner = self

        class Stream:
            closed = False

            def __enter__(self):
                return self

            def __exit__(self, *_):
                self.closed = True

            def write(self, block):
                owner.entered.set()
                if owner.gated and not owner.release.wait(2):
                    raise TimeoutError("test did not release stream")
                if owner.fail_write:
                    raise OSError("device disconnected")
                owner.writes.append(block.copy())
        stream = Stream()
        stream.options = options
        self.streams.append(stream)
        return stream


class PlayerTests(unittest.TestCase):
    def wait(self, player):
        player._thread.join(3)
        self.assertFalse(player.busy, "preview thread did not finish")
        self.assertFalse(player.active)

    def test_mono_is_duplicated_to_stereo_wasapi_and_clipped(self):
        sd = FakeSoundDevice()
        data = np.linspace(-2, 2, 1001, dtype=np.float32)
        player = PreviewPlayer()
        with patch.dict(sys.modules, sounddevice=sd):
            player.play(data, 7)
            self.wait(player)
        self.assertFalse(player.error)
        self.assertEqual(player.position, len(data))
        self.assertEqual(sd.streams[0].options["channels"], 2)
        output = np.concatenate(sd.writes)
        np.testing.assert_array_equal(output[:, 0], np.clip(data, -1, 1))
        np.testing.assert_array_equal(output[:, 0], output[:, 1])
        self.assertTrue(sd.streams[0].closed)
        sd.play.assert_not_called()

    def test_stereo_downmix_to_mono_device(self):
        sd = FakeSoundDevice(maximum=1, accepted=(1,))
        data = np.column_stack((np.ones(501), np.zeros(501))).astype(np.float32)
        player = PreviewPlayer()
        with patch.dict(sys.modules, sounddevice=sd):
            player.play(data, 2)
            self.wait(player)
        np.testing.assert_array_equal(np.concatenate(sd.writes), np.full((501, 1), .5))

    def test_native_channel_fallback(self):
        sd = FakeSoundDevice(maximum=6, accepted=(6,))
        player = PreviewPlayer()
        with patch.dict(sys.modules, sounddevice=sd):
            player.play(np.ones(20), 2)
            self.wait(player)
        self.assertEqual([x["channels"] for x in sd.checked], [2, 6])
        self.assertEqual(sd.writes[0].shape, (20, 6))

    def test_stop_only_owns_preview_stream_and_restart_works(self):
        sd = FakeSoundDevice(gated=True)
        player = PreviewPlayer()
        with patch.dict(sys.modules, sounddevice=sd):
            player.play(np.ones(4800), 1)
            self.assertTrue(sd.entered.wait(2))
            with self.assertRaises(RuntimeError):
                player.play(np.ones(480), 1)
            player.stop()
            sd.release.set()
            self.wait(player)
            self.assertLess(player.position, player.total)
            sd.stop.assert_not_called()
            self.assertTrue(sd.streams[0].closed)
            player.play(np.ones(20), 1)
            self.wait(player)
        self.assertEqual(player.position, 20)
        self.assertEqual(len(sd.streams), 2)

    def test_device_write_failure_is_reported_and_stream_closed(self):
        sd = FakeSoundDevice(fail_write=True)
        player = PreviewPlayer()
        with patch.dict(sys.modules, sounddevice=sd):
            player.play(np.ones(480), 1)
            self.wait(player)
        self.assertIn("device disconnected", player.error)
        self.assertTrue(sd.streams[0].closed)

    def test_no_compatible_output_does_not_open_stream(self):
        for sd in (FakeSoundDevice(maximum=0), FakeSoundDevice(accepted=())):
            player = PreviewPlayer()
            with patch.dict(sys.modules, sounddevice=sd):
                player.play(np.ones(480), 1)
                self.wait(player)
            self.assertTrue(player.error)
            self.assertFalse(sd.streams)

    def test_invalid_shapes_and_nonfinite_audio_are_rejected(self):
        for data in (np.array(1), [], np.empty((5, 0)), np.zeros((2, 2, 2)), [np.nan]):
            with self.subTest(shape=np.asarray(data).shape):
                with self.assertRaises(ValueError):
                    PreviewPlayer().play(data, 1)


if __name__ == "__main__":
    unittest.main()
