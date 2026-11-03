from contextlib import contextmanager
import json
import socket
import threading
import time

import pytest

from windows.core.diagnostics import Diagnostics
from windows.core.tcp_manager import TcpManager, TcpStream
from windows.tests.test_tof import packet

TOKEN = "a" * 64
BOOT = "0123456789abcdef"


def receive_line(connection):
    data = bytearray()
    while not data.endswith(b"\n"):
        part = connection.recv(1)
        if not part:
            raise EOFError()
        data += part
        if len(data) > 4096:
            raise ValueError("oversize test request")
    return json.loads(data)


def send_line(connection, value):
    connection.sendall((json.dumps(value) + "\n").encode())


@contextmanager
def board(*, wrong_key=False, wrong_boot=False, drop_ack=False, disconnect_once=False):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    listener.settimeout(.1)
    stop = threading.Event()
    requests = []
    errors = []
    boot_time = time.monotonic()
    def serve():
        try:
            while not stop.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(.03)
                    auth = receive_line(connection)
                    requests.append(auth)
                    if wrong_key or auth.get("token") != TOKEN:
                        continue
                    uptime = int((time.monotonic() - boot_time) * 1000)
                    ack = dict(ver=1, type="ack", cmd="auth", id=auth["id"], ok=True, boot_id=BOOT, uptime_ms=uptime)
                    encoded = (json.dumps(ack) + "\n").encode()
                    connection.sendall(encoded[:12])
                    time.sleep(.005)
                    connection.sendall(encoded[12:])
                    seq = 0
                    while not stop.is_set():
                        seq += 1
                        value = packet(seq)
                        value["uptime_ms"] = int((time.monotonic() - boot_time) * 1000)
                        if wrong_boot:
                            value["boot_id"] = "b" * 16
                        send_line(connection, value)
                        if disconnect_once and len([r for r in requests if r["cmd"] == "auth"]) == 1 and seq == 3:
                            break
                        try:
                            command = receive_line(connection)
                        except socket.timeout:
                            continue
                        requests.append(command)
                        if drop_ack:
                            break
                        send_line(connection, dict(ver=1, type="ack", cmd=command["cmd"], id=command["id"], ok=True))
        except (EOFError, ConnectionError, OSError):
            pass
        except Exception as error:
            errors.append(error)
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield listener.getsockname()[1], requests
    finally:
        stop.set()
        thread.join(2)
        listener.close()
        assert not thread.is_alive() and not errors


def pump(worker, condition, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        worker.service_once()
        if condition():
            return
    assert condition()


def cleanup(worker):
    worker._close("test complete")
    worker.handler.close()


def test_fragmented_auth_telemetry_and_correlated_command_ack(tmp_path):
    frames, statuses, results = [], [], []
    with board() as (port, requests):
        worker = TcpManager(Diagnostics(tmp_path), frames.append, statuses.append, results.append,
                            host="127.0.0.1", port=port, token=TOKEN)
        try:
            pump(worker, lambda: worker.confirmed)
            assert frames[0]["new_session"] and frames[0]["packet"]["ver"] == 2
            identifier = worker.command({"cmd": "ping"})
            pump(worker, lambda: bool(results))
            assert results[0]["id"] == identifier and results[0]["ok"]
            assert requests[0]["cmd"] == "auth" and requests[1]["cmd"] == "ping"
        finally:
            cleanup(worker)
    for path in tmp_path.glob("*.jsonl"):
        assert TOKEN not in path.read_text(encoding="utf-8")


def test_wrong_auth_key_never_confirms_sensor(tmp_path):
    statuses = []
    with board(wrong_key=True) as (port, _):
        worker = TcpManager(Diagnostics(tmp_path), lambda event: pytest.fail("unauthorized packet"), statuses.append,
                            host="127.0.0.1", port=port, token=TOKEN)
        try:
            worker.service_once()
            assert not worker.confirmed and worker.io is None
            assert statuses[-1]["state"] == "error"
        finally:
            cleanup(worker)


def test_changed_boot_drops_connection_instead_of_reusing_previous_session(tmp_path):
    frames = []
    with board(wrong_boot=True) as (port, _):
        worker = TcpManager(Diagnostics(tmp_path), frames.append, lambda event: None,
                            host="127.0.0.1", port=port, token=TOKEN)
        try:
            pump(worker, lambda: worker.io is None)
            assert not frames and not worker.confirmed
        finally:
            cleanup(worker)


def test_lost_mutation_ack_is_failed_without_retransmission(tmp_path):
    results = []
    with board(drop_ack=True) as (port, requests):
        worker = TcpManager(Diagnostics(tmp_path), lambda event: None, lambda event: None, results.append,
                            host="127.0.0.1", port=port, token=TOKEN)
        try:
            pump(worker, lambda: worker.confirmed)
            worker.command({"cmd": "tof_reset"})
            pump(worker, lambda: bool(results))
            assert not results[0]["ok"]
            assert len([value for value in requests if value["cmd"] == "tof_reset"]) == 1
        finally:
            cleanup(worker)


def test_buffered_old_data_cannot_acquire_freshness():
    clock = [100.0]
    stream = TcpStream("127.0.0.1", 1234, TOKEN, clock=lambda: clock[0])
    stream.boot_id, stream.anchor_uptime, stream.anchor_received = BOOT, 10000, 100
    value = packet()
    value["uptime_ms"] = 8000
    with pytest.raises(ValueError, match="지연"):
        stream.validate(value)
    value["uptime_ms"] = 11000
    clock[0] = 101
    stream.validate(value)
    clock[0] = 103
    with pytest.raises(ValueError, match="지연"):
        stream.validate(value)


def test_reconnect_authenticates_again_and_marks_new_session(tmp_path):
    frames = []
    with board(disconnect_once=True) as (port, requests):
        worker = TcpManager(Diagnostics(tmp_path), frames.append, lambda event: None,
                            host="127.0.0.1", port=port, token=TOKEN)
        worker.retry_seconds = .01
        try:
            pump(worker, lambda: sum(frame["new_session"] for frame in frames) >= 2, timeout=2)
            auth = [r for r in requests if r["cmd"] == "auth"]
            assert len(auth) == 2 and auth[0]["id"] != auth[1]["id"]
        finally:
            cleanup(worker)


@pytest.mark.parametrize("host,token", [("sensor.local", TOKEN), ("127.0.0.1", ""), ("127.0.0.1", "x" * 64)])
def test_tcp_requires_numeric_address_and_provisioned_key(host, token):
    with pytest.raises(ValueError):
        TcpStream(host, 47653, token)
