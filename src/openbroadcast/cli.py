"""Command line interface for the audio-only OpenBroadcast package."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__
from .audio.denoiser import HOP, LATENCY, RATE, Denoiser, DenoiserChain, read_wav, write_wav
from .audio.inference import inference_options

ROOT = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inference_options(args: argparse.Namespace):
    if args.provider == "auto":
        if args.device_id is not None:
            raise ValueError("--device-id requires an explicit --provider (for example cuda or dml)")
        return inference_options(dict(inference_mode="auto", threads=args.threads))
    return dict(provider=args.provider, device_id=args.device_id or 0, threads=args.threads)


def _make_engine(args: argparse.Namespace, dereverb: bool = False):
    options = _inference_options(args)
    stages = []
    if dereverb:
        stages.append(
            Denoiser(
                model_file="dereverb_48k.onnx",
                intensity=args.intensity,
                **options,
            )
        )
    stages.append(
        Denoiser(
            intensity=args.intensity,
            **options,
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

    from .audio.runtime import AudioRoute, EffectSettings

    # Separate input/output streams support independent physical/virtual devices,
    # including CoreAudio. Reuse the GUI's worker and Windows COM lifecycle.
    route = AudioRoute("microphone", sd_module=sd)
    route.start(
        args.input_device, args.output_device, channels=1,
        effects=EffectSettings(noise=True, dereverb=args.dereverb,
                               noise_strength=args.intensity, dereverb_strength=args.intensity),
        **_inference_options(args),
    )
    announced = False
    try:
        while True:
            state = route.snapshot()
            if state["state"] == "error":
                raise RuntimeError(state["error"])
            if state["state"] == "running" and not announced:
                print(f"Noise removal running. Model delay {state['latency_ms']:.0f} ms "
                      "+ device buffers. Ctrl+C to stop.")
                announced = True
            if not route.busy:
                raise RuntimeError("Audio stream stopped unexpectedly")
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        route.stop(wait=True)
        state = route.snapshot()
        counters = {key: state[key] for key in (
            "input_drop", "output_drop", "output_underrun", "device_status")}
        print(json.dumps(counters), file=sys.stderr)
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    seconds = args.seconds
    if not math.isfinite(seconds) or seconds <= 0:
        raise SystemExit("--seconds must be a finite positive number")
    rng = np.random.default_rng(0)
    audio = rng.normal(0, 0.03, int(RATE * seconds)).astype(np.float32)
    engine = Denoiser(**_inference_options(args))
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
        **_inference_options(args),
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
            default="auto",
            help="default: auto (prefer a high-performance GPU, otherwise CPU); "
                 "aliases: cpu, cuda, dml, coreml, rocm, migraphx, openvino",
        )
        sp.add_argument("--device-id", type=int, help="native device index; requires an explicit --provider")
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
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "provider", None) == "auto" and args.device_id is not None:
        parser.error("--device-id requires an explicit --provider (for example cuda or dml)")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
