import unittest
from unittest.mock import patch

from openbroadcast.cli import build_parser, cmd_benchmark, cmd_mic, main, _inference_options, _make_engine
from openbroadcast.audio.inference import GpuDevice, DML, CPU
from openbroadcast.audio.runtime import AudioRoute


class CliTests(unittest.TestCase):
    def test_cli_defaults_use_preferred_gpu_for_both_model_stages(self):
        devices = [GpuDevice("Integrated", DML, 0, "igpu", performance_rank=1),
                   GpuDevice("Discrete", DML, 3, "dgpu", performance_rank=0)]
        args = build_parser().parse_args(["denoise", "a.wav", "b.wav", "--dereverb"])
        with patch("openbroadcast.audio.inference.discover_gpus", return_value=devices), \
             patch("openbroadcast.cli.Denoiser") as engine:
            _make_engine(args, dereverb=True)
        self.assertEqual(engine.call_count, 2)
        for call in engine.call_args_list:
            self.assertEqual(call.kwargs["provider"], DML)
            self.assertEqual(call.kwargs["device_id"], 3)

    def test_cli_auto_cpu_fallback_and_explicit_override(self):
        with patch("openbroadcast.audio.inference.discover_gpus", return_value=[]) as discover:
            options = _inference_options(build_parser().parse_args(["benchmark"]))
            self.assertEqual(options["provider"], CPU)
            self.assertEqual(options["device_id"], 0)
            discover.reset_mock()
            for provider, index in (("cpu", 0), ("cuda", 2)):
                args = build_parser().parse_args([
                    "benchmark", "--provider", provider, "--device-id", str(index)])
                self.assertEqual(_inference_options(args),
                                 dict(provider=provider, device_id=index, threads=2))
            discover.assert_not_called()

    def test_cli_auto_cannot_silently_ignore_explicit_device_id(self):
        with patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                main(["benchmark", "--device-id", "2"])

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

    def test_mic_uses_independent_stream_route_and_stops_on_interrupt(self):
        args = build_parser().parse_args([
            "mic", "--input-device", "2", "--output-device", "4",
            "--dereverb", "--intensity", "0.3",
        ])
        with patch("openbroadcast.audio.runtime.AudioRoute") as factory, \
             patch("openbroadcast.cli.time.sleep", side_effect=KeyboardInterrupt), \
             patch("builtins.print"):
            route = factory.return_value
            route.snapshot.return_value = dict(AudioRoute._initial_stats(), state="running")
            self.assertEqual(cmd_mic(args), 0)
            route.start.assert_called_once()
            self.assertEqual(route.start.call_args.args, (2, 4))
            effects = route.start.call_args.kwargs["effects"]
            self.assertTrue(effects.dereverb)
            self.assertEqual(effects.noise_strength, 0.3)
            route.stop.assert_called_once_with(wait=True)

    def test_mic_reports_worker_failure_and_releases_route(self):
        args = build_parser().parse_args(["mic", "--input-device", "2", "--output-device", "4"])
        with patch("openbroadcast.audio.runtime.AudioRoute") as factory, patch("builtins.print"):
            route = factory.return_value
            route.snapshot.return_value = dict(AudioRoute._initial_stats(), state="error",
                                               error="device disconnected")
            with self.assertRaisesRegex(RuntimeError, "device disconnected"):
                cmd_mic(args)
            route.stop.assert_called_once_with(wait=True)
