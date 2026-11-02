import time
import uuid
from enum import Enum

from .watchdog import arm_watchdog


class State(str, Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    RECOVERING = "recovering"


class DisplayController:
    """Countdown uses a monotonic clock and cannot be armed twice."""
    def __init__(self, power, diagnostics, clock=time.monotonic, arm=arm_watchdog):
        self.power, self.log, self.clock, self.arm = power, diagnostics, clock, arm
        self.state = State.IDLE
        self.deadline = 0.0
        self.test_id = ""

    def start(self):
        if self.state != State.IDLE:
            raise RuntimeError("이미 화면 시험이 진행 중입니다.")
        self.test_id = uuid.uuid4().hex
        self.deadline = self.clock() + 5
        self.state = State.COUNTDOWN
        self.log.event("sleep_countdown", test_id=self.test_id, seconds=5, affects="all_displays")

    def cancel(self):
        if self.state == State.COUNTDOWN:
            self.log.event("sleep_cancelled", test_id=self.test_id)
            self.state = State.IDLE
            return True
        return False

    def execute(self, method, seconds, allow_mouse, fallback_seconds=30):
        if self.state != State.COUNTDOWN or self.clock() < self.deadline:
            raise RuntimeError("5초 카운트다운이 끝나지 않았습니다.")
        self.state = State.RECOVERING
        try:
            pid = self.arm(self.log.root, self.test_id, method, seconds, allow_mouse, fallback_seconds)
            self.log.event("recovery_armed", test_id=self.test_id, pid=pid, method=method,
                           seconds=seconds, fallback_seconds=fallback_seconds,
                           first_fallback_after_seconds=seconds + fallback_seconds)
            result = self.power.off()
            self.log.event("display_off_requested", test_id=self.test_id, result=result)
            return result
        except Exception as error:
            self.log.event("display_off_error", test_id=self.test_id, error=str(error))
            raise

    def finish(self):
        self.state = State.IDLE
