"""POSIX advisory lock and durable activation counter, scoped to a GUI session.

Lock files must not be unlinked: removing a locked inode would allow two owners.
A separate counter lock preserves requests even while the first GUI is loading.
No sockets, ports, PID reuse checks, signals or background polling threads.
"""
import hashlib
import os
from pathlib import Path
import stat
import sys


class PosixInstance:
    def __init__(self, name, directory=None):
        session = ""
        if sys.platform == "linux":
            session = os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY") or "desktop"
        identity = hashlib.sha256((name + "\0" + session).encode()).hexdigest()[:24]
        # Login agents and shells can have different TMPDIR environments.
        # A fixed per-user location makes them discover the same owner.
        base = (Path.home() / "Library" / "Caches" if sys.platform == "darwin"
                else Path.home() / ".cache")
        self.directory = Path(directory) if directory else base / "OpenBroadcast" / "instances"
        self.lock_path = self.directory / (identity + ".lock")
        self.request_path = self.directory / (identity + ".request")
        self.owner = False
        self.lock_fd = self.request_fd = None
        self.seen = 0

    def _open(self, path):
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1):
            os.close(fd)
            raise OSError("Unsafe single-instance lock file")
        return fd

    def _counter(self):
        return int.from_bytes(os.pread(self.request_fd, 8, 0), "little")

    def acquire(self):
        import fcntl
        if self.lock_fd is not None:
            raise RuntimeError("SingleInstance.acquire() must only be called once")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise OSError("Single-instance directory must be private and owned by this user")
        try:
            self.request_fd = self._open(self.request_path)
            self.lock_fd = self._open(self.lock_path)
            # Hold the request lock while acquiring ownership/snapshotting:
            # a second launcher can never race a reset of the activation state.
            fcntl.flock(self.request_fd, fcntl.LOCK_EX)
            try:
                try:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.owner = True
                    self.seen = self._counter()
                    return True
                except BlockingIOError:
                    value = (self._counter() + 1) % (1 << 64)
                    os.pwrite(self.request_fd, value.to_bytes(8, "little"), 0)
                    return False
            finally:
                fcntl.flock(self.request_fd, fcntl.LOCK_UN)
        except BaseException:
            self.close()
            raise

    def activation_requested(self):
        import fcntl
        if not self.owner:
            return False
        try:
            fcntl.flock(self.request_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return False  # Retry on the next Tk tick; never block the UI.
        try:
            value = self._counter()
            changed = value != self.seen
            self.seen = value
            return changed
        finally:
            fcntl.flock(self.request_fd, fcntl.LOCK_UN)

    def close(self):
        for attribute in ("request_fd", "lock_fd"):
            fd = getattr(self, attribute)
            if fd is not None:
                os.close(fd)
                setattr(self, attribute, None)
        self.owner = False
