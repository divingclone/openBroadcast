"""Opt-in Windows logon startup for the current portable/source location."""

from .i18n import tr
from pathlib import Path
import subprocess
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "OpenBroadcast"


def startup_command():
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        args = [str(executable), "--background"]
    else:
        pythonw = executable.with_name("pythonw.exe")
        if not pythonw.is_file():
            raise OSError(tr('找不到 pythonw.exe，请使用 Windows Python 或便携版。'))
        args = [str(pythonw), str(Path(__file__).resolve().with_name("run_gui.pyw")),
                "--background"]
    command = subprocess.list2cmdline(args)
    if len(command) > 260:
        raise OSError(tr('程序路径过长，无法注册开机自启；请移到更短的目录。'))
    return command


def is_enabled():
    if sys.platform != "win32":
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
        raise OSError(tr('开机自启目前仅支持 Windows。'))
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
