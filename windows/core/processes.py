"""Subprocess entry points work from source and the PyInstaller bundle."""
from pathlib import Path
import sys


def helper_command(module, *args):
    if getattr(sys, "frozen", False):
        return [sys.executable, "--helper", module, *args]
    return [sys.executable, "-m", module, *args]


def process_cwd():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
