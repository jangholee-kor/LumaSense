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


def test_two_level_uses_exact_presets_below_curve_minimum_and_at_threshold():
    model = BrightnessController(Settings(brightness_mode="two_level", light_threshold_lux=100))
    model.seed(56, 0)
    assert model.observe(100, 0) == 55
    assert model.propose(0) == 55
    model.sent(55, 0)
    assert model.observe(99, .2) == 55
    assert model.observe(2, 1.3) == 2
    assert model.propose(1.3) == 2
    model.sent(2, 1.3)
    assert model.propose(2.5) is None
    model.observe(100, 3)
    assert model.observe(100, 4) == 55
    assert model.propose(4) == 55


def test_two_level_noise_manual_pause_and_one_percent_presets():
    model = BrightnessController(Settings(brightness_mode="two_level", light_on_brightness=3,
                                           light_off_brightness=2, manual_pause_seconds=10))
    model.seed(3, 0)
    model.observe(150, 0)
    for t, lux in ((.1, 99), (.5, 101), (.9, 99), (1.2, 101)):
        assert model.observe(lux, t) == 3
    model.manual(40, 2)
    model.observe(0, 3)
    model.observe(0, 4)
    assert model.propose(11.9) is None
    assert model.propose(12) == 2


def test_two_level_profile_round_trip_and_legacy_mode(tmp_path):
    path = tmp_path / "settings.json"
    Settings(brightness_mode="two_level", light_on_lux=500, light_off_lux=3.5,
             light_on_recorded_at="2026-11-02T14:00:00+00:00").save(path)
    saved = Settings.load(path)
    assert saved.brightness_mode == "two_level" and saved.light_off_brightness == 2
    assert saved.light_on_lux == 500 and saved.light_off_lux == 3.5
    path.write_text('{"curve": [[0, 10], [100, 80]]}', encoding="utf-8")
    assert Settings.load(path).brightness_mode == "curve"


@pytest.mark.parametrize("changes", [
    {"brightness_mode": "unknown"}, {"light_on_brightness": 101}, {"light_off_brightness": True},
    {"light_threshold_lux": float("nan")}, {"light_threshold_lux": -1},
    {"light_on_lux": float("inf")}, {"light_off_lux": -1}, {"light_switch_seconds": 11},
    {"light_on_recorded_at": None},
])
def test_invalid_two_level_settings(changes):
    with pytest.raises(ValueError):
        Settings(**changes).validate()


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


def test_home_timing_includes_five_second_radar_hold_and_immediate_wake():
    model = PresenceController(Settings(absence_seconds=20, recent_input_seconds=5))
    for second in range(30):
        assert model.tick(second, snapshot(second < 5), True, enabled=True, input_age=second) is None
    assert model.countdown_until == 30
    assert model.tick(30, snapshot(False), True, enabled=True, input_age=30) == "off"
    model.completed("off", True, 30)
    assert model.tick(30.2, snapshot(True), True, enabled=True, input_age=30.2) == "wake"


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
