import json
from types import SimpleNamespace

import pytest

from tools.sensor_cli import JsonLines, capture, select_port, validate_telemetry


def packet(**changes):
    return {"ver": 1, "type": "telemetry", "device": "smart-monitor-s3", "seq": 1, "uptime_ms": 200,
            "light_ok": True, "radar_ok": True, "sensor_ok": True, "lux": 125.5,
            "presence": True, "moving": False, "stationary": True, "distance_cm": 67, **changes}


def test_fragmented_utf8_and_resynchronization():
    decoder = JsonLines(limit=256)
    payload = (json.dumps({"type": "ack", "message": "센서"}, ensure_ascii=False) + "\n").encode()
    result = []
    for byte in payload:
        result += decoder.feed(bytes([byte]))
    assert result[0]["message"] == "센서"
    assert decoder.feed(b'x' * 1000 + b'\n{bad}\n{"ok":true}\n') == [{"ok": True}]
    assert decoder.invalid == 2 and len(decoder.buffer) == 0


@pytest.mark.parametrize("changes", [
    {"lux": float("nan")}, {"seq": True}, {"seq": -1}, {"sensor_ok": False},
    {"presence": False}, {"radar_ok": False, "sensor_ok": False},
    {"light_ok": False, "sensor_ok": False}, {"distance_cm": "67"}, {"ver": 2}, {"ver": True}
])
def test_invalid_sensor_data_rejected(changes):
    with pytest.raises(ValueError):
        validate_telemetry(packet(**changes))


def test_errors_are_null_not_false_absence():
    good = packet(light_ok=False, radar_ok=False, sensor_ok=False, lux=None,
                  presence=None, moving=None, stationary=None, distance_cm=None)
    assert validate_telemetry(good)["presence"] is None


def test_led_driver_failure_does_not_invalidate_healthy_sensor_data():
    value = packet(firmware="0.2.1", status_led={"enabled": True, "gpio": 38, "brightness": 4,
                   "state": "present", "driver_ok": False, "error": "ESP_ERR_TIMEOUT", "requested_rgb": [0, 4, 0]})
    decoded = JsonLines().feed((json.dumps(value) + "\n").encode())[0]
    assert validate_telemetry(decoded)["sensor_ok"]
    assert decoded["status_led"]["driver_ok"] is False


def test_select_port_ambiguous_and_explicit():
    devices = [{"port": "COM3", "vid": 0x303a, "pid": 0x1001}]
    assert select_port(available=devices) == "COM3"
    with pytest.raises(ValueError):
        select_port(available=devices * 2)
    assert select_port("COM7", available=devices * 2) == "COM7"


def test_capture_stall_is_not_a_pass(tmp_path):
    device = SimpleNamespace(read=lambda deadline: None, decoder=SimpleNamespace(invalid=0))
    with pytest.raises(TimeoutError):
        capture(device, .05, tmp_path / "capture", stale_seconds=.001)
    summary = json.loads((tmp_path / "capture/summary.json").read_text(encoding="utf-8"))
    assert not summary["sensor_stream_pass"]
    assert "transport_error" in summary
    assert not summary["ten_minute_stream_pass"]


def test_capture_preserves_sensor_error_and_gaps(tmp_path):
    frames = [packet(), packet(seq=3), packet(seq=4, light_ok=False, lux=None, sensor_ok=False)]
    device = SimpleNamespace(read=lambda deadline: frames.pop(0) if frames else None, decoder=SimpleNamespace(invalid=0))
    summary = capture(device, .01, tmp_path / "capture")
    assert summary["telemetry"] == 3 and summary["sensor_errors"] == 1
    assert summary["sequence_gaps"] == 1 and not summary["sensor_stream_pass"]


def test_short_healthy_capture_is_not_ten_minute_verification(tmp_path):
    frames = [packet()]
    device = SimpleNamespace(read=lambda deadline: frames.pop(0) if frames else None, decoder=SimpleNamespace(invalid=0))
    summary = capture(device, .01, tmp_path / "capture")
    assert summary["sensor_stream_pass"]
    assert not summary["ten_minute_stream_pass"]
