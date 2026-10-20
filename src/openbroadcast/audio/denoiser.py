"""Portable NVIDIA Broadcast / AFX 48 kHz noise-removal engine.

The CNN + 4-layer GRU weights in ``models/denoiser_48k.onnx`` were extracted
from the TensorRT plan that ships with NVIDIA Broadcast 2.3
(``nvbcast_afx_bnr_v0_9``).  The DSP coefficients in ``data/dsp_48k.npz`` are
the original analysis/synthesis windows and 961x320 mel matrix.

Only NumPy and ONNX Runtime are required at run time.  No CUDA, TensorRT,
NVIDIA DLL or RTX GPU is needed; ONNX Runtime may use CPU, DirectML, CoreML,
ROCm, OpenVINO or CUDA when those providers are installed.
"""
from __future__ import annotations

from ..i18n import tr

from collections import deque
from pathlib import Path
from typing import Iterable, Mapping

import numpy as np
import onnxruntime as ort

ROOT = Path(__file__).resolve().parent
RATE = 48_000
HOP = 480                 # 10 ms
FFT = 1_920               # 40 ms
BLOCK = 1_920             # one inference = 4 hops
LATENCY = 3_360           # 70 ms model delay
MEL_BINS = 320
MASK_BINS = 961
STATES = (256, 256, 512, 1024)

_PROVIDER_ALIASES = {
    "cpu": "CPUExecutionProvider",
    "cuda": "CUDAExecutionProvider",
    "dml": "DmlExecutionProvider",
    "directml": "DmlExecutionProvider",
    "coreml": "CoreMLExecutionProvider",
    "rocm": "ROCMExecutionProvider",
    "migraphx": "MIGraphXExecutionProvider",
    "openvino": "OpenVINOExecutionProvider",
    "trt": "TensorrtExecutionProvider",
}


class PeakTracker:
    """Four-candidate expiring peak queue used by the original SDK.

    The queue keeps the largest recent peaks, expires entries after
    ``timeout`` samples, and returns 1.0 when it is empty.
    """

    __slots__ = ("timeout", "age", "entries")

    def __init__(self, timeout: int):
        self.timeout = int(timeout)
        self.age = self.timeout
        self.entries: list[list] = []

    def add(self, value: float) -> None:
        live = [e for e in self.entries if e[1]]
        if len(live) < 4 or value > min(e[2] for e in live):
            if len(live) == 4:
                min(live, key=lambda e: e[2])[1] = False
            self.entries.append([self.age, True, float(value)])
            self.age = 0
        while self.entries and not self.entries[0][1]:
            gap = self.entries.pop(0)[0]
            if self.entries:
                self.entries[0][0] += gap
        if self.entries:
            if self.entries[0][0] <= 0:
                self.entries.pop(0)
            else:
                self.entries[0][0] -= 1
        self.age = min(self.timeout, self.age + 1)

    def maximum(self) -> float:
        return max((e[2] for e in self.entries if e[1]), default=1.0)

    def copy_from(self, other: "PeakTracker") -> None:
        self.age = other.age
        self.entries = [e.copy() for e in other.entries if e[1]]


class Denoiser:
    """One mono 48 kHz stream.

    ``process()`` consumes exactly 480 float32 samples (10 ms) and returns the
    same number.  The model has a fixed 3360-sample (70 ms) algorithmic delay;
    ``process_audio()`` processes a whole waveform, flushes the tail and
    compensates that delay so input and output have equal length.
    """

    @property
    def latency(self) -> int:
        return LATENCY

    def __init__(
        self,
        model_dir: str | Path | None = None,
        provider: str = "cpu",
        device_id: int = 0,
        intensity: float = 1.0,
        threads: int = 2,
        providers: Iterable[str] | None = None,
        model_file: str = "denoiser_48k.onnx",
    ) -> None:
        if not 0.0 <= float(intensity) <= 1.0:
            raise ValueError("intensity must be between 0 and 1")
        if threads < 1 or device_id < 0:
            raise ValueError("threads must be positive; device_id must be nonnegative")
        self.intensity = np.float32(intensity)
        self.model_dir = Path(model_dir) if model_dir else ROOT
        self.model_file = str(model_file)
        self.model_path = self.model_dir / "models" / self.model_file

        with np.load(self.model_dir / "data" / "dsp_48k.npz", allow_pickle=False) as dsp:
            self.window = dsp["analysis_window"].astype(np.float32, copy=True)
            self.synthesis_window = dsp["synthesis_window"].astype(np.float32, copy=True)
            mel = dsp["mel"].astype(np.float32, copy=True)
        self.mel_bin, self.mel_band = np.nonzero(mel)
        self.mel_value = mel[self.mel_bin, self.mel_band]

        self.session = self._create_session(provider, device_id, threads, providers)
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.reset()

    # ------------------------------------------------------------------ setup
    @staticmethod
    def _provider_options(name: str, device_id: int) -> tuple[str, dict]:
        opts: dict = {}
        if name in ("DmlExecutionProvider", "CUDAExecutionProvider", "ROCMExecutionProvider"):
            opts["device_id"] = int(device_id)
        if name == "CUDAExecutionProvider":
            opts["cudnn_conv_algo_search"] = "HEURISTIC"
        if name == "CoreMLExecutionProvider":
            if device_id != 0:
                raise ValueError("CoreML uses system-managed GPU selection; --device-id must be 0")
            opts["MLComputeUnits"] = "CPUAndGPU"
        return name, opts

    def _create_session(
        self,
        provider: str,
        device_id: int,
        threads: int,
        providers: Iterable[str] | None,
    ) -> ort.InferenceSession:
        available = ort.get_available_providers()
        if providers is None:
            requested = [_PROVIDER_ALIASES.get(provider.lower(), provider)]
        else:
            requested = [str(p) for p in providers]
        chosen = [p for p in requested if p in available]
        unknown = [p for p in requested if p not in available]
        if not chosen:
            raise RuntimeError(
                f"Requested provider(s) {unknown or requested} are unavailable. "
                f"Installed providers: {available}"
            )
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(threads)
        options.enable_mem_pattern = "DmlExecutionProvider" not in chosen
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        provider_list = []
        for name in chosen:
            name, opts = self._provider_options(name, device_id)
            provider_list.append((name, opts))
        if "CPUExecutionProvider" not in chosen:
            provider_list.append("CPUExecutionProvider")
        session = ort.InferenceSession(
            str(self.model_path), sess_options=options, providers=provider_list
        )
        if not any(p in session.get_providers() for p in chosen):
            raise RuntimeError(tr('所选推理后端初始化失败，请检查 GPU 运行库及驱动，或在设置中切换到 CPU。'))
        return session

    def set_intensity(self, intensity: float) -> None:
        if not 0.0 <= float(intensity) <= 1.0:
            raise ValueError("intensity must be between 0 and 1")
        self.intensity = np.float32(intensity)

    # ------------------------------------------------------------------- state
    def reset(self) -> None:
        self.states: dict[str, np.ndarray] = {
            f"input_{i}": np.zeros((1, n), np.float32)
            for i, n in enumerate(STATES, 1)
        }
        self.audio_history = np.zeros(FFT - HOP, np.float32)
        self.feature_history = np.zeros((6, MEL_BINS), np.float32)
        self.overlap = np.zeros(FFT - HOP, np.float32)
        self.pending: list[np.ndarray] = []
        self.queue = np.zeros(BLOCK, np.float32)
        self.long_peak = PeakTracker(60_000)
        self.short_peak = PeakTracker(8_000)
        self.peak_history = np.ones(3, np.float32)
        self.flag_history = np.zeros(3, bool)
        self.vad_history = deque([np.float32(0.0)] * 15)
        self.vad_sum = np.float32(0.0)
        self.vad_active = False

    # ------------------------------------------------------------------- input
    def _normalize(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        peak = np.max(np.abs(audio[:HOP]))
        self.long_peak.add(peak)
        self.short_peak.add(peak)
        peaks = np.concatenate((self.peak_history, np.ones(4, np.float32)))
        flags = np.concatenate((self.flag_history, np.zeros(4, bool)))
        audio = audio.copy()
        for i in range(4):
            peaks[3 + i] = self.long_peak.maximum()
            p = peaks[3]
            if not flags[2]:
                flags[3 + i] = self.vad_active and (
                    p < np.float32(0.075) or self.short_peak.maximum() < np.float32(0.075)
                )
                if flags[3 + i] and p > np.float32(0.075):
                    self.long_peak.copy_from(self.short_peak)
            else:
                flags[3 + i] = p < np.float32(0.075)
            if -np.finfo(np.float32).eps < p < np.finfo(np.float32).eps:
                flags[3 + i] = False
            if flags[3 + i]:
                audio[i * HOP:(i + 1) * HOP] *= np.float32(0.3) / p
        self.peak_history = peaks[-3:].copy()
        self.flag_history = flags[-3:].copy()
        return audio, peaks[:4], flags[:4]

    # ------------------------------------------------------------------ output
    def _restore_gain(self, audio: np.ndarray, peaks: np.ndarray, flags: np.ndarray) -> np.ndarray:
        for hop in audio.reshape(4, HOP):
            self.vad_sum = np.float32(self.vad_sum - self.vad_history.popleft())
            energy = np.cumsum(np.abs(hop), dtype=np.float32)[-1]
            self.vad_history.append(energy)
            self.vad_sum = np.float32(self.vad_sum + energy)
            self.vad_active = self.vad_sum / np.float32(7_200) > np.float32(1e-4)
            if not self.vad_active:
                break
        for i in range(4):
            if flags[i]:
                audio[i * HOP:(i + 1) * HOP] *= peaks[i] / np.float32(0.3)
        return audio

    # ----------------------------------------------------------------- features
    def _features(self, spectrum: np.ndarray) -> np.ndarray:
        power = (spectrum.real ** 2 + spectrum.imag ** 2).astype(np.float32)
        # The original packed real FFT folds Nyquist into the DC imaginary part.
        power[:, 0] += power[:, -1]
        power[:, -1] = 0.0
        mel = np.stack(
            [
                np.bincount(
                    self.mel_band,
                    weights=p[self.mel_bin] * self.mel_value,
                    minlength=MEL_BINS,
                )
                for p in power
            ]
        ).astype(np.float32)
        return np.clip(
            np.log10(np.maximum(mel, np.float32(2 ** -24))) * np.float32(1 / 8.8)
            + np.float32(4 / 8.8),
            0.0,
            1.0,
        )

    def _infer_block(self, audio: np.ndarray) -> np.ndarray:
        audio, peaks, flags = self._normalize(audio)
        joined = np.concatenate((self.audio_history, audio))
        frames = np.stack([joined[i * HOP:i * HOP + FFT] for i in range(4)])
        spectrum = np.fft.rfft(frames * self.window, axis=1).astype(np.complex64)
        features = np.concatenate((self.feature_history, self._features(spectrum)))
        outputs = dict(
            zip(
                self.output_names,
                self.session.run(None, {"main_input": features[None, None], **self.states}),
            )
        )
        self.states = {
            f"input_{i}": outputs[f"output_{i}"][:, -1, :].copy()
            for i in range(1, 5)
        }
        self.feature_history = features[-6:].copy()
        self.audio_history = joined[-(FFT - HOP):].copy()
        gain = 1.0 - self.intensity * outputs["main_output"][0]
        gain[:, -1] = gain[:, 0]
        frames = np.fft.irfft(spectrum * gain, n=FFT, axis=1).astype(np.float32)
        frames *= self.synthesis_window
        ola = np.zeros(BLOCK + FFT - HOP, np.float32)
        ola[:FFT - HOP] = self.overlap
        for i, frame in enumerate(frames):
            ola[i * HOP:i * HOP + FFT] += frame
        self.overlap = ola[BLOCK:].copy()
        return self._restore_gain(ola[:BLOCK], peaks, flags)

    # ------------------------------------------------------------------- public
    def process(self, samples: Iterable[float]) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.shape != (HOP,) or not np.isfinite(samples).all():
            raise ValueError(tr("Expected 480 finite mono samples"))
        self.pending.append(samples.copy())
        if len(self.pending) == 4:
            block = np.concatenate(self.pending)
            self.pending.clear()
            self.queue = np.concatenate((self.queue, self._infer_block(block)))
        result = self.queue[:HOP].copy()
        self.queue = self.queue[HOP:]
        return result

    def process_audio(self, samples: Iterable[float]) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32)
        if samples.ndim != 1 or not np.isfinite(samples).all():
            raise ValueError(tr("Expected finite mono audio"))
        self.reset()
        if not samples.size:
            return samples.copy()
        total = ((samples.size + LATENCY + BLOCK - 1) // BLOCK) * BLOCK
        padded = np.pad(samples, (0, total - samples.size))
        result = np.concatenate(
            [self.process(padded[i:i + HOP]) for i in range(0, total, HOP)]
        )
        return result[LATENCY:LATENCY + samples.size]


class DenoiserChain:
    """Run several 48 kHz models in series (for example dereverb -> denoise)."""

    def __init__(self, stages: Iterable[Denoiser]) -> None:
        self.stages = list(stages)
        if not self.stages:
            raise ValueError("a DenoiserChain needs at least one stage")

    @property
    def latency(self) -> int:
        return LATENCY * len(self.stages)

    @property
    def session(self):
        return self.stages[-1].session

    @property
    def model_path(self) -> Path:
        return self.stages[-1].model_path

    def set_intensity(self, value: float) -> None:
        for stage in self.stages:
            stage.set_intensity(value)

    def reset(self) -> None:
        for stage in self.stages:
            stage.reset()

    def process(self, block: np.ndarray) -> np.ndarray:
        for stage in self.stages:
            block = stage.process(block)
        return block

    def process_audio(self, audio: np.ndarray) -> np.ndarray:
        for stage in self.stages:
            audio = stage.process_audio(audio)
        return audio


def read_wav(path: str | Path) -> np.ndarray:
    """Read a 16-bit PCM WAV at 48 kHz and return mono float32 in [-1, 1]."""
    import wave

    with wave.open(str(path), "rb") as f:
        if f.getsampwidth() != 2 or f.getcomptype() != "NONE":
            raise ValueError(tr("Use a 16-bit PCM WAV file"))
        rate, channels = f.getframerate(), f.getnchannels()
        audio = np.frombuffer(f.readframes(f.getnframes()), "<i2").astype(np.float32)
    if rate != RATE:
        raise ValueError(tr("NVIDIA Broadcast's 48 kHz model requires 48 kHz audio"))
    return audio.reshape(-1, channels).mean(axis=1) / np.float32(32768)


def write_wav(path: str | Path, audio: np.ndarray) -> None:
    import wave

    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(np.clip(np.rint(audio * 32768), -32768, 32767).astype("<i2").tobytes())
