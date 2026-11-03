"""No-return samples are usable absence observations, not fabricated distances."""
import pytest
from windows.core.sensor_protocol import tof_no_target, control_sensor_ok, validate_telemetry
from windows.core.sensor_manager import SensorManager
from windows.core.tof_presence import TofPresence
from windows.core.settings import Settings
from windows.core.automation import AutomationRuntime
from windows.core.diagnostics import Diagnostics
from windows.core.simulation import SimulatedPower, SimulatedGuard
from windows.tests.test_tof import packet


def missing(seq=1, **changes):
    value = packet(seq)
    value.update(tof_ok=False, sensor_ok=False, distance_mm=None,
                 tof_raw_status=4, tof_sample_age_ms=30, tof_error="ESP_OK")
    value.update(changes)
    return value


@pytest.mark.parametrize("change", [{"tof_raw_status": 3}, {"tof_raw_status": 5},
    {"tof_raw_status": 6}, {"tof_raw_status": 7}, {"tof_raw_status": 9},
    {"tof_raw_status": True}, {"tof_error": "ESP_ERR_TIMEOUT"}, {"tof_error": None},
    {"tof_sample_age_ms": 500}, {"tof_sample_age_ms": -1}, {"tof_sample_age_ms": None},
    {"tof_sample_age_ms": True}, {"tof_sample_age_ms": 1.5}, {"distance_mm": 2000}, {"tof_ok": True}])
def test_only_fresh_signal_failure_with_successful_io_is_no_target(change):
    assert not tof_no_target(missing(**change))


def test_no_target_keeps_raw_failure_flags_and_light_fault_still_blocks_control():
    value = missing(tof_sample_age_ms=499)
    assert validate_telemetry(value) is value
    assert tof_no_target(value) and control_sensor_ok(value)
    assert value["sensor_ok"] is False and value["tof_ok"] is False and value["distance_mm"] is None
    value.update(light_ok=False, lux=None)
    validate_telemetry(value)
    assert not control_sensor_ok(value)
    del value["tof_error"]
    assert not tof_no_target(value)


def test_no_target_preserves_stabilization_and_advanced_absence_dwell():
    manager = SensorManager(stabilization_seconds=1, tof_presence=TofPresence(20, 100, 5, 1))
    manager.ingest(packet(1), 0)
    manager.ingest(packet(2), 1)
    assert manager.ready(1)
    first = manager.ingest(missing(3), 1.2)
    assert first.healthy_since == 0 and first.packet["presence"] is True
    end = manager.ingest(missing(4), 2.3)
    assert end.packet["presence"] is False and end.packet["tof_no_target"]
    assert end.packet["distance_cm"] is None and end.packet["sensor_ok"] is False
    assert manager.ready(2.3) and "대상 미감지" in end.reason
    assert not manager.ready(6)


def test_no_target_cold_start_still_requires_stabilization():
    manager = SensorManager(stabilization_seconds=5)
    for i in range(6):
        manager.ingest(missing(i + 1), i)
        assert manager.ready(i) is (i == 5)


def runtime(tmp_path):
    now = [0]
    model = AutomationRuntime(Settings(ui_mode="simple", auto_presence=True, absence_seconds=5,
                                       tof_max_distance_cm=100), Diagnostics(tmp_path), SimulatedPower(),
                              clock=lambda: now[0], guard_factory=SimulatedGuard,
                              input_provider=lambda: 0, locked_provider=lambda: False)
    return model, now


def ingest(model, now, value, time):
    now[0] = time
    model.ingest({"packet": value, "received_at": time})
    return model.tick(time, 0, False, False)


def test_seated_to_no_target_off_after_wait_and_redetection_wakes(tmp_path):
    model, now = runtime(tmp_path)
    for t in range(6):
        assert not ingest(model, now, packet(t + 1), t)
    for t in range(6, 17):
        actions = ingest(model, now, missing(t + 1), t)
        if t == 6:
            assert model.presence.absent_since == 6
        if t == 11:
            assert model.presence.countdown_until == 16
        if t < 16:
            assert not actions
        else:
            assert actions[0]["kind"] == "off"
            assert model.perform(actions[0])["ok"]
    assert model.presence.owns_off
    actions = ingest(model, now, packet(18), 17)
    assert actions[0]["kind"] == "wake" and model.perform(actions[0])["ok"]
    assert not model.presence.owns_off and model.guard is None


@pytest.mark.parametrize("fault", ["io", "stale_sample", "hardware", "disconnect", "stream_stale"])
def test_faults_cancel_no_target_countdown_and_never_turn_off(tmp_path, fault):
    model, now = runtime(tmp_path)
    for t in range(12):
        assert not ingest(model, now, missing(t + 1), t)
    assert model.presence.countdown_until == 15
    if fault == "disconnect":
        model.sensor_status({"connected": False, "message": "USB disconnected"})
    elif fault != "stream_stale":
        change = {"io": {"tof_error": "ESP_ERR_INVALID_RESPONSE"},
                  "stale_sample": {"tof_sample_age_ms": 500}, "hardware": {"tof_raw_status": 3}}[fault]
        ingest(model, now, missing(13, **change), 12)
    for t in range(15, 30):
        now[0] = t
        assert not model.tick(t, 0, False, False)
    assert model.presence.countdown_until is None
