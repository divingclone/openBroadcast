"""Named GPU discovery using the same device order as each inference provider."""
from __future__ import annotations

from ..i18n import tr

import ctypes as C
from dataclasses import dataclass
import os
import uuid

import onnxruntime as ort

CPU = "CPUExecutionProvider"
CUDA = "CUDAExecutionProvider"
DML = "DmlExecutionProvider"


@dataclass(frozen=True)
class GpuDevice:
    name: str
    provider: str
    device_id: int
    identity: str
    available: bool = True

    @property
    def key(self):
        return {"name": self.name, "provider": self.provider, "identity": self.identity}

    @property
    def label(self):
        backend = "CUDA" if self.provider == CUDA else "DirectML"
        return f"{self.name} · {backend}" + ("" if self.available else tr('（未安装支持）'))


def _cuda_devices():
    """CUDA driver ordinals, including CUDA_VISIBLE_DEVICES ordering."""
    lib = C.WinDLL("nvcuda.dll") if os.name == "nt" else C.CDLL("libcuda.so.1")
    if lib.cuInit(0):
        return []
    count = C.c_int()
    if lib.cuDeviceGetCount(C.byref(count)):
        return []
    result = []
    for ordinal in range(count.value):
        device, name, identity = C.c_int(), C.create_string_buffer(256), (C.c_ubyte * 16)()
        if (lib.cuDeviceGet(C.byref(device), ordinal)
                or lib.cuDeviceGetName(name, len(name), device)
                or lib.cuDeviceGetUuid(C.byref(identity), device)):
            continue
        result.append(GpuDevice(name.value.decode("utf-8", errors="replace"), CUDA,
                                ordinal, "cuda:" + bytes(identity).hex()))
    return result


def _dxgi_devices():
    """Keep EnumAdapters ordinals intact when excluding software adapters."""
    if os.name != "nt":
        return []
    class Luid(C.Structure):
        _fields_ = [("low", C.c_uint32), ("high", C.c_int32)]

    class Desc(C.Structure):
        _fields_ = [("name", C.c_wchar * 128), ("vendor", C.c_uint32),
                    ("device", C.c_uint32), ("subsys", C.c_uint32),
                    ("revision", C.c_uint32), ("video_memory", C.c_size_t),
                    ("system_memory", C.c_size_t), ("shared_memory", C.c_size_t),
                    ("luid", Luid), ("flags", C.c_uint32)]

    def call(obj, slot, restype, argtypes, *args):
        vtable = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
        return C.WINFUNCTYPE(restype, C.c_void_p, *argtypes)(vtable[slot])(obj, *args)

    factory = C.c_void_p()
    iid = (C.c_ubyte * 16).from_buffer_copy(uuid.UUID("770aae78-f26f-4dba-a829-253c83d1b387").bytes_le)
    create = C.WinDLL("dxgi.dll").CreateDXGIFactory1
    create.argtypes = [C.c_void_p, C.POINTER(C.c_void_p)]
    create.restype = C.c_int32
    if create(C.byref(iid), C.byref(factory)) < 0:
        return []
    result = []
    try:
        for index in range(256):
            adapter = C.c_void_p()
            hr = call(factory, 12, C.c_int32, [C.c_uint32, C.POINTER(C.c_void_p)],
                      index, C.byref(adapter))  # IDXGIFactory1::EnumAdapters1
            if hr < 0:
                break
            try:
                desc = Desc()
                if call(adapter, 10, C.c_int32, [C.POINTER(Desc)], C.byref(desc)) >= 0:
                    if not desc.flags & 2:  # DXGI_ADAPTER_FLAG_SOFTWARE
                        identity = f"dxgi:{desc.luid.high & 0xffffffff:08x}{desc.luid.low:08x}"
                        result.append(GpuDevice(desc.name, DML, index, identity))
            finally:
                call(adapter, 2, C.c_uint32, [])  # Release
    finally:
        call(factory, 2, C.c_uint32, [])
    return result


def discover_gpus():
    providers = ort.get_available_providers()
    devices = []
    for discover, provider in ((_cuda_devices, CUDA), (_dxgi_devices, DML)):
        # DXGI also supplies hardware names in a CPU-only Windows installation.
        if provider == CUDA and provider not in providers:
            continue
        try:
            devices.extend(GpuDevice(d.name, d.provider, d.device_id, d.identity,
                                     provider in providers) for d in discover())
        except (OSError, AttributeError, ValueError):
            continue
    return devices


def selected_gpu(config, devices):
    saved = config.get("gpu")
    if saved:
        matches = [d for d in devices if d.identity == saved["identity"]
                   and d.provider == saved["provider"]]
    else:
        provider = {"cuda": CUDA, "dml": DML, "directml": DML}.get(
            config["provider"].lower(), config["provider"])
        matches = [d for d in devices if d.provider == provider
                   and d.device_id == config["device_id"]]
    return matches[0] if len(matches) == 1 else None


def inference_options(config, devices=None):
    if config["inference_mode"] == "cpu":
        return dict(provider=CPU, threads=config["threads"], device_id=0)
    devices = discover_gpus() if devices is None else devices
    device = selected_gpu(config, devices)
    if device is None:
        raise ValueError(tr('所选显卡不可用或已变更，请到设置中重新选择推理显卡。'))
    if not device.available:
        raise ValueError(tr('{value0} 尚未安装 GPU 推理支持。请切换到 CPU，或按照使用说明安装 GPU 运行库后重启程序。', value0=device.name))
    return dict(provider=device.provider, device_id=device.device_id, threads=config["threads"])
