import unittest
from unittest.mock import patch

from openbroadcast.cli import build_parser, cmd_benchmark, main


class CliTests(unittest.TestCase):
    def test_no_command_opens_gui(self):
        with patch("openbroadcast.gui.main", return_value=0) as launch:
            self.assertEqual(main([]), 0)
            launch.assert_called_once()

    def test_process_preserves_independent_effect_arguments(self):
        args = build_parser().parse_args([
            "process", "a.flac", "b.wav", "--no-noise", "--dereverb",
            "--dereverb-strength", "0.4", "--provider", "cpu",
        ])
        self.assertTrue(args.no_noise)
        self.assertTrue(args.dereverb)
        self.assertEqual(args.dereverb_strength, 0.4)

    def test_benchmark_rejects_invalid_durations(self):
        for value in ("0", "-1", "nan", "inf"):
            args = build_parser().parse_args(["benchmark", "--seconds", value])
            with self.assertRaises(SystemExit):
                cmd_benchmark(args)
