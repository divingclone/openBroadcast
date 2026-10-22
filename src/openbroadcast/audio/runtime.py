"""Threaded, bounded-buffer audio routes for the desktop control panel.

No ONNX session or PortAudio stream is created on the caller's thread. A route
owns its worker, callbacks, model states, and queues; microphone and speaker
routes may therefore run independently. Device indices are session-local.
"""
from __future__ import annotations

from ..i18n import tr

from collections import deque
from contextlib import ExitStack
from dataclasses import dataclass
import math
import queue
import sys
import threading
import time
from typing import Any, Callable

import numpy as np

from .denoiser import Denoiser, HOP, RATE
from .com import audio_thread
from .studio import StudioVoice
from .performance import PerformanceMonitor


@dataclass(frozen=True)
class DeviceInfo:
    index: int
    name: str
    hostapi: str
    input_channels: int
    output_channels: int
    default_input: bool = False
    default_output: bool = False

    @property
    def key(self) -> dict[str, str]:
        """Stable settings identifier; never persist the PortAudio index."""
        return {"name": self.name, "hostapi": self.hostapi}

    @property
    def label(self) -> str:
        return self.name if self.hostapi == "Windows WASAPI" else f"{self.name}  [{self.hostapi}]"


def list_devices(sd_module=None, *, refresh=False) -> list[DeviceInfo]:
    """List usable endpoints, not Windows legacy APIs/driver pins.

    PortAudio WASAPI enumerates MMDevice DEVICE_STATE_ACTIVE endpoints.
    Refresh rebuilds PortAudio's cached inventory; callers MUST stop all
    streams (including preview playback) before requesting a refresh.
    """
    if sd_module is None:
        import sounddevice as sd_module
    if refresh:
        sd_module._terminate()
        sd_module._initialize()
    hosts = sd_module.query_hostapis()
    defaults = sd_module.default.device
    windows = sys.platform == "win32"
    result = []
    for i, device in enumerate(sd_module.query_devices()):
        host = hosts[device["hostapi"]]
        if windows and host["name"] != "Windows WASAPI":
            continue
        inputs = int(device["max_input_channels"])
        outputs = int(device["max_output_channels"])
        if not inputs and not outputs:
            continue
        result.append(DeviceInfo(
            i, str(device["name"]), str(host["name"]),
            inputs, outputs,
            i == (host.get("default_input_device", -1) if windows else defaults[0]),
            i == (host.get("default_output_device", -1) if windows else defaults[1]),
        ))
    return result


def device_matches(saved: dict, device: DeviceInfo) -> bool:
    """Migrate only complete, exact legacy names; never guess truncated names."""
    return device.key == saved or (
        saved.get("hostapi") in ("MME", "Windows DirectSound", "Windows WDM-KS")
        and device.hostapi == "Windows WASAPI" and saved.get("name") == device.name
    )


def resolve_device(
    saved: dict | None, direction: str, devices: list[DeviceInfo],
) -> int | None:
    if direction not in ("input", "output"):
        raise ValueError("direction must be input or output")
    if not isinstance(saved, dict):
        return None
    matches = [
        d for d in devices if device_matches(saved, d)
        and getattr(d, f"{direction}_channels") > 0
    ]
    # Ambiguous names are deliberately not silently routed to another device.
    return matches[0].index if len(matches) == 1 else None


@dataclass(frozen=True)
class EffectSettings:
    noise: bool = True
    dereverb: bool = False
    noise_strength: float = 1.0
    dereverb_strength: float = 1.0
    studio: bool = False

    def __post_init__(self):
        for name in ("noise_strength", "dereverb_strength"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} must be between 0 and 1")

    @property
    def topology(self) -> tuple[bool, bool, bool]:
        return self.noise and not self.studio, self.dereverb and not self.studio, self.studio


class AudioRoute:
    """An asynchronous 48 kHz route, with mono or independent stereo models.

    ``stop(wait=False)`` is suitable for Tk callbacks; poll ``snapshot`` until
    idle before restarting. ``stop(wait=True)`` joins for up to five seconds.
    Recordings are aligned float32 arrays shaped (samples, channels). They
    become available when finished, or after stop_recording / route stop.
    """

    def __init__(
        self, name: str = "microphone", sd_module=None,
        engine_factory: Callable[..., Any] | None = None,
        studio_factory: Callable[..., Any] | None = None,
    ):
        self.name = name
        self._sd = sd_module
        self._factory = engine_factory or Denoiser
        self._studio_factory = studio_factory or StudioVoice
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._effects = EffectSettings()
        self._incoming: queue.Queue = queue.Queue(8)
        self._outgoing: queue.Queue = queue.Queue(8)
        self._stats = self._initial_stats()
        self._performance = None
        self._recording = False
        self._record_raw: list[np.ndarray] = []
        self._record_clean: list[np.ndarray] = []
        self._record_limit = 0
        self._record_skip = 0
        self._record_count = 0
        self._record_error = ""

    @staticmethod
    def _initial_stats() -> dict:
        return dict(
            state="idle", error="", input_peak=0.0, output_peak=0.0,
            input_drop=0, output_drop=0, output_underrun=0, device_status=0,
            process_ms=0.0, latency_ms=0.0, channels=1,
            realtime_factor=0.0, performance_ready=False, performance_warning="",
        )

    def snapshot(self) -> dict:
        with self._lock:
            result = self._stats.copy()
            if self._performance is not None and result["state"] == "running":
                result.update(self._performance.snapshot(time.monotonic()))
            result.update(
                recording=self._recording,
                recorded_seconds=self._record_count / RATE,
                recording_ready=not self._recording and self._record_count > 0,
                recording_error=self._record_error,
            )
            return result

    @property
    def busy(self) -> bool:
        """State may already be idle/error while the worker is still unwinding."""
        return bool(self._thread and self._thread.is_alive())

    def start(
        self, input_device: int, output_device: int, channels: int = 1,
        effects: EffectSettings | None = None, provider: str = "cpu",
        threads: int = 2, device_id: int = 0,
    ) -> None:
        if channels not in (1, 2):
            raise ValueError(tr("Only mono and stereo routes are supported"))
        if input_device is None or output_device is None:
            raise ValueError(tr("Select both input and output devices"))
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError(tr("The route is still running or stopping"))
            self._effects = effects or self._effects
            self._stats = self._initial_stats()
            self._performance = None
            self._stats.update(state="loading", channels=channels)
            self._incoming = queue.Queue(8)
            self._outgoing = queue.Queue(8)
            self._stop = threading.Event()
            self.discard_recording()
            self._thread = threading.Thread(
                target=self._run,
                args=(input_device, output_device, channels,
                      dict(provider=provider, threads=threads, device_id=device_id)),
                name=f"OpenBroadcast-{self.name}", daemon=True,
            )
            self._thread.start()

    def update_effects(self, effects: EffectSettings) -> None:
        if not isinstance(effects, EffectSettings):
            raise TypeError("effects must be EffectSettings")
        with self._lock:
            self._effects = effects

    def stop(self, wait: bool = False) -> None:
        with self._lock:
            thread = self._thread
            self._stop.set()
            if thread and thread.is_alive() and self._stats["state"] != "error":
                self._stats["state"] = "stopping"
        if wait and thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def start_recording(self, max_seconds: float = 20) -> None:
        if not math.isfinite(max_seconds) or not 0 < max_seconds <= 20:
            raise ValueError(tr("Recording duration must be between 0 and 20 seconds"))
        with self._lock:
            if self._stats["state"] != "running":
                raise RuntimeError(tr("Start the audio route before recording"))
            if self._recording:
                raise RuntimeError(tr("A recording is already in progress"))
            self.discard_recording()
            self._record_limit = max(1, int(max_seconds * RATE))
            # Skip the delayed history preceding the user's record action.
            self._record_skip = round(self._stats["latency_ms"] * RATE / 1000)
            self._recording = True

    def stop_recording(self) -> None:
        with self._lock:
            self._recording = False

    def discard_recording(self) -> None:
        with self._lock:
            self._recording = False
            self._record_raw = []
            self._record_clean = []
            self._record_count = 0
            self._record_error = ""

    def get_recording(self) -> tuple[np.ndarray, np.ndarray] | None:
        with self._lock:
            if self._recording or not self._record_count:
                return None
            return (np.concatenate(self._record_raw).copy(),
                    np.concatenate(self._record_clean).copy())

    def _failure(self, exc: BaseException) -> None:
        with self._lock:
            if not self._stats["error"]:
                self._stats.update(state="error", error=f"{type(exc).__name__}: {exc}")
        self._stop.set()

    def _count(self, key: str) -> None:
        with self._lock:
            self._stats[key] += 1
            if self._performance is not None and key in ("input_drop", "output_drop", "output_underrun"):
                self._performance.glitch(time.monotonic())

    def _input_callback(self, data, frames, _time, status) -> None:
        if self._stop.is_set():
            return
        try:
            if status:
                self._count("device_status")
                if getattr(status, "input_overflow", False):
                    self._count("input_drop")
            if frames != HOP:
                raise RuntimeError(tr("Input device returned {frames} frames; expected {HOP}", frames=frames, HOP=HOP))
            block = np.asarray(data, dtype=np.float32).copy()
            if not np.isfinite(block).all():
                raise RuntimeError(tr("Input device returned non-finite samples"))
            self._offer(self._incoming, block, "input_drop")
        except Exception as exc:
            self._failure(exc)

    def _output_callback(self, data, frames, _time, status) -> None:
        data.fill(0)
        if self._stop.is_set():
            return
        try:
            if status:
                self._count("device_status")
                if getattr(status, "output_underflow", False):
                    self._count("output_underrun")
            if frames != HOP:
                raise RuntimeError(tr("Output device requested {frames} frames; expected {HOP}", frames=frames, HOP=HOP))
            try:
                block = self._outgoing.get_nowait()
            except queue.Empty:
                self._count("output_underrun")
                return
            data[:] = block
        except Exception as exc:
            self._failure(exc)

    def _offer(self, target: queue.Queue, block: np.ndarray, counter: str):
        try:
            target.put_nowait(block)
        except queue.Full:
            try:
                target.get_nowait()
            except queue.Empty:
                pass
            self._count(counter)
            try:
                target.put_nowait(block)
            except queue.Full:
                self._count(counter)

    @staticmethod
    def _drain(target: queue.Queue):
        while True:
            try:
                target.get_nowait()
            except queue.Empty:
                return

    def _record(self, raw: np.ndarray, clean: np.ndarray):
        with self._lock:
            if not self._recording:
                return
            skip = min(self._record_skip, len(raw))
            self._record_skip -= skip
            raw, clean = raw[skip:], clean[skip:]
            count = min(len(raw), self._record_limit - self._record_count)
            if count:
                self._record_raw.append(raw[:count].copy())
                self._record_clean.append(clean[:count].copy())
                self._record_count += count
            if self._record_count >= self._record_limit:
                self._recording = False

    def _run(self, input_device: int, output_device: int, channels: int, options: dict):
        thread_resources = ExitStack()
        models: dict[str, list] = {}
        applied: EffectSettings | None = None
        raw_delay: deque = deque()
        try:
            thread_resources.enter_context(audio_thread())
            if self._sd is None:
                import sounddevice
                self._sd = sounddevice
            sd = self._sd
            sd.check_input_settings(device=input_device, channels=channels,
                                    dtype="float32", samplerate=RATE)
            sd.check_output_settings(device=output_device, channels=channels,
                                     dtype="float32", samplerate=RATE)

            def prepare(settings: EffectSettings) -> list[list]:
                if settings.studio:
                    if "studio" not in models:
                        models["studio"] = [self._studio_factory(**options) for _ in range(channels)]
                    return [models["studio"]]
                stages = []
                for enabled, key, strength, filename in (
                    (settings.dereverb, "dereverb", settings.dereverb_strength,
                     "dereverb_48k.onnx"),
                    (settings.noise, "noise", settings.noise_strength,
                     "denoiser_48k.onnx"),
                ):
                    if not enabled:
                        continue
                    if key not in models:
                        models[key] = [
                            self._factory(model_file=filename, intensity=strength, **options)
                            for _ in range(channels)
                        ]
                    for model in models[key]:
                        model.set_intensity(strength)
                    stages.append(models[key])
                return stages

            with self._lock:
                settings = self._effects
            stages = prepare(settings)
            if self._stop.is_set():
                return
            latency = sum(group[0].latency for group in stages)
            if latency % HOP:
                raise RuntimeError(tr("Model latency must be a multiple of the hop size"))
            raw_delay = deque(
                np.zeros((HOP, channels), np.float32)
                for _ in range(latency // HOP)
            )
            applied = settings
            with self._lock:
                self._stats["latency_ms"] = latency / RATE * 1000
            with ExitStack() as resources:
                # Register close immediately, including start failures.
                output = sd.OutputStream(
                    device=output_device, channels=channels, samplerate=RATE,
                    blocksize=HOP, dtype="float32", callback=self._output_callback,
                )
                resources.callback(output.close)
                source = sd.InputStream(
                    device=input_device, channels=channels, samplerate=RATE,
                    blocksize=HOP, dtype="float32", callback=self._input_callback,
                )
                resources.callback(source.close)
                output.start()
                source.start()
                with self._lock:
                    if not self._stop.is_set():
                        self._performance = PerformanceMonitor(time.monotonic())
                        self._stats["state"] = "running"
                while not self._stop.is_set():
                    if not source.active or not output.active:
                        raise RuntimeError(tr("An audio device stopped unexpectedly or disconnected"))
                    with self._lock:
                        settings = self._effects
                    if settings != applied:
                        changed = applied is None or settings.topology != applied.topology
                        if changed:
                            with self._lock:
                                self._performance = None
                        stages = prepare(settings)
                        if self._stop.is_set():
                            break
                        if changed:
                            for group in models.values():
                                for model in group:
                                    model.reset()
                            latency = sum(group[0].latency for group in stages)
                            if latency % HOP:
                                raise RuntimeError(tr("Model latency must be a multiple of the hop size"))
                            raw_delay = deque(
                                np.zeros((HOP, channels), np.float32)
                                for _ in range(latency // HOP)
                            )
                            self._drain(self._outgoing)
                            if applied is not None:
                                self._drain(self._incoming)
                                with self._lock:
                                    if self._recording:
                                        self.discard_recording()
                                        self._record_error = "Effects changed during recording; record again."
                            with self._lock:
                                self._stats["latency_ms"] = latency / RATE * 1000
                                self._performance = PerformanceMonitor(time.monotonic())
                        applied = settings
                    try:
                        block = self._incoming.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    start = time.perf_counter()
                    clean = block.copy()
                    for group in stages:
                        clean = np.column_stack([
                            model.process(clean[:, channel])
                            for channel, model in enumerate(group)
                        ])
                    if not np.isfinite(clean).all():
                        raise RuntimeError(tr("The audio model returned non-finite samples"))
                    clean = np.clip(clean, -1, 1).astype(np.float32, copy=False)
                    elapsed = (time.perf_counter() - start) * 1000
                    raw_delay.append(block)
                    aligned_raw = raw_delay.popleft()
                    self._record(aligned_raw, clean)
                    with self._lock:
                        if self._performance is not None:
                            self._performance.processed(time.monotonic(), elapsed)
                        self._stats.update(
                            input_peak=float(np.max(np.abs(block))),
                            output_peak=float(np.max(np.abs(clean))),
                        )
                    self._offer(self._outgoing, clean, "output_drop")
        except Exception as exc:
            self._failure(exc)
        finally:
            self._stop.set()
            self._drain(self._incoming)
            self._drain(self._outgoing)
            with self._lock:
                self._performance = None
                self._recording = False
                self._stats.update(input_peak=0.0, output_peak=0.0)
                if self._stats["state"] != "error":
                    self._stats["state"] = "idle"
            thread_resources.close()
