import pytest

from windows.core.sensor_protocol import validate_telemetry
from windows.core.sensor_manager import SensorManager
from windows.core.tof_presence import TofPresence
from windows.core.settings import Settings
from windows.core.presence_controller import PresenceController


def packet(seq=1, **changes):
    return dict(ver=2, type="telemetry", device="smart-monitor-s3", presence_sensor="vl53l1x",
                boot_id="0123456789abcdef", seq=seq, uptime_ms=seq * 200,
                light_ok=True, tof_ok=True, sensor_ok=True, lux=123,
                distance_mm=600, tof_raw_status=9, tof_sample_age_ms=30, **changes)


@pytest.mark.parametrize("change", [{"tof_sample_age_ms": 500}, {"distance_mm": None},
    {"distance_mm": 4001}, {"tof_raw_status": 4}, {"boot_id": ""},
    {"tof_ok": False, "sensor_ok": False}, {"sensor_ok": False}])
def test_tof_invalid_or_stale_ranges_rejected(change):
    value = packet()
    value.update(change)
    with pytest.raises(ValueError):
        validate_telemetry(value)


def test_distance_window_hysteresis_and_dwell():
    model = TofPresence(20, 100, 5, 1)
    assert model.observe(600, 0) is True
    assert model.observe(1040, 1) is True
    assert model.observe(1100, 2) is True
    assert model.observe(1100, 3) is False
    assert model.observe(1010, 4) is False
    assert model.observe(600, 5) is False
    assert model.observe(600, 6) is True


def test_tof_errors_and_restart_clear_presence_and_stabilization():
    model = SensorManager(stabilization_seconds=1)
    model.ingest(packet(), 0)
    model.ingest(packet(2), 1)
    assert model.ready(1) and model.packet["presence"] is True
    assert model.packet["moving"] is None and model.packet["distance_cm"] == 60
    error = packet(3)
    error.update(tof_ok=False, sensor_ok=False, distance_mm=None, tof_raw_status=4)
    assert model.ingest(error, 1.2).packet["presence"] is None
    assert not model.ready(1.2)
    value = packet(4)
    value.update(boot_id="abcdef0123456789")
    snap = model.ingest(value, 2)
    assert snap.generation == 1 and not model.ready(2)
    assert not model.snapshot(6).valid


def test_tof_settings_do_not_break_legacy_distance_limit():
    Settings(max_distance_cm=10).validate()
    with pytest.raises(ValueError):
        Settings(tof_min_distance_cm=150, tof_max_distance_cm=100).validate()


def test_tof_absence_countdown_cancels_on_invalid_range_and_wakes_owned_display():
    settings = Settings(absence_seconds=5, stabilization_seconds=1, use_recent_input=False)
    sensors = SensorManager(stabilization_seconds=1)
    presence = PresenceController(settings)
    for i in range(8):
        value = packet(i + 1)
        value["distance_mm"] = 2500
        snap = sensors.ingest(value, i)
        assert presence.tick(i, snap, sensors.ready(i), enabled=True) is None
    assert presence.countdown_until is not None
    invalid = packet(9)
    invalid.update(tof_ok=False, sensor_ok=False, distance_mm=None)
    snap = sensors.ingest(invalid, 8)
    assert presence.tick(8, snap, sensors.ready(8), enabled=True) is None
    assert presence.countdown_until is None
    presence.completed("off", True, 9)
    assert presence.tick(9, snap, False, enabled=True) == "wake"
