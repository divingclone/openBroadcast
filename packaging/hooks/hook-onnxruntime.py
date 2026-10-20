"""Pinned DirectML Python runtime: native inference is in the pybind module.

onnxruntime.dll is the separate C API library, not a dependency of this wheel's
Python module. DirectML.dll is a delay-loaded dependency and must be collected.
Keep licenses; avoid collect_all(), which also bundles offline developer tools.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

binaries = collect_dynamic_libs("onnxruntime", search_patterns=["DirectML.dll"])
datas = collect_data_files(
    "onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt", "Privacy.md"]
)
