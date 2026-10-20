"""Opt-in, per-user login startup. Never installs a system service."""

from .i18n import tr
from pathlib import Path
import configparser
import os
import plistlib
import subprocess
import sys
import tempfile

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "OpenBroadcast"
AGENT_LABEL = "io.openbroadcast.desktop"


def startup_args():
    # Do not resolve Unix venv symlinks to the base interpreter.
    executable = Path(sys.executable).absolute()
    if getattr(sys, "frozen", False):
        return [str(executable), "--background"]
    if sys.platform == "win32":
        executable = executable.with_name("pythonw.exe")
        if not executable.is_file():
            raise OSError(tr('找不到 pythonw.exe，请使用 Windows Python 或便携版。'))
    return [str(executable), str(Path(__file__).resolve().with_name("run_gui.pyw")),
            "--background"]


def startup_path():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist"
    if sys.platform == "linux":
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        if not base.is_absolute():
            base = Path.home() / ".config"
        return base / "autostart" / "openbroadcast.desktop"
    raise OSError("Unsupported login startup platform")


def _desktop_exec(args):
    """Desktop Entry quoting has two escaping layers; it is not shell syntax."""
    quoted = []
    for arg in args:
        if any(c in arg for c in "\r\n\0"):
            raise OSError("Login startup paths cannot contain newlines or NUL")
        value = arg.replace("%", "%%")
        value = "".join("\\" + c if c in '\\\"`$' else c for c in value)
        quoted.append('"' + value + '"')
    return " ".join(quoted).replace("\\", "\\\\").replace("\t", "\\t")


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".openbroadcast-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def startup_command():
    command = subprocess.list2cmdline(startup_args())
    if len(command) > 260:
        raise OSError(tr('程序路径过长，无法注册开机自启；请移到更短的目录。'))
    return command


def is_enabled():
    if sys.platform != "win32":
        path = startup_path()
        try:
            if sys.platform == "darwin":
                config = plistlib.loads(path.read_bytes())
                return (isinstance(config, dict) and config.get("Label") == AGENT_LABEL
                        and config.get("RunAtLoad") is True
                        and not config.get("Disabled", False)
                        and bool(config.get("ProgramArguments")))
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(path.read_text(encoding="utf-8"))
            entry = config["Desktop Entry"]
            return (entry.get("Type") == "Application" and bool(entry.get("Exec"))
                    and not entry.getboolean("Hidden", fallback=False)
                    and entry.getboolean("X-GNOME-Autostart-enabled", fallback=True))
        except (FileNotFoundError, ValueError, KeyError, configparser.Error,
                plistlib.InvalidFileException):
            return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, kind = winreg.QueryValueEx(key, VALUE_NAME)
        return kind == winreg.REG_SZ and bool(value)
    except FileNotFoundError:
        return False


def set_enabled(enabled):
    if sys.platform != "win32":
        path = startup_path()
        if not enabled:
            path.unlink(missing_ok=True)
        elif sys.platform == "darwin":
            _atomic_write(path, plistlib.dumps({
                "Label": AGENT_LABEL, "ProgramArguments": startup_args(),
                "RunAtLoad": True, "LimitLoadToSessionType": "Aqua",
                "ProcessType": "Interactive",
            }))
        else:
            content = ("[Desktop Entry]\nType=Application\nName=OpenBroadcast\n"
                       f"Exec={_desktop_exec(startup_args())}\nTerminal=false\n"
                       "X-GNOME-Autostart-enabled=true\n")
            _atomic_write(path, content.encode("utf-8"))
        return
    import winreg
    if enabled:
        command = startup_command()
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY,
                                access=winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
    else:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
