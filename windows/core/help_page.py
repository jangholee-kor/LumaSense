"""Locate the offline guide in source checkouts and PyInstaller bundles."""
from pathlib import Path


def help_path():
    return Path(__file__).resolve().parents[1] / "resources" / "help.html"
