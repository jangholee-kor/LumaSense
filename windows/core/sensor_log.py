import json
from datetime import datetime, timezone
from logging import Logger
from .log_handler import ReportingRotatingFileHandler


class SensorRecorder:
    def __init__(self, root, on_error):
        self.logger = Logger(f"sensor-record.{id(self)}", 20)
        self.handler = ReportingRotatingFileHandler(root / "sensor.jsonl", maxBytes=4_000_000, backupCount=5,
                                                   encoding="utf-8", on_error=on_error)
        self.logger.addHandler(self.handler)

    def write(self, packet, received_at, simulated=False):
        self.logger.info(json.dumps({"received_at": datetime.now(timezone.utc).isoformat(),
                                    "received_monotonic": received_at, "simulated": simulated, "packet": packet}, ensure_ascii=False))

    def close(self):
        self.handler.close()
