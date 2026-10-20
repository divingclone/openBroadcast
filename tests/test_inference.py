import unittest
import sys
from unittest.mock import patch
from dataclasses import replace

from openbroadcast.audio.inference import (
    CPU, DML, CUDA, COREML, GpuDevice, discover_gpus, inference_options, selected_gpu,
    preferred_gpu, apply_inference_default,
)
from openbroadcast.settings import validate_settings
from openbroadcast.audio.denoiser import Denoiser
from pathlib import Path
from unittest.mock import Mock


GPU = GpuDevice("NVIDIA GeForce RTX 5090", DML, 3, "dxgi:stable")


class InferenceTests(unittest.TestCase):
    def test_mac_default_selects_coreml_only_when_available(self):
        with patch("openbroadcast.audio.inference.sys.platform", "darwin"), \
             patch("openbroadcast.audio.inference._dxgi_devices", return_value=[]), \
             patch("openbroadcast.audio.inference.ort.get_available_providers",
                   return_value=[CPU, COREML]):
            devices = discover_gpus()
            self.assertEqual(len(devices), 1)
            self.assertEqual(devices[0].provider, COREML)
            self.assertIn("CoreML", devices[0].label)
            self.assertEqual(inference_options(validate_settings(None), devices),
                             dict(provider=COREML, device_id=0, threads=2))
            legacy = validate_settings(dict(provider="coreml"))
            self.assertEqual(selected_gpu(legacy, devices), devices[0])
        with patch("openbroadcast.audio.inference.sys.platform", "darwin"), \
             patch("openbroadcast.audio.inference._dxgi_devices", return_value=[]), \
             patch("openbroadcast.audio.inference.ort.get_available_providers", return_value=[CPU]):
            self.assertEqual(inference_options(validate_settings(None))["provider"], CPU)

    def test_coreml_passes_gpu_policy_without_a_fictitious_device_id(self):
        processor = object.__new__(Denoiser)
        processor.model_path = Path("test.onnx")
        session = Mock()
        session.get_providers.return_value = [COREML, CPU]
        with patch("openbroadcast.audio.denoiser.ort.get_available_providers",
                   return_value=[COREML, CPU]), \
             patch("openbroadcast.audio.denoiser.ort.InferenceSession", return_value=session) as factory:
            processor._create_session("coreml", 0, 2, None)
        self.assertEqual(factory.call_args.kwargs["providers"],
                         [(COREML, {"MLComputeUnits": "CPUAndGPU"}), CPU])
        with self.assertRaisesRegex(ValueError, "system-managed"):
            processor._provider_options(COREML, 1)

    @unittest.skipUnless(sys.platform == "darwin", "Requires native macOS CoreML")
    def test_native_coreml_models_produce_finite_audio(self):
        import numpy as np
        import onnxruntime as ort
        if COREML not in ort.get_available_providers():
            self.skipTest("This ONNX Runtime build has no CoreML provider")
        signal = (0.03 * np.sin(np.arange(4800) * 2 * np.pi * 437 / 48000)).astype(np.float32)
        for model in ("denoiser_48k.onnx", "dereverb_48k.onnx"):
            with self.subTest(model=model):
                engine = Denoiser(model_file=model, provider="coreml")
                self.assertIn(COREML, engine.session.get_providers())
                output = engine.process_audio(signal)
                self.assertEqual(output.shape, signal.shape)
                self.assertTrue(np.isfinite(output).all())

    def test_fresh_install_prefers_high_performance_gpu_and_keeps_native_index(self):
        integrated = GpuDevice("Integrated", DML, 0, "igpu", performance_rank=1)
        discrete = replace(GPU, performance_rank=0)
        config = validate_settings(None)
        apply_inference_default(config, [integrated, discrete])
        self.assertEqual(config["inference_mode"], "gpu")
        self.assertEqual(config["gpu"], discrete.key)
        self.assertEqual(inference_options(config, [integrated, discrete]),
                         dict(provider=DML, device_id=3, threads=2))

    def test_auto_ignores_unsupported_gpus_and_falls_back_to_cpu(self):
        unavailable = replace(GPU, available=False, performance_rank=0)
        for devices in ([], [unavailable]):
            config = validate_settings(None)
            self.assertEqual(inference_options(config, devices),
                             dict(provider=CPU, device_id=0, threads=2))
            self.assertEqual(config["inference_mode"], "auto")
        supported = GpuDevice("Integrated", DML, 1, "igpu", performance_rank=1)
        self.assertEqual(preferred_gpu([unavailable, supported]), supported)

    def test_cuda_uses_compute_capacity_before_memory_or_ordinal(self):
        large = GpuDevice("Large older GPU", CUDA, 0, "large",
                          memory_bytes=48 << 30, compute_score=50)
        fast = GpuDevice("Fast GPU", CUDA, 2, "fast",
                         memory_bytes=24 << 30, compute_score=100)
        self.assertEqual(preferred_gpu([large, fast]), fast)
        self.assertEqual(preferred_gpu([replace(large, compute_score=0),
                                        replace(fast, compute_score=0)]).identity, "large")

    def test_dxgi_without_preference_api_uses_dedicated_memory(self):
        integrated = GpuDevice("Integrated", DML, 0, "igpu", memory_bytes=512 << 20)
        discrete = replace(GPU, memory_bytes=24 << 30)
        self.assertEqual(preferred_gpu([integrated, discrete]), discrete)

    def test_defaults_never_replace_saved_cpu_gpu_or_missing_gpu(self):
        for values in (dict(inference_mode="cpu"), dict(provider="cpu"),
                       dict(inference_mode="gpu", gpu=GPU.key),
                       dict(provider="dml", device_id=3)):
            config = validate_settings(values)
            before = config.copy()
            apply_inference_default(config, [replace(GPU, identity="new-faster")])
            self.assertEqual(config, before)

    def test_gpu_initialization_cannot_fall_back_to_cpu_silently(self):
        processor = object.__new__(Denoiser)
        processor.model_path = Path("test.onnx")
        session = Mock()
        session.get_providers.return_value = [CPU]
        with patch("openbroadcast.audio.denoiser.ort.get_available_providers", return_value=[CPU, DML]), \
             patch("openbroadcast.audio.denoiser.ort.InferenceSession", return_value=session):
            with self.assertRaisesRegex(RuntimeError, "初始化失败|failed to initialize"):
                processor._create_session(DML, 0, 2, None)

    def test_cpu_ignores_saved_gpu_and_legacy_index(self):
        config = validate_settings(dict(inference_mode="cpu", provider=DML, device_id=3,
                                        gpu=GPU.key, threads=5))
        self.assertEqual(inference_options(config, []),
                         dict(provider=CPU, threads=5, device_id=0))

    def test_gpu_uses_identity_after_reordering(self):
        config = validate_settings(dict(inference_mode="gpu", gpu=GPU.key, device_id=0))
        self.assertEqual(inference_options(config, [GPU])["device_id"], 3)
        self.assertEqual(inference_options(config, [GPU])["provider"], DML)

    def test_missing_and_unsupported_gpu_never_silently_use_cpu(self):
        config = validate_settings(dict(inference_mode="gpu", gpu=GPU.key))
        for devices in ([], [GpuDevice(GPU.name, DML, 3, GPU.identity, False)]):
            with self.assertRaises(ValueError):
                inference_options(config, devices)

    def test_duplicate_names_do_not_select_wrong_gpu(self):
        other = GpuDevice(GPU.name, DML, 0, "dxgi:another")
        config = validate_settings(dict(inference_mode="gpu", gpu=GPU.key))
        self.assertEqual(selected_gpu(config, [other, GPU]), GPU)

    def test_legacy_gpu_migrates_and_azure_is_cpu(self):
        config = validate_settings(dict(provider="dml", device_id=3))
        self.assertEqual(config["inference_mode"], "gpu")
        self.assertEqual(selected_gpu(config, [GPU]), GPU)
        self.assertEqual(validate_settings(dict(provider="AzureExecutionProvider"))["inference_mode"], "cpu")

    def test_discovery_preserves_native_ordinals_and_provider_support(self):
        ranked = replace(GPU, memory_bytes=32 << 30, performance_rank=0)
        with patch("openbroadcast.audio.inference.ort.get_available_providers", return_value=[CPU]), \
             patch("openbroadcast.audio.inference._dxgi_devices", return_value=[ranked]), \
             patch("openbroadcast.audio.inference._cuda_devices") as cuda:
            devices = discover_gpus()
        cuda.assert_not_called()
        self.assertEqual(devices[0].device_id, 3)
        self.assertFalse(devices[0].available)
        self.assertEqual(devices[0].memory_bytes, 32 << 30)
        self.assertEqual(devices[0].performance_rank, 0)

    def test_broken_driver_discovery_is_safe(self):
        with patch("openbroadcast.audio.inference.ort.get_available_providers", return_value=[CPU, CUDA]), \
             patch("openbroadcast.audio.inference._dxgi_devices", side_effect=OSError), \
             patch("openbroadcast.audio.inference._cuda_devices", side_effect=OSError):
            self.assertEqual(discover_gpus(), [])
