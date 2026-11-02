import json
import threading

import pytest

from windows.core.diagnostics import Diagnostics
from windows.core.sensor_manager import SensorManager
from windows.core.serial_manager import SerialManager


def packet(seq=1, uptime=200, **changes):
    return {"ver": 1, "type": "telemetry", "device": "smart-monitor-s3", "seq": seq, "uptime_ms": uptime,
            "sensor_ok": True, "light_ok": True, "radar_ok": True, "lux": 123,
            "presence": True, "moving": False, "stationary": True, "distance_cm": 65, **changes}


class FakeSerial:
    def __init__(self, data=b"", **kwargs):
        self.data = bytearray(data)
        self.written = []
        self.closed = False
        self.broken = False

    @property
    def in_waiting(self):
        return len(self.data)

    def open(self):
        assert not self.dtr and not self.rts

    def close(self):
        self.closed = True

    def read(self, size):
        if self.broken:
            raise OSError("USB unplugged")
        data = self.data[:size]
        del self.data[:size]
        return bytes(data)

    def write(self, data):
        self.written.append(data)
        return len(data)

    def add(self, value):
        self.data.extend((json.dumps(value) + "\n").encode())


def test_disconnect_reconnect_and_ack_not_retried(tmp_path):
    now = [0]
    devices = [FakeSerial(), FakeSerial()]
    for device in devices:
        device.add(packet())
    created = []
    def factory(**kwargs):
        device = devices[len(created)]
        created.append(device)
        return device
    packets, statuses, results = [], [], []
    manager = SerialManager(Diagnostics(tmp_path), packets.append, statuses.append, results.append,
                            port="COM-test", factory=factory, enumerator=lambda: [], clock=lambda: now[0])
    manager.service_once()
    assert manager.confirmed and packets[-1]["new_session"]
    request_id = manager.command({"cmd": "ping"})
    manager.service_once()
    assert json.loads(devices[0].written[0])["id"] == request_id
    devices[0].broken = True
    manager.service_once()
    assert not manager.confirmed and not results[-1]["ok"]
    now[0] = 1
    manager.service_once()
    assert len(created) == 1
    now[0] = 2
    manager.service_once()
    assert manager.confirmed and packets[-1]["new_session"]
    assert not devices[1].written
    request_id = manager.command({"cmd": "get_status"})
    manager.service_once()
    devices[1].add({"ver": 1, "type": "ack", "id": request_id, "cmd": "get_status", "ok": True})
    manager.service_once()
    assert results[-1]["ok"]
    manager._close("test end")
    manager.handler.close()


def test_wrong_device_stale_and_malformed_packet(tmp_path):
    now = [0]
    device = FakeSerial(b'{"type":"telemetry","device":"other"}\n')
    statuses = []
    manager = SerialManager(Diagnostics(tmp_path), lambda value: None, statuses.append,
                            port="test", factory=lambda **kw: device, enumerator=lambda: [], clock=lambda: now[0])
    manager.service_once()
    assert not manager.confirmed
    with pytest.raises(RuntimeError):
        manager.command({"cmd": "radar_config"})
    device.add(packet())
    manager.service_once()
    device.data.extend(b'{invalid}\n')
    manager.service_once()
    assert statuses[-1]["state"] == "invalid"
    now[0] = 4
    manager.service_once()
    assert device.closed and statuses[-1]["state"] == "error"
    manager.handler.close()


def test_sensor_validity_stabilization_gaps_restart():
    sensors = SensorManager(stale_seconds=3, stabilization_seconds=1)
    sensors.ingest(packet(), 0)
    assert not sensors.ready(0)
    sensors.ingest(packet(2, 400), 1)
    assert sensors.ready(1)
    sensors.ingest(packet(4, 800), 1.1)
    assert not sensors.ready(1.1)
    sensors.ingest(packet(5, 1000), 1.2)
    assert not sensors.ready(1.3)
    sensors.ingest(packet(1, 200), 1.4)
    assert sensors.generation == 1 and not sensors.ready(1.5)
    with pytest.raises(ValueError):
        sensors.ingest(packet(1, 200), 1.6)
    assert not sensors.snapshot(1.6).valid
    sensors.ingest(packet(2, 400), 1.7)
    assert not sensors.snapshot(5).valid


def test_sensor_error_not_absence():
    sensors = SensorManager()
    sensors.ingest(packet(radar_ok=False, sensor_ok=False, presence=None, moving=None, stationary=None, distance_cm=None), 0)
    assert sensors.snapshot(0).packet["presence"] is None
    assert not sensors.ready(0)


def test_serial_io_runs_on_worker_and_stops(tmp_path):
    seen = threading.Event()
    owner = []
    device = FakeSerial()
    device.add(packet())
    def factory(**kwargs):
        owner.append(threading.current_thread().name)
        return device
    manager = SerialManager(Diagnostics(tmp_path), lambda value: seen.set(), lambda value: None,
                            port="test", factory=factory, enumerator=lambda: [])
    manager.start()
    assert seen.wait(2)
    manager.stop()
    assert manager.wait(2)
    assert owner == ["smc-serial"] and device.closed
