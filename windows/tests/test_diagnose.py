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


@pytest.mark.parametrize("brightness", [None, 56.5, float("nan"), float("inf")])
def test_no_sweep_without_restore_value(tmp_path, brightness):
    with pytest.raises(ValueError):
        brightness_sweep(None, Monitor("id", "panel", brightness, "ddcci"), Diagnostics(tmp_path))


@pytest.mark.parametrize("reported", [56, 56.00000000000001, 55.99999999999999])
def test_sweep_restores_integer_despite_cli_float_noise(tmp_path, reported):
    calls = []
    initial = Monitor("full-id", "32M2N8900", 56.00000000000001, "ddcci")
    backend = SimpleNamespace(
        set_brightness=lambda identifier, level: calls.append((identifier, level)),
        monitors=lambda: [Monitor(initial.identifier, initial.name, reported, initial.kind)],
    )
    brightness_sweep(backend, initial, Diagnostics(tmp_path), lambda seconds: None)
    assert calls == [("full-id", level) for level in (20, 50, 80, 56)]
    assert all(type(level) is int for _, level in calls)


@pytest.mark.parametrize("reported", [55, 56.1, None, float("nan")])
def test_sweep_rejects_restore_mismatch(tmp_path, reported):
    initial = Monitor("full-id", "32M2N8900", 56, "ddcci")
    backend = SimpleNamespace(
        set_brightness=lambda identifier, level: None,
        monitors=lambda: [Monitor(initial.identifier, initial.name, reported, initial.kind)],
    )
    with pytest.raises(RuntimeError, match="수동 확인"):
        brightness_sweep(backend, initial, Diagnostics(tmp_path), lambda seconds: None)
