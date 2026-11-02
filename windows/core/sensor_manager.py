"""Sensor validity, sequence and startup stabilization; never invent absence."""
import copy
from dataclasses import dataclass

from .sensor_protocol import validate_telemetry


@dataclass(frozen=True)
class SensorSnapshot:
    packet: dict | None
    received_at: float | None
    healthy_since: float | None
    valid: bool
    reason: str
    generation: int


class SensorManager:
    def __init__(self, stale_seconds=3.0, stabilization_seconds=5.0):
        self.stale_seconds = stale_seconds
        self.stabilization_seconds = stabilization_seconds
        self.packet = None
        self.received_at = None
        self.healthy_since = None
        self.valid = False
        self.reason = "연결 대기"
        self.generation = 0

    def invalidate(self, reason, new_session=False):
        self.valid = False
        self.healthy_since = None
        self.reason = reason
        if new_session:
            self.packet = None
            self.received_at = None
            self.generation += 1

    def ingest(self, packet, now):
        try:
            validate_telemetry(packet)
            restarted = self.packet is not None and packet["uptime_ms"] < self.packet["uptime_ms"]
            if self.packet is not None and not restarted and packet["seq"] <= self.packet["seq"]:
                raise ValueError("센서 순번 중복 또는 역전")
            if restarted:
                self.invalidate("장치 재시작 안정화", new_session=True)
            gap = self.packet is not None and packet["seq"] != self.packet["seq"] + 1
            stale = self.received_at is not None and now - self.received_at > self.stale_seconds
            self.packet = copy.deepcopy(packet)
            self.received_at = now
            self.valid = True
            if not packet["sensor_ok"] or gap or stale:
                self.healthy_since = None
            elif self.healthy_since is None:
                self.healthy_since = now
            self.reason = "센서 오류" if not packet["sensor_ok"] else ("순번 누락 후 안정화" if gap else "정상")
            return self.snapshot(now)
        except (ValueError, TypeError) as error:
            self.invalidate(str(error))
            raise

    def snapshot(self, now):
        if self.received_at is not None and now - self.received_at > self.stale_seconds:
            self.invalidate("센서 데이터 수신 중단")
        return SensorSnapshot(copy.deepcopy(self.packet), self.received_at, self.healthy_since,
                              self.valid, self.reason, self.generation)

    def ready(self, now):
        snapshot = self.snapshot(now)
        return bool(snapshot.valid and snapshot.packet["sensor_ok"] and snapshot.healthy_since is not None
                    and now - snapshot.healthy_since >= self.stabilization_seconds)
