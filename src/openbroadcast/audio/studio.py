"""Portable Studio Voice, using a raw 48 kHz waveform and streaming caches.

The model consumes 3840 samples. The application's 480-sample interface adds
3360 initial samples of buffering; whole-file processing removes this delay.
Weights and streaming operations are ported from Broadcast's
``nvbcast_afx_stdvoice_v0_9`` low-latency 48 kHz model. Inference uses standard
ONNX operators and does not load NVIDIA's SDK or TensorRT.
"""
from collections import deque
from pathlib import Path

import numpy as np

from .binding import FixedStateBinding
from .denoiser import create_session
from .native_dml import NativeDmlSession

RATE = 48_000
HOP = 480
INFERENCE_SAMPLES = 3_840
LATENCY = INFERENCE_SAMPLES - HOP


class StudioVoice:
    """One independent mono stream, exposing the application's 10 ms interface."""

    def __init__(self, model_dir=None, provider="cpu", device_id=0, threads=2,
                 providers=None):
        if (type(threads) is not int or threads < 1
                or type(device_id) is not int or device_id < 0):
            raise ValueError("threads must be positive; device_id must be nonnegative")
        self.model_dir = Path(model_dir) if model_dir else Path(__file__).resolve().parent
        self.model_path = self.model_dir / "models" / "studio_voice_48k.onnx"
        self.device_id = device_id
        self.native_session = None
        self.native_error = None
        self.input_buffer = np.zeros(INFERENCE_SAMPLES, np.float32)
        self.binding = None
        self.audio_output = "out_audio_pre_tanh"
        requested = list(providers) if providers is not None else [provider]
        if requested and requested[0].lower() in ("dml", "directml", "dmlexecutionprovider"):
            try:
                self.native_session = NativeDmlSession(self.model_path, device_id, threads)
                self.reset()
                self._infer()
                self.reset()
            except (OSError, RuntimeError, AttributeError) as exc:
                # Retain the same GPU provider on unsupported installations.
                # Runtime errors after a successful start are never concealed.
                self.native_error = str(exc)
                if self.native_session is not None:
                    self.native_session.close()
                    self.native_session = None
        if self.native_session is not None:
            self.session = self.native_session
            using_dml = self.device_binding = True
        else:
            # The final Tanh runs on the host so DirectML can fuse the model.
            self.session = create_session(self.model_path, provider, device_id, threads,
                                          requested if providers is not None else None)
            self.session.disable_fallback()
            using_dml = "DmlExecutionProvider" in self.session.get_providers()
            # ORT's Python DML allocator currently allocates on adapter 0 only.
            self.device_binding = using_dml and device_id == 0
            self.inputs = {item.name: item for item in self.session.get_inputs()}
            self.output_names = [item.name for item in self.session.get_outputs()]
            required = {self.audio_output} | {"out_" + n for n in self.inputs if n != "input_audio"}
            if ("input_audio" not in self.inputs
                    or self.inputs["input_audio"].shape != [1, INFERENCE_SAMPLES]
                    or not required.issubset(self.output_names)):
                raise ValueError("Invalid Studio Voice model interface")
            if self.device_binding:
                self.binding = FixedStateBinding(
                    self.session, {"input_audio": self.input_buffer[None]},
                    {name: "out_" + name for name in self.inputs if name != "input_audio"},
                    {self.audio_output: np.empty((1, INFERENCE_SAMPLES), np.float32)},
                    device_id,
                )
        if self.native_session is None:
            self.reset()
        if using_dml and self.native_session is None:
            # Compile lazy GPU kernels before a live route opens its streams.
            self._infer()
            self.reset()

    @property
    def latency(self):
        return LATENCY

    def reset(self):
        types = {"tensor(float)": np.float32, "tensor(float16)": np.float16,
                 "tensor(int32)": np.int32}
        if self.native_session is not None:
            self.native_session.reset()
        elif self.binding is not None:
            self.binding.reset()
            self.states = self.binding.states
        else:
            self.states = {
                name: np.zeros(item.shape, types[item.type])
                for name, item in self.inputs.items() if name != "input_audio"
            }
        self.input_buffer.fill(0.0)
        self.input_count = 0
        self.output_queue = deque(
            np.zeros(HOP, np.float32) for _ in range(LATENCY // HOP)
        )

    def _infer(self):
        if self.native_session is not None:
            result = {self.audio_output: self.native_session.run(self.input_buffer)}
        elif self.binding is not None:
            result = self.binding.run()
            self.states = self.binding.states
        else:
            result = dict(zip(self.output_names, self.session.run(
                None, {"input_audio": self.input_buffer[None], **self.states}
            )))
            self.states = {name: result["out_" + name] for name in self.states}
        # Preserve the native model's half-precision rounding after activation.
        output = np.tanh(result[self.audio_output]).astype(np.float16).astype(np.float32)
        np.clip(output, -1.0, 1.0, out=output)
        if output.shape != (1, INFERENCE_SAMPLES) or not np.isfinite(output).all():
            raise RuntimeError("Studio Voice returned invalid audio")
        return output

    def process(self, samples):
        samples = np.asarray(samples, dtype=np.float32)
        if samples.shape != (HOP,) or not np.isfinite(samples).all():
            raise ValueError("Expected 480 finite mono samples")
        self.input_buffer[self.input_count:self.input_count + HOP] = samples
        self.input_count += HOP
        if self.input_count == INFERENCE_SAMPLES:
            output = self._infer()
            self.output_queue.extend(
                output[0, i:i + HOP].copy() for i in range(0, INFERENCE_SAMPLES, HOP)
            )
            self.input_count = 0
        return self.output_queue.popleft()

    def process_audio(self, audio):
        """Process a complete waveform, reset state and compensate buffering."""
        audio = np.asarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not np.isfinite(audio).all():
            raise ValueError("Expected finite mono audio")
        self.reset()
        if not audio.size:
            return audio.copy()
        size = ((audio.size + LATENCY + HOP - 1) // HOP) * HOP
        padded = np.pad(audio, (0, size - audio.size))
        result = np.concatenate([
            self.process(padded[i:i + HOP]) for i in range(0, size, HOP)
        ])
        return result[LATENCY:LATENCY + audio.size]
