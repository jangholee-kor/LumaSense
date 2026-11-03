import pytest

from windows.core.brightness_profiles import StepBrightness, default_brightness_profiles, validate_profiles
from windows.core.brightness_controller import BrightnessController
from windows.core.settings import Settings
from windows.tests.test_automation_runtime import make_runtime, sample


def profile(**changes):
    return {**default_brightness_profiles()[0], **changes}


@pytest.mark.parametrize("lux,brightness", [(0, 2), (99.99, 2), (100, 30), (299.99, 30), (300, 55), (65535, 55)])
def test_threshold_is_inclusive_and_exact(lux, brightness):
    assert StepBrightness(profile()).observe(lux, 0) == brightness


def test_step_dwell_and_hysteresis_are_applied_to_lux_in_both_directions():
    model = StepBrightness(profile(hysteresis_lux=5))
    assert model.observe(10, 0) == 2
    assert model.observe(300, 1) == 2
    assert model.observe(300, 2) == 55
    assert model.observe(296, 3) == 55
    assert model.observe(294, 4) == 55
    assert model.observe(296, 5) == 55
    assert model.observe(294, 6) == 55
    assert model.observe(294, 7) == 30
    assert model.observe(94, 8) == 30
    assert model.observe(94, 9) == 2


def test_multistep_drop_preserves_last_crossed_boundary_hysteresis():
    model = StepBrightness(profile(points=[[0, 2], [100, 30], [300, 55], [700, 80]], hysteresis_lux=5, hold_seconds=0))
    assert model.observe(800, 0) == 80
    assert model.observe(296, 1) == 55
    assert model.observe(294, 2) == 30


def test_profile_outputs_exact_values_with_rate_limit_and_manual_pause():
    settings = Settings(brightness_mode="steps", brightness_min=50, brightness_deadband=10,
                        brightness_profiles=[profile(points=[[0, 2], [100, 3]], hold_seconds=0)],
                        manual_pause_seconds=10)
    model = BrightnessController(settings)
    model.seed(80, 0)
    model.observe(5, 0)
    assert model.propose(0) == 2
    model.sent(2, 0)
    model.observe(100, .2)
    assert model.propose(.2) is None
    assert model.propose(1) == 3
    model.manual(40, 2)
    assert model.propose(11.9) is None
    assert model.propose(12) == 3


def test_profiles_round_trip_and_existing_settings_are_preserved(tmp_path):
    path = tmp_path / "settings.json"
    night = profile(name="야간", points=[[0, 1], [50, 10]])
    Settings(brightness_mode="steps", brightness_profile="야간", brightness_profiles=[profile(), night]).save(path)
    saved = Settings.load(path)
    assert saved.brightness_profile == "야간" and saved.brightness_profiles[1] == night
    path.write_text('{"brightness_mode":"two_level","light_threshold_lux":259.2}', encoding="utf-8")
    old = Settings.load(path)
    assert old.brightness_mode == "two_level" and old.light_threshold_lux == 259.2
    assert old.brightness_profiles[0]["name"] == "기본"


@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": " 앞공백"}, {"name": "a\nb"}, {"points": []},
    {"points": [[1, 2]]}, {"points": [[0, 2], [0, 3]]}, {"points": [[0, True]]},
    {"points": [[0, 2.5]]}, {"points": [[0, 101]]}, {"points": [[0, 2], [float("nan"), 5]]},
    {"hysteresis_lux": 100}, {"hold_seconds": -1}, {"hold_seconds": float("inf")},
])
def test_invalid_profiles_rejected(bad):
    with pytest.raises(ValueError):
        Settings(brightness_profiles=[profile(**bad)]).validate()


def test_duplicate_or_missing_profile_rejected_and_defaults_not_shared():
    with pytest.raises(ValueError):
        validate_profiles([profile(), profile()], "기본")
    with pytest.raises(ValueError):
        validate_profiles([profile()], "없음")
    settings = Settings()
    changed = Settings()
    changed.brightness_profiles[0]["points"][0][1] = 50
    assert settings.brightness_profiles[0]["points"][0][1] == 2


def test_sensor_error_and_reconnect_discard_pending_profile_transition(tmp_path):
    runtime, now, calls = make_runtime(tmp_path, auto_brightness=True, brightness_mode="steps", monitor_id="monitor")
    runtime.ingest(sample(1, 0, True, lux=10))
    runtime.ingest(sample(2, .5, True, lux=300))
    now[0] = 1
    runtime.ingest(sample(3, 1, True, light_ok=False, lux=None, sensor_ok=False))
    assert runtime.brightness.target is None
    assert not runtime.tick(1, 1000, False, True)
    runtime.sensor_status({"connected": False, "message": "test disconnect"})
    assert runtime.brightness.target is None and not calls


def test_controller_copies_profile_before_editor_changes():
    settings = Settings(brightness_mode="steps")
    model = BrightnessController(settings)
    settings.brightness_profiles[0]["points"][0][1] = 90
    assert model.observe(0, 0) == 2


def test_malformed_sensor_packet_clears_step_target(tmp_path):
    runtime, now, calls = make_runtime(tmp_path, brightness_mode="steps")
    runtime.ingest(sample(1, 0, True, lux=10))
    assert runtime.brightness.target == 2
    with pytest.raises(ValueError):
        runtime.ingest(sample(2, 1, True, lux=None))
    assert runtime.brightness.target is None and not calls
