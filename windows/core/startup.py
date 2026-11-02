"""Per-user opt-in login startup; no admin rights or scheduled tasks."""
from pathlib import Path
import subprocess
import sys
import winreg


KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
NAME = "SmartMonitorController"


def command():
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--minimized"]
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        args = [str(pythonw if pythonw.exists() else Path(sys.executable)),
                str(Path(__file__).resolve().parents[2] / "launch.py"), "--minimized"]
    return subprocess.list2cmdline(args)


def set_enabled(enabled):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(key, NAME)
            except FileNotFoundError:
                pass
