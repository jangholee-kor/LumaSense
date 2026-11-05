"""Track CLI reports separately from accepted requests and physical observations."""
import math


class BrightnessFeedback:
    CHECK_DELAY = 2.0
    LATE_CHECK_DELAY = 8.0
    POLL_INTERVAL = 30.0
    MAX_RETRIES = 2

    def __init__(self):
        self.expected = None
        self.reported = None
        self.due = math.inf
        self.late_check = None
        self.retries = 0
        self.read_errors = 0
        self.retry_pending = False
        self.exhausted = False
        self.status = "보고값 미확인"

    def written(self, percent, now):
        self.expected = percent
        self.retry_pending = False
        self.due = now + self.CHECK_DELAY
        self.late_check = now + self.LATE_CHECK_DELAY
        self.status = "요청 접수 · 보고값 확인 대기"

    def failed(self, percent, now, error):
        self.expected = percent
        self.status = f"밝기 요청 실패: {error}"
        self._retry(now)

    def _retry(self, now):
        self.exhausted = self.retries >= self.MAX_RETRIES
        self.retry_pending = not self.exhausted
        self.due = math.inf if self.exhausted else now + self.CHECK_DELAY
        self.status += " · 재시도 종료" if self.exhausted else " · 재시도 대기"

    def checked(self, reported, now, error=""):
        self.reported = reported
        if error or reported is None:
            self.read_errors += 1
            self.exhausted = self.read_errors > self.MAX_RETRIES
            self.due = math.inf if self.exhausted else now + self.CHECK_DELAY
            self.status = f"보고값 확인 불가: {error or '밝기 정보 없음'}"
            if self.exhausted:
                self.status += " · 재조회 종료"
            return
        self.read_errors = 0
        if not math.isclose(reported, self.expected, rel_tol=0, abs_tol=0.5):
            self.status = f"보고값 불일치 · 요청 {self.expected}% / 보고 {reported:g}%"
            self._retry(now)
            return
        self.status = "보고값 일치 · 실제 화면 미확인"
        self.due = self.late_check if self.late_check is not None and self.late_check > now else now + self.POLL_INTERVAL
        self.late_check = None
