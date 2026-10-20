"""COM lifetime for Windows audio workers (WASAPI uses COM per thread)."""
from contextlib import contextmanager
import sys


@contextmanager
def audio_thread(ole32=None):
    if sys.platform != "win32":
        yield
        return
    if ole32 is None:
        import ctypes
        ole32 = ctypes.WinDLL("ole32")
        ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        ole32.CoInitializeEx.restype = ctypes.c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
    result = ole32.CoInitializeEx(None, 0) & 0xffffffff  # COINIT_MULTITHREADED
    # An existing STA is already initialized; don't undo someone else's COM.
    if result not in (0, 1, 0x80010106):  # S_OK, S_FALSE, RPC_E_CHANGED_MODE
        raise OSError(f"Windows 音频线程初始化失败 (COM 0x{result:08X})")
    try:
        yield
    finally:
        if result in (0, 1):
            ole32.CoUninitialize()
