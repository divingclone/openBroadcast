"""Opt-in portable-package check; uses temporary settings and no audio streams."""
from pathlib import Path
import hashlib
import json
import tempfile
import time
import traceback


def run(report_path):
    report = {"ok": False, "inference": []}
    root = app = None
    try:
        import numpy as np
        import soundfile as sf
        import tkinter as tk
        from .audio.denoiser import Denoiser, RATE
        from .audio.inference import discover_gpus
        from .audio.runtime import list_devices
        from .gui import App
        from .settings import SettingsStore
        from .i18n import get_language, tr

        report["language"] = get_language()
        for guide in ("README.md", "README.zh-CN.md"):
            assert Path(__file__).with_name(guide).is_file(), f"Missing user guide: {guide}"

        report["devices"] = len(list_devices())
        # Fixed nonzero signal exercises FFT, model state and audio serialization.
        samples = (0.03 * np.sin(np.arange(4800) * (2 * np.pi * 437 / RATE))).astype("float32")
        choices = [("cpu", 0, "CPU")]
        choices += [(gpu.provider, gpu.device_id, gpu.name) for gpu in discover_gpus() if gpu.available]
        for provider, device, name in choices:
            for model in ("denoiser_48k.onnx", "dereverb_48k.onnx"):
                engine = Denoiser(provider=provider, device_id=device, model_file=model)
                output = engine.process_audio(samples)
                assert output.shape == samples.shape and np.isfinite(output).all()
                report["inference"].append({
                    "device": name, "provider": provider, "model": model,
                    "active_providers": engine.session.get_providers(),
                    "sha256": hashlib.sha256(output.tobytes()).hexdigest(),
                })
                del engine
        with tempfile.TemporaryDirectory(prefix="OpenBroadcast-check-") as temporary:
            folder = Path(temporary)
            sf.write(folder / "test.wav", samples, RATE, subtype="FLOAT")
            restored, rate = sf.read(folder / "test.wav", dtype="float32")
            assert rate == RATE and np.array_equal(samples, restored)
            root = tk.Tk()
            root.withdraw()
            app = App(root, SettingsStore(folder / "settings.json"))
            assert app.heading.cget("text") == tr("音频"), "UI language was not applied"
            deadline = time.monotonic() + 10
            while not app.tray_ready and time.monotonic() < deadline:
                root.update()
                if app.tray is None:
                    raise RuntimeError("Tray initialization failed")
                time.sleep(0.02)
            assert app.tray_ready, "Tray startup timed out"
            assert not app.expanded, "Default layout must be compact"
            app.toggle_layout()
            assert app.store.load()["expanded"], "Layout preference was not saved"
            app.toggle_layout()
            report["gui"] = "Tk layout, saved preferences and native tray initialized"
            app.request_exit()
            deadline = time.monotonic() + 5
            while not app.closed and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            assert app.closed, "GUI shutdown timed out"
            root = None
        report["ok"] = True
    except Exception:
        report["error"] = traceback.format_exc()
    finally:
        if app and app.tray:
            app.tray.stop()
        if root:
            root.destroy()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
