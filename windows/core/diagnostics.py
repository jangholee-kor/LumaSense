"""Append-only structured diagnostics; API acceptance is not physical success."""
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .log_handler import ReportingRotatingFileHandler


def data_dir() -> Path:
    return Path(os.environ.get("SMC_DATA_DIR") or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SmartMonitorController")


class Diagnostics:
    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.storage_error_message = ""
        self.logger = logging.Logger(f"smc.{id(self)}", logging.INFO)
        handler = ReportingRotatingFileHandler(self.root / "app.log", maxBytes=2_000_000, backupCount=3,
                                              encoding="utf-8", on_error=self.storage_error)
        self.logger.addHandler(handler)

    def storage_error(self, filename, error):
        self.storage_error_message = f"로그 저장 오류 · {Path(filename).name}: {error}"
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": "log_storage_error",
                  "file": Path(filename).name, "error": error}
        try:
            with self.lock:
                self._append(record)
        except OSError:
            # The GUI still exposes the error when the whole directory is unwritable.
            pass

    def _append(self, record):
        filename = f"events-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
        with (self.root / filename).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def event(self, event: str, **fields) -> dict:
        record = {"time": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.lock:
            # Separate files per day also allow the independent watchdog to append.
            try:
                self._append(record)
            except OSError as error:
                filename = f"events-{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
                self.storage_error(filename, str(error))
            self.logger.info(line)
        return record
