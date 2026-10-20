"""This portable distribution targets Windows x64 only."""
from pathlib import Path
from PyInstaller.utils.hooks import get_module_file_attribute

root = Path(get_module_file_attribute("sounddevice")).parent
folder = root / "_sounddevice_data" / "portaudio-binaries"
destination = "_sounddevice_data/portaudio-binaries"
# Retain ASIO too: sounddevice selects it when SD_ENABLE_ASIO is set.
binaries = [(str(folder / name), destination) for name in (
    "libportaudio64bit.dll", "libportaudio64bit-asio.dll"
)]
datas = [(str(folder / "README.md"), destination)]
