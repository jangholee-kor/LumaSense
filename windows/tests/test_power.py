import json
from types import SimpleNamespace

import pytest

from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController, State
from windows.core.settings import Settings
from windows.core.watchdog import recovery_sequence, recovery_window_seconds, validate_timing


def test_countdown_cancel_and_duplicate(tmp_path):
    calls = []
    now = [0]
    controller = DisplayController(SimpleNamespace(off=lambda: calls.append("off")), Diagnostics(tmp_path), lambda: now[0],
                                   lambda *args: calls.append("armed"))
    controller.start()
    with pytest.raises(RuntimeError):
        controller.start()
    with pytest.raises(RuntimeError):
        controller.execute("monitor_power", 10, False)
    assert controller.cancel()
    assert controller.state == State.IDLE
    assert not calls
    controller.start()
    now[0] = 5
    controller.execute("monitor_power", 10, False)
    assert calls == ["armed", "off"]
    assert not controller.cancel()
    with pytest.raises(RuntimeError):
        controller.execute("monitor_power", 10, False)


def test_no_off_without_watchdog(tmp_path):
    calls = []
    def fail(*args):
        raise RuntimeError("watchdog unavailable")
    controller = DisplayController(SimpleNamespace(off=lambda: calls.append("off")), Diagnostics(tmp_path), lambda: 0, fail)
    controller.start()
    controller.clock = lambda: 5
    with pytest.raises(RuntimeError):
        controller.execute("monitor_power", 10, False)
    assert not calls


def test_recovery_continues_on_failure_without_mouse(tmp_path):
    calls = []
    def wake(method, allow):
        calls.append(method)
        if method == "monitor_power":
            raise OSError("timeout")
        return {"accepted": True}
    recovery_sequence(SimpleNamespace(wake=wake), Diagnostics(tmp_path), "test", "monitor_power", False, lambda s: None)
    assert calls == ["monitor_power", "execution_state"]
    logs = [json.loads(line) for line in next(tmp_path.glob("events-*.jsonl")).read_text(encoding="utf-8").splitlines()]
    assert any(event["event"] == "wake_error" for event in logs)
    assert logs[-1]["physical_result"] == "unverified"


def test_mouse_primary_and_fallback_order(tmp_path):
    calls = []
    power = SimpleNamespace(wake=lambda method, allow: calls.append((method, allow)))
    recovery_sequence(power, Diagnostics(tmp_path), "test", "mouse_move", True, lambda s: None)
    assert calls == [("mouse_move", True), ("monitor_power", True), ("execution_state", True)]


def test_settings_round_trip_and_invalid(tmp_path):
    path = tmp_path / "settings.json"
    Settings(monitor_id="full-id", recovery_seconds=15).save(path)
    assert Settings.load(path).monitor_id == "full-id"
    path.write_text('{"recovery_seconds": -1}', encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)


@pytest.mark.parametrize("interval", [5, 30, 60])
def test_fallback_waits_configured_interval(tmp_path, interval):
    timeline = []
    power = SimpleNamespace(wake=lambda method, allow: timeline.append(method))
    recovery_sequence(power, Diagnostics(tmp_path), "interval-test", "monitor_power", True,
                      lambda seconds: timeline.append(seconds), fallback_seconds=interval)
    assert timeline == ["monitor_power", interval, "execution_state", interval, "mouse_move"]
    assert recovery_window_seconds("monitor_power", 5, True, interval) == 5 + 2 * interval + 15


@pytest.mark.parametrize("bad", [0, 4, 61, 30.0, "30", True])
def test_invalid_interval(bad):
    with pytest.raises(ValueError):
        validate_timing(5, bad)


def test_settings_migration_and_interval_validation(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"monitor_id":"old-id", "recovery_seconds":5}', encoding="utf-8")
    assert Settings.load(path).fallback_seconds == 30
    settings = Settings.load(path)
    settings.fallback_seconds = 60
    settings.save(path)
    assert Settings.load(path).fallback_seconds == 60
    path.write_text('{"fallback_seconds":61}', encoding="utf-8")
    with pytest.raises(ValueError):
        Settings.load(path)


def test_controller_forwards_interval_and_arms_before_off(tmp_path):
    calls = []
    controller = DisplayController(SimpleNamespace(off=lambda: calls.append("off")), Diagnostics(tmp_path),
                                   lambda: 0, lambda *args: calls.append(args[-1]))
    controller.start()
    controller.clock = lambda: 5
    controller.execute("monitor_power", 5, False, 45)
    assert calls == [45, "off"]
    assert recovery_window_seconds("monitor_power", 5, False, 45) == 65
