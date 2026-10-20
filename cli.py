"""Command line interface for the audio-only OpenBroadcast package."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import queue
import sys
import threading
import time
from pathlib import Path

import numpy as np

from . import __version__
from .audio.denoiser import HOP, LATENCY, RATE, Denoiser, DenoiserChain, read_wav, write_wav

ROOT = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _make_engine(args: argparse.Namespace, dereverb: bool = False):
    stages = []
    if dereverb:
        stages.append(
            Denoiser(
                model_file="dereverb_48k.onnx",
                provider=args.provider,
                device_id=args.device_id,
                intensity=args.intensity,
                threads=args.threads,
            )
        )
    stages.append(
        Denoiser(
            provider=args.provider,
            device_id=args.device_id,
            intensity=args.intensity,
            threads=args.threads,
        )
    )
    return stages[0] if len(stages) == 1 else DenoiserChain(stages)


def cmd_info(_: argparse.Namespace) -> int:
    import onnxruntime as ort

    model = ROOT / "audio" / "models" / "denoiser_48k.onnx"
    dereverb = ROOT / "audio" / "models" / "dereverb_48k.onnx"
    info = {
        "version": __version__,
        "onnxruntime": ort.__version__,
        "providers": ort.get_available_providers(),
        "audio_model": str(model),
        "audio_model_sha256": _sha256(model),
        "audio_model_mb": round(model.stat().st_size / 1e6, 1),
        "dereverb_model": str(dereverb),
        "dereverb_model_sha256": _sha256(dereverb),
        "dereverb_model_mb": round(dereverb.stat().st_size / 1e6, 1),
        "sample_rate": RATE,
        "block": HOP,
        "algorithmic_latency_samples": LATENCY,
        "algorithmic_latency_ms": LATENCY / RATE * 1000,
    }
    print(json.dumps(info, indent=2))
    return 0


def cmd_denoise(args: argparse.Namespace) -> int:
    src, dst = Path(args.input), Path(args.output)
    if src.resolve() == dst.resolve():
        raise SystemExit("Use a different output path to preserve the source recording")
    audio = read_wav(src)
    engine = _make_engine(args, dereverb=args.dereverb)
    start = time.perf_counter()
    clean = engine.process_audio(audio)
    elapsed = time.perf_counter() - start
    write_wav(dst, clean)
    print(
        json.dumps(
            {
                "output": str(dst),
                "audio_seconds": round(audio.size / RATE, 3),
                "processing_seconds": round(elapsed, 3),
                "realtime_factor": round(elapsed / (audio.size / RATE), 4) if audio.size else None,
                "dereverb": bool(args.dereverb),
                "stages": 2 if args.dereverb else 1,
                "providers": engine.session.get_providers(),
            },
            indent=2,
        )
    )
    return 0


def cmd_devices(_: argparse.Namespace) -> int:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise SystemExit(f"sounddevice is required: {exc}") from exc
    print(sd.query_devices())
    print("\nDefault input :", sd.default.device[0])
    print("Default output:", sd.default.device[1])
    return 0


def cmd_mic(args: argparse.Namespace) -> int:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise SystemExit(f"sounddevice is required: {exc}") from exc
    if args.list_devices:
        print(sd.query_devices())
        return 0
    if args.input_device is None or args.output_device is None:
        raise SystemExit("Choose --input-device and --output-device (see `devices`).")

    engine = _make_engine(args, dereverb=args.dereverb)
    incoming: queue.Queue = queue.Queue(maxsize=16)
    outgoing: queue.Queue = queue.Queue(maxsize=16)
    stop = threading.Event()
    counters = {"input_drop": 0, "output_underrun": 0, "device_status": 0}
    failures: list[BaseException] = []

    def worker() -> None:
        try:
            while not stop.is_set():
                try:
                    block = incoming.get(timeout=0.1)
                except queue.Empty:
                    continue
                clean = engine.process(block)
                while not stop.is_set():
                    try:
                        outgoing.put(clean, timeout=0.1)
                        break
                    except queue.Full:
                        pass
        except BaseException as exc:
            failures.append(exc)
            stop.set()

    def callback(indata, outdata, frames, _time, status) -> None:
        if status:
            counters["device_status"] += 1
        if frames != HOP:
            outdata.fill(0)
            raise sd.CallbackAbort
        try:
            incoming.put_nowait(indata[:, 0].copy())
        except queue.Full:
            counters["input_drop"] += 1
        try:
            outdata[:, 0] = outgoing.get_nowait()
        except queue.Empty:
            outdata.fill(0)
            counters["output_underrun"] += 1

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    try:
        with sd.Stream(
            samplerate=RATE,
            blocksize=HOP,
            dtype="float32",
            channels=1,
            device=(args.input_device, args.output_device),
            callback=callback,
        ) as stream:
            print(
                f"Noise removal running. Model delay {engine.latency / RATE * 1000:.0f} ms "
                f"+ device buffers. Ctrl+C to stop."
            )
            while not stop.wait(0.2):
                if not stream.active:
                    raise RuntimeError("Audio stream stopped unexpectedly")
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        thread.join(timeout=2)
    print(json.dumps(counters), file=sys.stderr)
    if failures:
        raise RuntimeError("Audio worker failed") from failures[0]
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    seconds = args.seconds
    if not math.isfinite(seconds) or seconds <= 0:
        raise SystemExit("--seconds must be a finite positive number")
    rng = np.random.default_rng(0)
    audio = rng.normal(0, 0.03, int(RATE * seconds)).astype(np.float32)
    engine = Denoiser(provider=args.provider, device_id=args.device_id, threads=args.threads)
    t0 = time.perf_counter()
    engine.process_audio(audio)
    elapsed = time.perf_counter() - t0
    print(
        json.dumps(
            {
                "seconds_audio": seconds,
                "seconds_wall": round(elapsed, 4),
                "realtime_factor": round(elapsed / seconds, 4),
                "providers": engine.session.get_providers(),
            },
            indent=2,
        )
    )
    return 0


def cmd_gui(_: argparse.Namespace) -> int:
    from .gui import main as gui_main

    return gui_main()


def cmd_process(args: argparse.Namespace) -> int:
    from .audio.files import process_file
    result = process_file(
        args.input, args.output, noise=not args.no_noise, dereverb=args.dereverb,
        noise_strength=args.noise_strength, dereverb_strength=args.dereverb_strength,
        provider=args.provider, threads=args.threads, device_id=args.device_id,
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="openbroadcast",
        description="Portable NVIDIA Broadcast audio effects: noise removal and room echo removal.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command")
    p.set_defaults(func=cmd_gui)

    def common(sp):
        sp.add_argument(
            "--provider",
            default="cpu",
            help="onnxruntime provider alias: cpu, cuda, dml, coreml, rocm, migraphx, openvino",
        )
        sp.add_argument("--device-id", type=int, default=0)
        sp.add_argument("--threads", type=int, default=2)

    info = sub.add_parser("info", help="show model hashes and available providers")
    info.set_defaults(func=cmd_info)

    dn = sub.add_parser("denoise", help="remove background noise from a WAV file")
    dn.add_argument("input")
    dn.add_argument("output")
    dn.add_argument("--intensity", type=float, default=1.0)
    dn.add_argument("--dereverb", action="store_true", help="remove room reverb before noise removal")
    common(dn)
    dn.set_defaults(func=cmd_denoise)

    files = sub.add_parser("process", help="process WAV/FLAC/OGG with independent effects, preserve channels")
    files.add_argument("input")
    files.add_argument("output")
    files.add_argument("--no-noise", action="store_true")
    files.add_argument("--dereverb", action="store_true")
    files.add_argument("--noise-strength", type=float, default=1.0)
    files.add_argument("--dereverb-strength", type=float, default=1.0)
    common(files)
    files.set_defaults(func=cmd_process)

    dev = sub.add_parser("devices", help="list audio devices")
    dev.set_defaults(func=cmd_devices)

    mic = sub.add_parser("mic", help="real-time microphone noise removal")
    mic.add_argument("--list-devices", action="store_true")
    mic.add_argument("--input-device", type=int)
    mic.add_argument("--output-device", type=int)
    mic.add_argument("--intensity", type=float, default=1.0)
    mic.add_argument("--dereverb", action="store_true", help="remove room reverb before noise removal")
    common(mic)
    mic.set_defaults(func=cmd_mic)

    bench = sub.add_parser("benchmark", help="measure audio real-time factor")
    bench.add_argument("--seconds", type=float, default=10.0)
    common(bench)
    bench.set_defaults(func=cmd_benchmark)

    gui = sub.add_parser("gui", help="launch the audio control panel")
    gui.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
