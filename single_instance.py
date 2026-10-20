"""One GUI per Windows user/session, with activation of a hidden first window."""
from __future__ import annotations

import hashlib
from pathlib import Path
import os
import sys


class SingleInstance:
    def __init__(self, name=None):
        identity = hashlib.sha256(str(Path.home()).casefold().encode("utf-8")).hexdigest()[:24]
        self.name = name or rf"Local\OpenBroadcast.{identity}"
        self._mutex = self._event = self._mapping = None
        self._owned = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def acquire(self):
        if sys.platform != "win32":
            return True
        if self._mutex is not None:
            raise RuntimeError("SingleInstance.acquire() must only be called once")
        import ctypes as c
        from ctypes import wintypes as w
        import mmap

        self._api = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateMutexW": ([c.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE),
            "CreateEventW": ([c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "SetEvent": ([w.HANDLE], w.BOOL),
            "ReleaseMutex": ([w.HANDLE], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for function, (args, result) in signatures.items():
            method = getattr(self._api, function)
            method.argtypes, method.restype = args, result
        self._mutex = self._api.CreateMutexW(None, False, self.name + ".mutex")
        if not self._mutex:
            raise c.WinError(c.get_last_error())
        # Create/open these before acquiring, so simultaneous launches cannot
        # lose an activation request while the first GUI is still loading.
        self._event = self._api.CreateEventW(None, False, False, self.name + ".activate")
        if not self._event:
            raise c.WinError(c.get_last_error())
        self._mapping = mmap.mmap(-1, 4, tagname=self.name + ".owner")
        state = self._api.WaitForSingleObject(self._mutex, 0)
        if state in (0, 0x80):  # WAIT_OBJECT_0 / WAIT_ABANDONED after a crash
            self._owned = True
            self._mapping[:4] = os.getpid().to_bytes(4, "little")
            return True
        if state != 0x102:  # WAIT_TIMEOUT: a live instance owns the mutex
            raise c.WinError(c.get_last_error())

        owner = int.from_bytes(self._mapping[:4], "little")
        if owner:
            user32 = c.WinDLL("user32", use_last_error=True)
            user32.AllowSetForegroundWindow.argtypes = [w.DWORD]
            user32.AllowSetForegroundWindow.restype = w.BOOL
            # A user-launched process can grant the existing GUI foreground
            # permission; no global focus/desktop settings are changed.
            user32.AllowSetForegroundWindow(owner)
        if not self._api.SetEvent(self._event):
            raise c.WinError(c.get_last_error())
        return False

    def activation_requested(self):
        if not self._owned:
            return False
        state = self._api.WaitForSingleObject(self._event, 0)
        if state == 0:
            return True
        if state != 0x102:
            import ctypes
            raise ctypes.WinError(ctypes.get_last_error())
        return False

    def close(self):
        if self._mapping is not None:
            self._mapping.close()
            self._mapping = None
        if self._event:
            self._api.CloseHandle(self._event)
            self._event = None
        if self._mutex:
            if self._owned:
                self._api.ReleaseMutex(self._mutex)
                self._owned = False
            self._api.CloseHandle(self._mutex)
            self._mutex = None
