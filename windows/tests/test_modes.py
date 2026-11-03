import json
from windows.core.settings import Settings
from windows.core.automation import AutomationRuntime
from windows.core.diagnostics import Diagnostics
from windows.core.simulation import SimulatedPower, SimulatedGuard
from windows.tests.test_tof import packet


def test_new_install_simple_old_settings_advanced_and_mode_roundtrip(tmp_path):
    path = tmp_path / "settings.json"
    assert Settings.load(path).ui_mode == "simple"
    path.write_text(json.dumps({"brightness_mode": "steps"}), encoding="utf-8")
    old = Settings.load(path)
    assert old.ui_mode == "advanced" and old.for_control().brightness_mode == "steps"
    old.ui_mode = "simple"
    old.save(path)
    assert Settings.load(path).ui_mode == "simple"
    assert Settings.load(path).brightness_mode == "steps"


def test_simple_defaults_preserve_advanced_settings_and_public_controls():
    raw = Settings(ui_mode="simple", brightness_mode="steps", tof_hold_seconds=3,
                   tof_hysteresis_cm=20, use_recent_input=True, recent_input_seconds=90,
                   absence_seconds=7, tof_max_distance_cm=100, light_threshold_lux=150,
                   light_on_brightness=35, light_off_brightness=2, light_switch_seconds=4)
    active = raw.for_control()
    assert active.brightness_mode == "two_level" and not active.use_recent_input
    assert active.tof_hold_seconds == 0 and active.tof_hysteresis_cm == 0
    assert active.absence_seconds == 7 and active.tof_max_distance_cm == 100
    assert active.light_threshold_lux == 150 and active.light_on_brightness == 35
    assert active.light_switch_seconds == 1
    assert raw.use_recent_input and raw.tof_hold_seconds == 3 and raw.brightness_mode == "steps"
    raw.ui_mode = "advanced"
    assert raw.for_control() is raw


def test_simple_raw_distance_exit_starts_absence_without_input_or_tof_delay(tmp_path):
    now = [0.0]
    raw = Settings(ui_mode="simple", auto_presence=True, absence_seconds=5,
                   tof_max_distance_cm=100, tof_hold_seconds=3, use_recent_input=True)
    runtime = AutomationRuntime(raw, Diagnostics(tmp_path), SimulatedPower(),
                                clock=lambda: now[0], guard_factory=SimulatedGuard)
    for index in range(81):
        now[0] = index / 5
        value = packet(index + 1)
        value["distance_mm"] = 600 if index < 30 or index >= 80 else 1010
        runtime.ingest({"packet": value, "received_at": now[0]})
        actions = runtime.tick(now[0], 0, False, False)
        if index == 30:
            assert runtime.presence.absent_since == 6
        if index == 55:
            assert runtime.presence.countdown_until == 16
        if index < 80:
            assert not actions
        else:
            assert runtime.presence.countdown_until is None
    # A fresh continuous departure requests off after exactly 5 + 5 seconds.
    for index in range(81, 132):
        now[0] = index / 5
        value = packet(index + 1); value["distance_mm"] = 1980
        runtime.ingest({"packet": value, "received_at": now[0]})
        actions = runtime.tick(now[0], 0, False, False)
        if index < 131:
            assert not actions
        else:
            assert actions[0]["kind"] == "off"
