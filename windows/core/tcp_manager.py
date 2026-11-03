"""Bounded TCP adapter sharing the serial worker's queue, ACK and reconnect logic."""
import ipaddress
import json
import socket
import time
import uuid

from .sensor_protocol import JsonLines
from .serial_manager import SerialManager


class TcpStream:
    def __init__(self, host, port, token, *, clock=time.monotonic, connector=socket.create_connection):
        # Numeric addresses avoid an unbounded DNS lookup in the worker/shutdown.
        ipaddress.IPv4Address(host)
        if len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("USB에서 Wi-Fi 설정을 저장한 뒤 연결하세요.")
        self.host, self.tcp_port, self.token = host, port, token
        self.clock, self.connector = clock, connector
        self.socket = None
        self.timeout = .1

    def open(self):
        started = self.clock()
        self.socket = self.connector((self.host, self.tcp_port), timeout=1)
        try:
            self.socket.settimeout(.1)
            self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            identifier = uuid.uuid4().hex
            self.write((json.dumps(dict(ver=1, cmd="auth", id=identifier, token=self.token)) + "\n").encode())
            decoder = JsonLines(limit=1024)
            while self.clock() - started < 2:
                for reply in decoder.feed(self.read(1024)):
                    if (reply.get("ver") == 1 and reply.get("type") == "ack" and reply.get("cmd") == "auth"
                            and reply.get("id") == identifier and reply.get("ok") is True):
                        boot = reply.get("boot_id")
                        uptime = reply.get("uptime_ms")
                        if not isinstance(boot, str) or len(boot) != 16 or type(uptime) is not int or uptime < 0:
                            raise ValueError("잘못된 무선 장치 확인 응답")
                        self.boot_id, self.anchor_uptime = boot, uptime
                        self.anchor_received = self.clock()
                        if self.anchor_received - started > 1:
                            raise TimeoutError("무선 장치 확인 응답 지연")
                        return
            raise TimeoutError("무선 장치 인증 시간 초과")
        except Exception:
            self.close()
            raise

    @property
    def in_waiting(self):
        return 1024

    def read(self, size):
        try:
            data = self.socket.recv(size)
        except socket.timeout:
            return b""
        if not data:
            raise ConnectionError("무선 장치 연결 종료")
        return data

    def write(self, payload):
        self.socket.sendall(payload)
        return len(payload)

    def close(self):
        connection, self.socket = self.socket, None
        if connection:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()

    def cancel_read(self):
        # Interrupt reads without waiting for a network response.
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def validate(self, packet):
        if packet.get("boot_id") != self.boot_id:
            raise ValueError("무선 장치가 재시작했습니다.")
        # A buffered old packet cannot acquire freshness merely by arriving now.
        age = self.clock() - self.anchor_received - (packet["uptime_ms"] - self.anchor_uptime) / 1000
        if age > 1 or age < -1:
            raise ValueError("무선 센서 데이터 지연 또는 시각 불일치")


class TcpManager(SerialManager):
    def __init__(self, diagnostics, on_packet, on_status, on_command=lambda result: None,
                 *, host, port=47653, token, stale_seconds=3, clock=time.monotonic,
                 connector=socket.create_connection):
        def factory(**kwargs):
            return TcpStream(host, port, token, clock=clock, connector=connector)
        super().__init__(diagnostics, on_packet, on_status, on_command, port=host,
                         stale_seconds=stale_seconds, factory=factory, enumerator=lambda: [], clock=clock)

    def validate_transport(self, packet):
        try:
            self.io.validate(packet)
        except ValueError as error:
            raise OSError(str(error)) from error
