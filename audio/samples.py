"""Optionally read demo WAVs from the user's installed Broadcast ASAR.

No NVIDIA sample assets are copied into, or required by, this project.
"""
from __future__ import annotations

import io
import json
import os
import struct
from pathlib import Path

MAX_SAMPLE_BYTES = 64 * 1024 * 1024


def installed_samples():
    archive = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / (
        "NVIDIA Corporation/NVIDIA Broadcast/resources/app.asar")
    if not archive.is_file():
        return {}
    try:
        with archive.open("rb") as f:
            archive_size = os.fstat(f.fileno()).st_size
            pickle_size, header_size, payload_size, json_size = struct.unpack("<4I", f.read(16))
            data_offset = 8 + header_size
            if (pickle_size != 4 or payload_size != header_size - 4
                    or header_size < 8 or data_offset > archive_size
                    or json_size > 32 * 1024 * 1024 or json_size > header_size - 8):
                return {}
            header = json.loads(f.read(json_size))
        media = header["files"]["build"]["files"]["static"]["files"]["media"]["files"]
        result = {}
        for filename, entry in media.items():
            if (not isinstance(filename, str) or not filename.lower().endswith(".wav")
                    or filename.startswith("silent_audio") or not isinstance(entry, dict)
                    or entry.get("unpacked") or "link" in entry):
                continue
            try:
                relative, size = int(entry["offset"]), int(entry["size"])
            except (ValueError, TypeError, KeyError):
                continue
            offset = data_offset + relative
            if relative >= 0 and 0 < size <= MAX_SAMPLE_BYTES and offset + size <= archive_size:
                result[filename.split(".")[0]] = (archive, offset, size)
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, struct.error):
        return {}


def read_sample(reference):
    import soundfile as sf
    from .denoiser import RATE
    archive, offset, size = reference
    if (type(offset) is not int or type(size) is not int
            or offset < 0 or not 0 < size <= MAX_SAMPLE_BYTES):
        raise ValueError("试听样本大小或位置无效。")
    archive = Path(archive)
    with archive.open("rb") as f:
        if offset + size > os.fstat(f.fileno()).st_size:
            raise ValueError("试听样本已损坏或安装文件已更改。")
        f.seek(offset)
        payload = f.read(size)
        if len(payload) != size:
            raise ValueError("试听样本读取不完整。")
        audio, rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
    if rate != RATE:
        raise ValueError(f"此样本为 {rate} Hz；请通过文件页转换为 48 kHz。")
    return audio
