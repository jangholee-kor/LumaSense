import json
from types import SimpleNamespace

import pytest

from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController, State
from windows.core.settings import Settings
from windows.core.watchdog import recovery_sequence


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
