from types import SimpleNamespace

import pytest

from windows.core.brightness_controller import BrightnessController, map_lux
from windows.core.presence_controller import PresenceController, PresenceState
from windows.core.sensor_manager import SensorManager
from windows.core.settings import Settings


def snapshot(presence, valid=True, distance=60):
    return SimpleNamespace(valid=valid, reason="test", packet={"sensor_ok": valid, "presence": presence, "distance_cm": distance})


def tick(controller, now, presence=False, **kwargs):
    return controller.tick(now, snapshot(presence), True, enabled=True, input_age=1000, **kwargs)


def test_curve_mapping_endpoints_and_interpolation():
    curve = Settings().curve
    assert map_lux(0, curve) == 10
    assert map_lux(65, curve) == 32.5
    assert map_lux(3000, curve) == 85
    with pytest.raises(ValueError):
        map_lux(float("nan"), curve)


def test_brightness_ramp_rate_limit_and_manual_resume():
    settings = Settings(brightness_interval=.5, manual_pause_seconds=10)
    model = BrightnessController(settings)
    model.seed(20, 0)
    model.observe(500, 0)
    assert model.propose(0) is None
    value = model.propose(1)
    assert 20 < value < 75
    model.sent(value, 1)
    assert model.propose(1.1) is None
    assert model.propose(2) == 75
    model.manual(40, 3)
    assert model.propose(12) is None
    assert model.propose(13) is None
    assert model.propose(14) == 58
    model.resume(14)
    assert model.propose(16) == 75


def test_small_lux_noise_does_not_churn_brightness():
    model = BrightnessController(Settings())
    model.seed(40, 0)
    model.observe(100, 0)
    for i in range(1, 100):
        model.observe(100 + i % 2, i)
        assert model.propose(i) is None
    model.observe(1000, 100)
    assert model.target == 85


def test_presence_off_only_after_continuous_absence_and_countdown():
    model = PresenceController(Settings(absence_seconds=30))
    assert tick(model, 0) is None
    assert model.state == PresenceState.MAYBE_ABSENT
    assert tick(model, 29) is None
    assert tick(model, 30) is None
    assert model.state == PresenceState.ABSENT
    assert model.countdown_until == 35
    assert tick(model, 35) == "off"
    assert tick(model, 36) is None
    model.completed("off", True, 36)
    assert tick(model, 37) is None
    assert tick(model, 38, True) == "wake"
    assert tick(model, 38.1, True) is None
    model.completed("wake", True, 38.2)
    assert tick(model, 39, True) is None


def test_brief_absence_stationary_presence_and_recent_input():
    model = PresenceController(Settings(absence_seconds=5))
    tick(model, 0)
    tick(model, 4, True)
    tick(model, 5)
    assert tick(model, 9) is None
    assert model.state == PresenceState.MAYBE_ABSENT
    model.tick(10, snapshot(False), True, enabled=True, input_age=0)
    assert model.state == PresenceState.PRESENT and model.absent_since is None
    model.tick(11, snapshot(False), True, enabled=True, input_age=None)
    assert model.state == PresenceState.PRESENT


@pytest.mark.parametrize("case", ["invalid", "startup", "disabled", "paused", "locked"])
def test_safety_gates_cancel_countdown_and_recover_owned_off(case):
    model = PresenceController(Settings(absence_seconds=5))
    tick(model, 0)
    tick(model, 5)
    values = {"enabled": True, "input_age": 1000, "paused": False, "locked": False}
    if case in values:
        values[case] = True
    if case == "disabled":
        values["enabled"] = False
    snap = snapshot(False, valid=case != "invalid")
    assert model.tick(6, snap, case != "startup", **values) is None
    assert model.countdown_until is None
    model.owns_off = True
    assert model.tick(7, snap, case != "startup", **values) == "wake"


def test_off_failure_latched_and_wake_failure_bounded():
    model = PresenceController(Settings(absence_seconds=5))
    tick(model, 0); tick(model, 5)
    assert tick(model, 10) == "off"
    model.completed("off", False, 10)
    assert tick(model, 100) is None
    assert model.state == PresenceState.SENSOR_ERROR
    tick(model, 101, True)
    model.owns_off = True
    for i in range(3):
        now = 102 + i * 2
        assert tick(model, now, True) == "wake"
        model.completed("wake", False, now)
    assert tick(model, 120, True) is None


@pytest.mark.parametrize("changes", [{"curve": [[10, 10], [1, 20]]}, {"curve": [[0, float('inf')], [1, 20]]},
                                    {"brightness_min": 90, "brightness_max": 20}, {"auto_presence": 1},
                                    {"ema_alpha": 0}, {"sensor_stale_seconds": float('nan')}])
def test_bad_automation_settings_rejected(changes):
    with pytest.raises(ValueError):
        Settings(**changes).validate()
