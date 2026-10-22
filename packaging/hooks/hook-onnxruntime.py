"""Collect both Python and optional explicit-resource DirectML runtime support.

onnxruntime.dll supplies the C API used by the native audio helper.
DirectML.dll is a delay-loaded dependency and must also be collected.
Keep licenses; avoid collect_all(), which also bundles offline developer tools.
"""
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

binaries = collect_dynamic_libs("onnxruntime", search_patterns=["DirectML.dll", "onnxruntime.dll"])
datas = collect_data_files(
    "onnxruntime", includes=["LICENSE", "ThirdPartyNotices.txt", "Privacy.md"]
)
