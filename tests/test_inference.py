import unittest
from unittest.mock import patch

from openbroadcast.audio.inference import (
    CPU, DML, CUDA, GpuDevice, discover_gpus, inference_options, selected_gpu,
)
from openbroadcast.settings import validate_settings
from openbroadcast.audio.denoiser import Denoiser
from pathlib import Path
from unittest.mock import Mock


GPU = GpuDevice("NVIDIA GeForce RTX 5090", DML, 3, "dxgi:stable")


class InferenceTests(unittest.TestCase):
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
        with patch("openbroadcast.audio.inference.ort.get_available_providers", return_value=[CPU]), \
             patch("openbroadcast.audio.inference._dxgi_devices", return_value=[GPU]), \
             patch("openbroadcast.audio.inference._cuda_devices") as cuda:
            devices = discover_gpus()
        cuda.assert_not_called()
        self.assertEqual(devices[0].device_id, 3)
        self.assertFalse(devices[0].available)

    def test_broken_driver_discovery_is_safe(self):
        with patch("openbroadcast.audio.inference.ort.get_available_providers", return_value=[CPU, CUDA]), \
             patch("openbroadcast.audio.inference._dxgi_devices", side_effect=OSError), \
             patch("openbroadcast.audio.inference._cuda_devices", side_effect=OSError):
            self.assertEqual(discover_gpus(), [])
