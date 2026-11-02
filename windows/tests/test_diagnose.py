from types import SimpleNamespace

import pytest

from windows.core.brightness import Monitor
from windows.core.diagnostics import Diagnostics
from windows.diagnose import brightness_sweep


def test_sweep_restores_after_failure(tmp_path):
    calls = []
    monitor = Monitor("full-id", "27B2H2", 24, "ddcci")
    def change(identifier, level):
        calls.append(level)
        if level == 50:
            raise OSError("DDC disconnected")
    backend = SimpleNamespace(set_brightness=change, monitors=lambda: [monitor])
    with pytest.raises(OSError):
        brightness_sweep(backend, monitor, Diagnostics(tmp_path), lambda seconds: None)
    assert calls == [20, 50, 24]


def test_no_sweep_without_restore_value(tmp_path):
    with pytest.raises(ValueError):
        brightness_sweep(None, Monitor("id", "panel", None, "ddcci"), Diagnostics(tmp_path))
