"""Append-only structured diagnostics; API acceptance is not physical success."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


def data_dir() -> Path:
    return Path(os.environ.get("SMC_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SmartMonitorController")


class Diagnostics:
    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.logger = logging.Logger(f"smc.{id(self)}", logging.INFO)
        handler = RotatingFileHandler(self.root / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        self.logger.addHandler(handler)

    def event(self, event: str, **fields) -> dict:
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.lock:
            # Separate files per day also allow the independent watchdog to append.
            filename = f"events-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
            with (self.root / filename).open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            self.logger.info(line)
        return record
