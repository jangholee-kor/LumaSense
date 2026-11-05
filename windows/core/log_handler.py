"""Keep logging when Windows temporarily refuses a rotating-file rename."""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler


class ReportingRotatingFileHandler(RotatingFileHandler):
    def __init__(self, *args, on_error, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_error = on_error
        self.last_error_at = -float("inf")

    def _report(self, error):
        now = time.monotonic()
        if now - self.last_error_at >= 60:
            self.last_error_at = now
            # Diagnostics writes this directly, without entering a log handler.
            self.on_error(self.baseFilename, str(error))

    def emit(self, record):
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except OSError as error:
                    self._report(error)
            # A failed rollover can leave stream=None. FileHandler reopens it.
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)

    def handleError(self, record):
        self._report(sys.exc_info()[1])
