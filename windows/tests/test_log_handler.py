import json
import logging

from windows.core.diagnostics import Diagnostics
from windows.core.log_handler import ReportingRotatingFileHandler
from windows.core.serial_manager import SerialManager
from windows.tests.test_serial_manager import FakeSerial, packet


def storage_events(root):
    return [json.loads(line) for p in root.glob("events-*.jsonl")
            for line in p.read_text(encoding="utf-8").splitlines()
            if json.loads(line)["event"] == "log_storage_error"]


def test_failed_sensor_rotation_preserves_packets_and_reports_once(tmp_path, monkeypatch):
    diagnostics = Diagnostics(tmp_path)
    received = []
    device = FakeSerial()
    manager = SerialManager(diagnostics, received.append, lambda value: None,
                            port="test", factory=lambda **kw: device, enumerator=lambda: [], clock=lambda: 0)
    manager.handler.maxBytes = 1
    def locked_rotation():
        if manager.handler.stream:
            manager.handler.stream.close()
            manager.handler.stream = None
        raise PermissionError("Windows sharing violation")
    monkeypatch.setattr(manager.handler, "doRollover", locked_rotation)
    try:
        for seq in (1, 2):
            device.add(packet(seq=seq, uptime=seq * 200))
            manager.service_once()
        assert len(received) == 2 and manager.confirmed
        lines = (tmp_path / "sensor.jsonl").read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["packet"]["seq"] for line in lines] == [1, 2]
        errors = storage_events(tmp_path)
        assert len(errors) == 1 and errors[0]["file"] == "sensor.jsonl"
        assert "sensor.jsonl" in diagnostics.storage_error_message
    finally:
        manager._close("test end")
        manager.handler.close()


def test_app_rotation_failure_reports_without_recursive_logging(tmp_path, monkeypatch):
    diagnostics = Diagnostics(tmp_path)
    handler, = diagnostics.logger.handlers
    handler.maxBytes = 1
    def locked_rotation():
        raise PermissionError("app.log locked")
    monkeypatch.setattr(handler, "doRollover", locked_rotation)
    diagnostics.event("first")
    diagnostics.event("second")
    assert len(storage_events(tmp_path)) == 1
    assert len((tmp_path / "app.log").read_text(encoding="utf-8").splitlines()) == 2
    handler.close()


def test_write_failure_is_visible_even_when_diagnostic_directory_fails(tmp_path, monkeypatch):
    diagnostics = Diagnostics(tmp_path)
    path = tmp_path / "sensor.jsonl"
    handler = ReportingRotatingFileHandler(path, delay=True, encoding="utf-8", on_error=diagnostics.storage_error)
    def unwritable(*args, **kwargs):
        raise PermissionError("disk unavailable")
    monkeypatch.setattr(handler, "_open", unwritable)
    monkeypatch.setattr(diagnostics, "_append", unwritable)
    handler.emit(logging.makeLogRecord({"msg": "packet"}))
    assert "disk unavailable" in diagnostics.storage_error_message
    diagnostics.event("still_running")
    assert "disk unavailable" in diagnostics.storage_error_message
    handler.close()
