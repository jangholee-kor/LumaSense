"""Single-owner serial worker with bounded reads, reconnect and command ACKs."""
import json
import queue
import threading
import time
import uuid
from datetime import datetime, timezone
from logging import Logger
from logging.handlers import RotatingFileHandler

import serial

from .sensor_protocol import JsonLines, ports, select_port, validate_telemetry


class SerialManager:
    def __init__(self, diagnostics, on_packet, on_status, on_command=lambda result: None,
                 port="", serial_number="", stale_seconds=3, retry_seconds=2,
                 factory=serial.Serial, enumerator=ports, clock=time.monotonic):
        self.log, self.on_packet, self.on_status, self.on_command = diagnostics, on_packet, on_status, on_command
        self.port, self.serial_number = port, serial_number
        self.stale_seconds, self.retry_seconds = stale_seconds, retry_seconds
        self.factory, self.enumerator, self.clock = factory, enumerator, clock
        self.io = None
        self.decoder = JsonLines()
        self.commands = queue.Queue(maxsize=16)
        self.pending = None
        self.confirmed = False
        self.last_valid = 0.0
        self.next_retry = 0.0
        self.state = None
        self.stop_event = threading.Event()
        self.thread = None
        self.sensor_log = Logger(f"sensor.{id(self)}")
        self.sensor_log.setLevel(20)
        self.handler = RotatingFileHandler(self.log.root / "sensor.jsonl", maxBytes=4_000_000, backupCount=5, encoding="utf-8")
        self.sensor_log.addHandler(self.handler)

    def _status(self, state, message):
        value = (state, message)
        if value != self.state:
            self.state = value
            event = {"state": state, "message": message, "port": self.port, "connected": state == "connected"}
            self.log.event("serial_status", **event)
            self.on_status(event)

    def _result(self, request, ok, error="", response=None):
        value = {"id": request["id"], "cmd": request["cmd"], "ok": ok, "error": error, "response": response}
        self.log.event("serial_command_result", **value)
        self.on_command(value)

    def command(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("cmd"), str):
            raise ValueError("명령 객체와 cmd 문자열 필요")
        # Reject non-JSON values before taking ownership of the request.
        request = json.loads(json.dumps({**payload, "ver": 1, "id": uuid.uuid4().hex}, allow_nan=False))
        if len(json.dumps(request).encode()) > 1800:
            raise ValueError("명령 길이 초과")
        if not self.confirmed or self.stop_event.is_set():
            raise RuntimeError("센서 장치 연결이 확인되지 않았습니다.")
        self.commands.put_nowait(request)
        return request["id"]

    def _close(self, reason):
        self.confirmed = False
        if self.io is not None:
            try:
                self.io.close()
            except OSError:
                pass
            self.io = None
        if self.pending:
            self._result(self.pending[0], False, reason)
            self.pending = None
        while True:
            try:
                self._result(self.commands.get_nowait(), False, reason)
            except queue.Empty:
                break
        self.decoder = JsonLines()

    def validate_transport(self, packet):
        """Transport-specific freshness/identity checks; USB has no extra envelope."""

    def service_once(self):
        now = self.clock()
        if self.stop_event.is_set():
            return
        try:
            if self.io is None:
                if now < self.next_retry:
                    return
                available = self.enumerator()
                if self.serial_number:
                    matches = [p["port"] for p in available if p.get("serial_number") == self.serial_number]
                    if len(matches) != 1:
                        raise ValueError("지정한 USB 장치가 없거나 여러 개입니다.")
                    self.port = matches[0]
                else:
                    self.port = select_port(self.port, available)
                self._status("connecting", "펌웨어 확인 중")
                self.io = self.factory(port=None, baudrate=115200, timeout=.1, write_timeout=1)
                self.io.dtr = False
                self.io.rts = False
                self.io.port = self.port
                self.io.open()
                self.last_valid = now
            data = self.io.read(min(self.io.in_waiting, 1024) or 1)
            before = self.decoder.invalid
            packets = self.decoder.feed(data)
            if self.decoder.invalid != before and self.confirmed:
                self._status("invalid", "손상된 JSON 패킷")
            for packet in packets:
                if packet.get("type") == "telemetry":
                    try:
                        validate_telemetry(packet)
                        self.validate_transport(packet)
                    except ValueError as error:
                        self._status("invalid", str(error))
                        continue
                    first = not self.confirmed
                    self.confirmed = True
                    self.last_valid = self.clock()
                    self._status("connected", "센서 연결됨")
                    self.sensor_log.info(json.dumps({"received_at": datetime.now(timezone.utc).isoformat(),
                                                    "received_monotonic": self.last_valid, "packet": packet}, ensure_ascii=False))
                    self.on_packet({"packet": packet, "new_session": first, "received_at": self.last_valid})
                elif packet.get("type") == "ack" and self.pending and packet.get("id") == self.pending[0]["id"]:
                    request = self.pending[0]
                    valid = type(packet.get("ver")) is int and packet["ver"] == 1 and packet.get("cmd") == request["cmd"]
                    self._result(request, bool(valid and packet.get("ok") is True),
                                 str(packet.get("error", "ACK 형식 오류")), packet)
                    self.pending = None
            now = self.clock()
            stale_limit = max(self.stale_seconds, 11) if self.pending else (self.stale_seconds if self.confirmed else 5)
            if now - self.last_valid > stale_limit:
                raise TimeoutError("센서 데이터 수신 중단")
            if self.pending and now >= self.pending[1]:
                self._result(self.pending[0], False, "ACK 시간 초과; 자동 재전송하지 않음")
                self.pending = None
            if self.confirmed and self.pending is None:
                try:
                    request = self.commands.get_nowait()
                except queue.Empty:
                    return
                payload = (json.dumps(request, allow_nan=False) + "\n").encode()
                self.pending = (request, now + 10)
                if self.io.write(payload) != len(payload):
                    raise OSError("명령 전송 길이 불일치")
                self.log.event("serial_command_sent", id=request["id"], cmd=request["cmd"])
        except (OSError, ValueError, serial.SerialException) as error:
            self._close(str(error))
            self.next_retry = self.clock() + self.retry_seconds
            self._status("error", str(error))

    def start(self):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("시리얼 작업이 이미 실행 중입니다.")
        self.stop_event.clear()
        def run():
            try:
                while not self.stop_event.is_set():
                    self.service_once()
                    self.stop_event.wait(.02)
            except Exception as error:
                self.log.event("serial_worker_error", error=str(error))
                self._status("error", str(error))
            finally:
                self._close("연결 종료")
                self._status("disconnected", "연결 종료")
                self.handler.close()
        self.thread = threading.Thread(target=run, name="smc-serial", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.io is not None:
            try:
                self.io.cancel_read()
            except (AttributeError, OSError):
                pass

    def wait(self, seconds=2):
        if self.thread:
            self.thread.join(seconds)
            return not self.thread.is_alive()
        return True
