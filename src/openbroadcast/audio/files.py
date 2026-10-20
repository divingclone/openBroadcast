"""Bounded-memory audio file processing with independently stateful channels.

WAV, FLAC and OGG inputs are decoded by libsndfile. Non-48 kHz inputs use
continuous linear interpolation across read boundaries. This lightweight
resampler is not band-limited: downsampling may alias high-frequency content.
Outputs are 48 kHz PCM16 WAV or FLAC. Enabled model stages run dereverb first,
then noise removal; their combined algorithmic delay is flushed and removed.
"""
from __future__ import annotations

from ..i18n import tr

from concurrent.futures import CancelledError
import math
import os
from pathlib import Path
import tempfile
import time

import numpy as np
import soundfile as sf

from .denoiser import Denoiser, HOP, LATENCY, RATE


def _check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise CancelledError(tr("Audio file processing was cancelled"))


def _resampled_blocks(source: sf.SoundFile, output_frames: int, cancel=None):
    """Yield at most HOP frames using a single shared integer resampling phase."""
    buffer = np.empty((0, source.channels), dtype=np.float32)
    base = 0
    for start in range(0, output_frames, HOP):
        _check_cancel(cancel)
        end = min(start + HOP, output_frames)
        positions = np.arange(start, end, dtype=np.int64) * source.samplerate
        indices = positions // RATE
        following = np.minimum(indices + 1, source.frames - 1)
        indices = np.minimum(indices, source.frames - 1)
        needed = int(following[-1]) + 1
        while base + len(buffer) < needed:
            _check_cancel(cancel)
            chunk = source.read(min(65536, max(4096, needed - base - len(buffer))),
                                dtype="float32", always_2d=True)
            if not len(chunk):
                raise ValueError(tr("Input audio ended before its declared frame count"))
            if not np.isfinite(chunk).all():
                raise ValueError(tr("Input audio contains NaN or infinite samples"))
            buffer = np.concatenate((buffer, chunk))
        fraction = ((positions % RATE) / RATE).astype(np.float32)[:, None]
        first = buffer[indices - base]
        second = buffer[following - base]
        yield first + fraction * (second - first)
        # Retain the preceding interpolation sample and unread source frames.
        discard = int(indices[-1]) - base
        if discard:
            buffer = buffer[discard:].copy()
            base += discard


def process_file(
    input_path,
    output_path,
    noise=True,
    dereverb=False,
    noise_strength=1.0,
    dereverb_strength=1.0,
    provider="cpu",
    threads=2,
    device_id=0,
    progress=None,
    cancel=None,
) -> dict:
    """Process a file atomically and return metadata.

    ``progress`` receives fractions from 0 to 1 on the calling worker thread.
    ``cancel`` accepts a threading.Event. Cancellation leaves any existing
    destination intact and raises concurrent.futures.CancelledError.
    Every channel gets independent model state. With both effects disabled,
    processing bypasses model construction (resampling/PCM encoding still apply).
    """
    for label, value in (("noise_strength", noise_strength),
                         ("dereverb_strength", dereverb_strength)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{label} must be a finite number between 0 and 1")
    if type(threads) is not int or threads < 1 or type(device_id) is not int or device_id < 0:
        raise ValueError("threads must be a positive integer; device_id must be nonnegative")
    src, dst = Path(input_path), Path(output_path)
    if src.resolve() == dst.resolve() or (
        src.exists() and dst.exists() and os.path.samefile(src, dst)
    ):
        raise ValueError(tr("Choose a different output path to preserve the source recording"))
    output_format = {".wav": "WAV", ".flac": "FLAC"}.get(dst.suffix.lower())
    if output_format is None:
        raise ValueError(tr("Output must be a .wav or .flac file"))
    _check_cancel(cancel)
    started = time.perf_counter()
    temporary = None
    try:
        with sf.SoundFile(str(src)) as source:
            if source.format not in ("WAV", "WAVEX", "RF64", "FLAC", "OGG"):
                raise ValueError(tr("Input must be a WAV, FLAC or OGG audio file"))
            frames = (source.frames * RATE + source.samplerate // 2) // source.samplerate
            if not frames and output_format == "FLAC":
                raise ValueError(tr("Empty audio cannot be encoded as FLAC; choose WAV output"))
            stages = []
            for enabled, model, strength in (
                (dereverb, "dereverb_48k.onnx", dereverb_strength),
                (noise, "denoiser_48k.onnx", noise_strength),
            ):
                if enabled:
                    per_channel = []
                    for _ in range(source.channels):
                        _check_cancel(cancel)
                        per_channel.append(Denoiser(
                            model_file=model, intensity=strength, provider=provider,
                            threads=threads, device_id=device_id,
                        ))
                    stages.append(per_channel)
            latency = LATENCY * len(stages)
            total = ((frames + latency + HOP - 1) // HOP) * HOP if frames else 0
            fd, temporary = tempfile.mkstemp(prefix=f".{dst.stem}-", suffix=dst.suffix,
                                              dir=dst.parent)
            os.close(fd)
            if progress:
                progress(0.0)
            last_progress = 0.0
            written = 0
            stream = iter(_resampled_blocks(source, frames, cancel))
            with sf.SoundFile(temporary, mode="w", samplerate=RATE, channels=source.channels,
                              format=output_format, subtype="PCM_16") as output:
                for offset in range(0, total, HOP):
                    _check_cancel(cancel)
                    block = next(stream, None)
                    if block is None:
                        block = np.zeros((HOP, source.channels), dtype=np.float32)
                    elif len(block) < HOP:
                        block = np.pad(block, ((0, HOP - len(block)), (0, 0)))
                    for stage in stages:
                        block = np.column_stack([
                            engine.process(block[:, channel])
                            for channel, engine in enumerate(stage)
                        ])
                    left = max(0, latency - offset)
                    count = min(HOP - left, frames - written)
                    if count > 0:
                        output.write(block[left:left + count])
                        written += count
                    if progress:
                        fraction = min((offset + HOP) / max(total, 1), 0.999)
                        # Keep GUI event queues bounded even when bypassing
                        # hours of audio much faster than real time.
                        if fraction - last_progress >= 0.005:
                            progress(fraction)
                            last_progress = fraction
            _check_cancel(cancel)
            metadata = {
                "input": str(src), "output": str(dst),
                "input_sample_rate": source.samplerate, "sample_rate": RATE,
                "channels": source.channels, "input_frames": source.frames,
                "frames": written, "audio_seconds": written / RATE,
                "noise": bool(noise), "dereverb": bool(dereverb),
                "noise_strength": noise_strength, "dereverb_strength": dereverb_strength,
                "stages": len(stages), "latency_samples": latency,
                "resampling": "none" if source.samplerate == RATE else "linear",
                "provider": provider, "format": output_format, "subtype": "PCM_16",
            }
        os.replace(temporary, dst)
        temporary = None
        metadata["processing_seconds"] = time.perf_counter() - started
        if progress:
            progress(1.0)
        return metadata
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except OSError:
                pass
