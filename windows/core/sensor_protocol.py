"""Shared bounded JSON Lines decoder and sensor protocol validation."""
import json
import math
from serial.tools import list_ports


def ports():
    return [{"port": p.device, "description": p.description, "vid": p.vid, "pid": p.pid,
             "serial_number": p.serial_number} for p in list_ports.comports()]


def select_port(configured="", available=None):
    if configured:
        return configured
    candidates = [p["port"] for p in (ports() if available is None else available)
                  if (p["vid"], p["pid"]) == (0x303A, 0x1001)]
    if len(candidates) != 1:
        raise ValueError(f"USB Serial/JTAG 장치가 {len(candidates)}개입니다. --port COM번호를 지정하세요.")
    return candidates[0]


def validate_telemetry(value):
    if not isinstance(value, dict) or type(value.get("ver")) is not int or value.get("ver") != 1 or value.get("type") != "telemetry" or value.get("device") != "smart-monitor-s3":
        raise ValueError("Smart Monitor Controller v1 telemetry가 아닙니다.")
    for field in ("seq", "uptime_ms"):
        if type(value.get(field)) is not int or value[field] < 0:
            raise ValueError(f"잘못된 {field}")
    for field in ("light_ok", "radar_ok", "sensor_ok"):
        if type(value.get(field)) is not bool:
            raise ValueError(f"잘못된 {field}")
    if value["sensor_ok"] != (value["light_ok"] and value["radar_ok"]):
        raise ValueError("sensor_ok 불일치")
    lux = value.get("lux")
    if value["light_ok"]:
        if type(lux) not in (int, float) or not math.isfinite(lux) or not 0 <= lux <= 65535:
            raise ValueError("잘못된 lux")
    elif lux is not None:
        raise ValueError("조도 오류는 lux=null이어야 합니다.")
    for field in ("presence", "moving", "stationary"):
        if value["radar_ok"]:
            if type(value.get(field)) is not bool:
                raise ValueError(f"잘못된 {field}")
        elif value.get(field) is not None:
            raise ValueError("레이더 오류를 인체 부재로 처리할 수 없습니다.")
    if value["radar_ok"] and value["presence"] != (value["moving"] or value["stationary"]):
        raise ValueError("인체 상태 필드 불일치")
    distance = value.get("distance_cm")
    if distance is not None and (type(distance) is not int or not 0 <= distance <= 65535):
        raise ValueError("잘못된 distance_cm")
    return value


class JsonLines:
    def __init__(self, limit=4096):
        self.buffer = bytearray()
        self.limit = limit
        self.discarding = False
        self.invalid = 0

    def feed(self, data):
        packets = []
        for byte in data:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try:
                        packet = json.loads(self.buffer.decode("utf-8"))
                        if not isinstance(packet, dict):
                            raise ValueError("object required")
                        packets.append(packet)
                    except (UnicodeDecodeError, ValueError):
                        self.invalid += 1
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > self.limit:
                    self.buffer.clear()
                    self.discarding = True
                    self.invalid += 1
        return packets
