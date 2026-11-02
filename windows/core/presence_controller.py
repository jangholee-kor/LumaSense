"""Presence state machine: invalid data is never interpreted as absence."""
from enum import Enum


class PresenceState(str, Enum):
    PRESENT = "PRESENT"
    MAYBE_ABSENT = "MAYBE_ABSENT"
    ABSENT = "ABSENT"
    DISPLAY_OFF = "DISPLAY_OFF"
    RECOVERING = "RECOVERING"
    SENSOR_ERROR = "SENSOR_ERROR"


class PresenceController:
    def __init__(self, settings):
        self.settings = settings
        self.state = PresenceState.SENSOR_ERROR
        self.absent_since = None
        self.countdown_until = None
        self.owns_off = False
        self.pending = None
        self.off_failed = False
        self.wake_attempts = 0
        self.retry_after = 0.0
        self.reason = "센서 연결 대기"

    def _wake(self, now):
        if self.owns_off and self.pending is None and self.wake_attempts < 3 and now >= self.retry_after:
            self.pending = "wake"
            self.wake_attempts += 1
            self.state = PresenceState.RECOVERING
            return "wake"
        return None

    def tick(self, now, snapshot, ready, *, enabled, paused=False, input_age=None, locked=False):
        valid = bool(snapshot.valid and snapshot.packet and snapshot.packet["sensor_ok"] and ready)
        input_block = self.settings.use_recent_input and (input_age is None or input_age < self.settings.recent_input_seconds)
        if not valid or not enabled or paused or locked:
            self.absent_since = None
            self.countdown_until = None
            self.state = PresenceState.SENSOR_ERROR if not valid else PresenceState.PRESENT
            self.reason = snapshot.reason if not valid else "자동 절전 중단"
            return self._wake(now)
        present = snapshot.packet["presence"]
        distance = snapshot.packet.get("distance_cm")
        if present and distance is not None and distance > self.settings.max_distance_cm:
            present = False
        # Recent physical input always overrides radar absence.
        if present or input_block:
            self.absent_since = None
            self.countdown_until = None
            self.off_failed = False
            self.reason = "인체 감지" if present else "최근 입력 또는 입력 상태 확인 불가"
            if not self.owns_off:
                self.state = PresenceState.PRESENT
            return self._wake(now)
        if self.pending:
            return None
        if self.owns_off:
            self.state = PresenceState.DISPLAY_OFF
            return None
        if self.off_failed:
            self.state = PresenceState.SENSOR_ERROR
            self.reason = "절전 요청 실패; 재감지 또는 수동 재개 필요"
            return None
        if self.absent_since is None:
            self.absent_since = now
        if now - self.absent_since < self.settings.absence_seconds:
            self.state = PresenceState.MAYBE_ABSENT
            self.reason = "연속 부재 확인 중"
            return None
        self.state = PresenceState.ABSENT
        if self.countdown_until is None:
            self.countdown_until = now + 5
        self.reason = "화면 절전 카운트다운"
        if now >= self.countdown_until:
            self.pending = "off"
            return "off"
        return None

    def completed(self, action, success, now):
        self.pending = None
        if action == "off":
            self.owns_off = success
            self.off_failed = not success
            self.state = PresenceState.DISPLAY_OFF if success else PresenceState.SENSOR_ERROR
            self.reason = "화면 절전 요청 접수 (실제 상태 미확인)" if success else "화면 절전 요청 실패"
            self.wake_attempts = 0
        else:
            if success:
                self.owns_off = False
                self.wake_attempts = 0
                self.state = PresenceState.PRESENT
                self.reason = "복귀 요청 접수 (실제 상태 미확인)"
            else:
                self.retry_after = now + 2
                self.state = PresenceState.SENSOR_ERROR
                self.reason = "복귀 요청 실패"

    def cancel(self, now):
        self.absent_since = now
        self.countdown_until = None
        self.off_failed = False
