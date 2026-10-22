"""Optional Windows DirectML execution with explicitly owned GPU resources.

The small helper uses the C API DLLs supplied by onnxruntime-directml. Other
platforms and installations without that helper retain the Python ORT path.
"""
from __future__ import annotations

import ctypes as C
from pathlib import Path
import platform
import threading
import weakref

import numpy as np
import onnxruntime as ort


class NativeDmlUnavailable(RuntimeError):
    """This installation cannot use the optional native execution helper."""


class Timing(C.Structure):
    _fields_ = [(name, C.c_double) for name in (
        "cpu_upload_ms", "cpu_submit_ms", "cpu_wait_ms", "cpu_download_ms",
        "total_ms", "gpu_upload_ms", "gpu_inference_queue_ms", "gpu_download_ms",
    )]


class NativeDmlSession:
    """A single mono Studio Voice stream; run/reset/close are serialized."""

    def __init__(self, model_path, device_id=0, threads=2, *, profile=False):
        self._lock = threading.RLock()
        self._finalizer = None
        self._profile = profile
        if platform.system() != "Windows" or platform.machine().lower() not in ("amd64", "x86_64"):
            raise NativeDmlUnavailable("Native DirectML requires Windows x64")
        helper = Path(__file__).with_name("native") / "explicit_dml.dll"
        runtime = Path(ort.__file__).resolve().parent / "capi"
        if not all(path.is_file() for path in (
            helper, runtime / "onnxruntime.dll", runtime / "DirectML.dll",
        )):
            raise NativeDmlUnavailable("Native DirectML runtime files are unavailable")
        try:
            self._lib = C.CDLL(str(helper))
        except OSError as exc:
            raise NativeDmlUnavailable(str(exc)) from exc
        lib = self._lib
        lib.edml_error.restype = C.c_char_p
        lib.edml_create.argtypes = [C.c_wchar_p, C.c_wchar_p, C.c_int, C.c_int, C.c_int]
        lib.edml_create.restype = C.c_void_p
        lib.edml_process.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(Timing)]
        lib.edml_process.restype = C.c_int
        lib.edml_reset.argtypes = [C.c_void_p]
        lib.edml_reset.restype = C.c_int
        lib.edml_destroy.argtypes = [C.c_void_p]
        lib.edml_destroy.restype = None
        lib.edml_adapter.argtypes = [C.c_void_p]
        lib.edml_adapter.restype = C.c_wchar_p
        lib.edml_audio_samples.argtypes = [C.c_void_p, C.c_int]
        lib.edml_audio_samples.restype = C.c_size_t
        self._handle = lib.edml_create(str(model_path), str(runtime), device_id, profile, threads)
        if not self._handle:
            raise RuntimeError(self._error())
        self._finalizer = weakref.finalize(self, lib.edml_destroy, self._handle)
        self.adapter_name = lib.edml_adapter(self._handle)
        self.input_samples = lib.edml_audio_samples(self._handle, 0)
        self.output = np.empty((1, lib.edml_audio_samples(self._handle, 1)), np.float32)
        self.last_timing = None

    def _error(self):
        return self._lib.edml_error().decode("utf-8", errors="replace")

    def _check_open(self):
        if self._finalizer is None or not self._finalizer.alive:
            raise RuntimeError("Native DirectML session is closed")

    def get_providers(self):
        return ["DmlExecutionProvider", "CPUExecutionProvider"]

    def run(self, audio):
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.size != self.input_samples:
            raise ValueError("Invalid Studio Voice input size")
        with self._lock:
            self._check_open()
            timing = Timing() if self._profile else None
            if self._lib.edml_process(
                self._handle, audio.ctypes.data, self.output.ctypes.data,
                C.byref(timing) if timing is not None else None,
            ):
                raise RuntimeError(self._error())
            if timing is not None:
                self.last_timing = {name: getattr(timing, name) for name, _ in Timing._fields_}
            # The caller consumes this view before the next run overwrites it.
            return self.output

    def reset(self):
        with self._lock:
            self._check_open()
            if self._lib.edml_reset(self._handle):
                raise RuntimeError(self._error())

    def close(self):
        with self._lock:
            if self._finalizer is not None:
                self._finalizer()
