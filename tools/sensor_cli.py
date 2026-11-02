"""USB Serial/JTAG discovery, explicit commands and timestamped capture."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
import uuid

import serial
from windows.core.sensor_protocol import JsonLines, ports, select_port, validate_telemetry
from windows.core.diagnostics import Diagnostics


class Device:
    def __init__(self, port):
        self.serial = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=1)
        self.serial.dtr = False
        self.serial.rts = False
        self.serial.port = port
        self.decoder = JsonLines()
        self.queue = deque()

    def __enter__(self):
        self.serial.open()
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                packet = self.read(deadline)
                if packet and packet.get("type") == "telemetry":
                    validate_telemetry(packet)
                    self.decoder.invalid = 0
                    return self
            raise TimeoutError("Smart Monitor Controller 펌웨어 응답이 없습니다.")
        except Exception:
            self.serial.close()
            raise

    def __exit__(self, *_):
        self.serial.close()

    def read(self, deadline):
        while time.monotonic() < deadline:
            if self.queue:
                return self.queue.popleft()
            data = self.serial.read(min(self.serial.in_waiting, 1024) or 1)
            self.queue.extend(self.decoder.feed(data))
        return None

    def command(self, command):
        command = {**command, "ver": 1, "id": uuid.uuid4().hex}
        self.serial.write((json.dumps(command, allow_nan=False) + "\n").encode("utf-8"))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            packet = self.read(deadline)
            if packet and packet.get("type") == "ack" and packet.get("id") == command["id"]:
                if packet.get("ok") is not True:
                    raise RuntimeError(f"Firmware command rejected: {packet}")
                return packet
        raise TimeoutError("명령 ACK 응답 시간 초과")


def capture(device, duration, output, stale_seconds=3):
    if not math.isfinite(duration) or not 0 < duration <= 86400:
        raise ValueError("duration은 0초 초과, 86400초 이하")
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    summary = {"duration_seconds": duration, "telemetry": 0, "healthy": 0, "sensor_errors": 0,
               "invalid_packets": 0, "sequence_gaps": 0, "restarts": 0, "physical_result": "unverified"}
    previous = None
    last_packet_at = start
    try:
        with (output / "sensor.jsonl").open("w", encoding="utf-8") as stream:
            while time.monotonic() - start < duration:
                packet = device.read(min(start + duration, time.monotonic() + 1))
                if time.monotonic() - last_packet_at > stale_seconds:
                    raise TimeoutError("센서 데이터 수신 중단")
                if not packet or packet.get("type") != "telemetry":
                    continue
                timestamp = datetime.now(timezone.utc).isoformat()
                try:
                    validate_telemetry(packet)
                except ValueError as error:
                    summary["invalid_packets"] += 1
                    stream.write(json.dumps({"received_at": timestamp, "error": str(error), "packet": packet}, ensure_ascii=False) + "\n")
                    continue
                summary["telemetry"] += 1
                last_packet_at = time.monotonic()
                summary["healthy" if packet["sensor_ok"] else "sensor_errors"] += 1
                if previous is not None:
                    if packet["seq"] <= previous:
                        summary["restarts"] += 1
                    elif packet["seq"] != previous + 1:
                        summary["sequence_gaps"] += packet["seq"] - previous - 1
                previous = packet["seq"]
                stream.write(json.dumps({"received_at": timestamp, "packet": packet}, ensure_ascii=False) + "\n")
                stream.flush()
    except Exception as error:
        summary["transport_error"] = str(error)
        raise
    finally:
        elapsed = time.monotonic() - start
        summary["elapsed_seconds"] = round(elapsed, 3)
        summary["invalid_lines"] = device.decoder.invalid
        summary["sensor_stream_pass"] = bool(summary["telemetry"] and not any(summary.get(key) for key in
            ("sensor_errors", "invalid_packets", "invalid_lines", "sequence_gaps", "restarts", "transport_error")))
        summary["ten_minute_stream_pass"] = summary["sensor_stream_pass"] and elapsed >= 600
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("ports", "select-port", "status", "record", "command"))
    parser.add_argument("--port", default="")
    parser.add_argument("--duration", type=float, default=600)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", default='{"cmd":"get_status"}')
    parser.add_argument("--request-file", type=Path, help="UTF-8 JSON 명령 파일")
    args = parser.parse_args()
    log = Diagnostics()
    try:
        if args.action == "ports":
            print(json.dumps(ports(), ensure_ascii=False, indent=2))
            return 0
        port = select_port(args.port)
        if args.action == "select-port":
            print(port)
            return 0
        if args.action == "record" and (not math.isfinite(args.duration) or not 0 < args.duration <= 86400):
            raise ValueError("duration은 0초 초과, 86400초 이하")
        with Device(port) as device:
            log.event("sensor_cli_connected", port=port, action=args.action)
            if args.action in ("status", "command"):
                text = args.request_file.read_text(encoding="utf-8-sig") if args.request_file else args.json
                request = {"cmd": "get_status"} if args.action == "status" else json.loads(text)
                if not isinstance(request, dict):
                    raise ValueError("command must be a JSON object")
                response = device.command(request)
                log.event("sensor_cli_ack", port=port, request=request, response=response)
                print(json.dumps(response, ensure_ascii=False, indent=2))
            else:
                path = args.output or Path(".local") / "sensor-capture" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                status = device.command({"cmd": "get_status"})
                result = capture(device, args.duration, path, stale_seconds=max(3, status.get("report_ms", 200) / 1000 * 3))
                log.event("sensor_capture_finished", port=port, output=str(path.resolve()), summary=result)
                print(json.dumps({"output": str(path.resolve()), **result}, ensure_ascii=False, indent=2))
                return 0 if result["sensor_stream_pass"] else 1
        return 0
    except (serial.SerialException, OSError, ValueError, TimeoutError, RuntimeError) as error:
        log.event("sensor_cli_error", action=args.action, port=args.port, error=str(error))
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
