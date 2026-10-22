"""Run with python -I after installing a wheel, outside the source checkout."""
from importlib import metadata
import json
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

import numpy as np
import soundfile as sf
import sounddevice  # Loads the platform's PortAudio library; opens no devices.
import tkinter

import openbroadcast
from openbroadcast.audio.denoiser import Denoiser, RATE
from openbroadcast.audio.files import process_file
from openbroadcast.audio.studio import StudioVoice


def main():
    package = Path(openbroadcast.__file__).resolve().parent
    site = Path(sysconfig.get_path("purelib")).resolve()
    assert package.is_relative_to(site), f"Source checkout leaked into test: {package}"
    distribution = metadata.distribution("openbroadcast")
    assert distribution.version == openbroadcast.__version__
    entries = {entry.name: entry.value for entry in distribution.entry_points}
    assert entries["openbroadcast"] == "openbroadcast.cli:main"
    assert entries["openbroadcast-gui"] == "openbroadcast.launcher:main"
    for name in ("README.md", "README.zh-CN.md", "run_gui.pyw", "docs/compatibility.md",
                 "tray_worker.py", "tray_process.py", "posix_instance.py"):
        assert (package / name).is_file(), f"Missing installed resource: {name}"

    signal = (0.03 * np.sin(np.arange(4800) * (2 * np.pi * 437 / RATE))).astype("float32")
    for model in ("denoiser_48k.onnx", "dereverb_48k.onnx", "studio_voice_48k.onnx"):
        engine = (StudioVoice(provider="cpu") if model == "studio_voice_48k.onnx"
                  else Denoiser(model_file=model, provider="cpu"))
        output = engine.process_audio(signal)
        assert output.shape == signal.shape and np.isfinite(output).all(), model
        del engine

    with tempfile.TemporaryDirectory(prefix="openbroadcast-wheel-") as temporary:
        folder = Path(temporary)
        sf.write(folder / "input.flac", np.column_stack((signal, -signal)), RATE)
        result = process_file(folder / "input.flac", folder / "output.wav", dereverb=True)
        output, rate = sf.read(folder / "output.wav", always_2d=True)
        assert output.shape == (len(signal), 2) and rate == RATE
        assert result["stages"] == 2 and np.isfinite(output).all()
        scripts = Path(sysconfig.get_path("scripts"))
        suffix = ".exe" if sys.platform == "win32" else ""
        for command in (
            [sys.executable, "-I", "-m", "openbroadcast", "--version"],
            [str(scripts / f"openbroadcast{suffix}"), "--version"],
            [str(scripts / f"openbroadcast-gui{suffix}"), "--help"],
            [sys.executable, "-I", str(package / "run_gui.pyw"), "--help"],
        ):
            subprocess.run(command, cwd=folder, check=True, timeout=30)
        info = subprocess.run(
            [sys.executable, "-I", "-m", "openbroadcast", "info"],
            cwd=folder, check=True, timeout=30, capture_output=True, text=True,
        )
        assert json.loads(info.stdout)["audio_model_sha256"]
    print(json.dumps({"ok": True, "platform": sys.platform, "package": str(package),
                      "version": distribution.version, "tk": tkinter.TkVersion}))


if __name__ == "__main__":
    main()
