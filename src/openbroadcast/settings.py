"""Validated user preferences, stored independently of the source checkout."""
from __future__ import annotations

import copy
import json
import math
import os
import sys
from pathlib import Path
import tempfile
from .i18n import tr


_CHANNEL_DEFAULTS = {
    "enabled": False,
    "noise": True,
    "dereverb": False,
    "noise_strength": 1.0,
    "dereverb_strength": 1.0,
    "input": None,
    "output": None,
    "monitor": None,
}
DEFAULT_SETTINGS = {
    "mic": copy.deepcopy(_CHANNEL_DEFAULTS),
    "speaker": copy.deepcopy(_CHANNEL_DEFAULTS),
    "provider": "cpu",
    "threads": 2,
    "device_id": 0,
    "inference_mode": "auto",
    "gpu": None,
    "theme": "dark",
    "expanded": False,
    "show_performance": True,
}


def _device(value):
    if not isinstance(value, dict):
        return None
    name, hostapi = value.get("name"), value.get("hostapi")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(hostapi, str) or not hostapi.strip():
        return None
    return {"name": name, "hostapi": hostapi}


def validate_settings(values: object) -> dict:
    """Return a fresh, known-key-only configuration with invalid fields reset."""
    result = copy.deepcopy(DEFAULT_SETTINGS)
    if not isinstance(values, dict):
        return result
    for channel in ("mic", "speaker"):
        incoming = values.get(channel)
        if not isinstance(incoming, dict):
            continue
        for key in ("enabled", "noise", "dereverb"):
            if type(incoming.get(key)) is bool:
                result[channel][key] = incoming[key]
        for key in ("noise_strength", "dereverb_strength"):
            value = incoming.get(key)
            if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1:
                result[channel][key] = float(value)
        for key in ("input", "output", "monitor"):
            result[channel][key] = _device(incoming.get(key))
    provider = values.get("provider")
    if isinstance(provider, str) and provider.strip() and len(provider) <= 128:
        result["provider"] = provider.strip()
    if values.get("inference_mode") in ("auto", "cpu", "gpu"):
        result["inference_mode"] = values["inference_mode"]
    elif result["provider"].lower() in (
            "cuda", "dml", "directml", "coreml",
            "cudaexecutionprovider", "dmlexecutionprovider", "coremlexecutionprovider"):
        result["inference_mode"] = "gpu"
    elif isinstance(provider, str) and provider.strip() and len(provider) <= 128:
        # Older settings had only a provider. Preserve their explicit CPU (or
        # unsupported provider) choice instead of treating them as a fresh install.
        result["inference_mode"] = "cpu"
    gpu = values.get("gpu")
    if isinstance(gpu, dict) and all(isinstance(gpu.get(k), str) and 0 < len(gpu[k]) <= 256
                                     for k in ("name", "provider", "identity")):
        result["gpu"] = {k: gpu[k] for k in ("name", "provider", "identity")}
    for key, lower, upper in (("threads", 1, 256), ("device_id", 0, 255)):
        value = values.get(key)
        if type(value) is int and lower <= value <= upper:
            result[key] = value
    if values.get("theme") in ("dark", "light"):
        result["theme"] = values["theme"]
    for key in ("show_performance", "expanded"):
        if type(values.get(key)) is bool:
            result[key] = values[key]
    return result


def default_settings_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "OpenBroadcast" / "settings.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenBroadcast" / "settings.json"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "OpenBroadcast" / "settings.json"


class SettingsStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else default_settings_path()

    def load(self) -> dict:
        """Missing, unreadable or malformed files fall back to safe defaults."""
        try:
            values = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError, RecursionError):
            values = None
        return validate_settings(values)

    def save(self, values: dict) -> None:
        """Atomically replace preferences; retain the previous file on failure."""
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=".settings-", suffix=".json", dir=self.path.parent
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(validate_settings(values), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise OSError(tr("Could not save OpenBroadcast settings to {path}: {error}",
                             path=self.path, error=exc)) from exc
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
