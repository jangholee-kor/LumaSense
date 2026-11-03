"""Distance-window occupancy with hysteresis; invalid ranges never mean absence."""


class TofPresence:
    def __init__(self, minimum_cm=20, maximum_cm=150, hysteresis_cm=5, hold_seconds=1):
        self.minimum_mm = minimum_cm * 10
        self.maximum_mm = maximum_cm * 10
        self.hysteresis_mm = hysteresis_cm * 10
        self.hold_seconds = hold_seconds
        self.reset()

    def reset(self):
        self.present = None
        self.candidate = None
        self.candidate_since = None

    def observe(self, distance_mm, now):
        margin = self.hysteresis_mm if self.present is True else 0
        candidate = self.minimum_mm - margin <= distance_mm <= self.maximum_mm + margin
        if self.present is None:
            self.present = candidate
        if candidate == self.present:
            self.candidate = self.candidate_since = None
        elif candidate != self.candidate:
            self.candidate, self.candidate_since = candidate, now
        elif now - self.candidate_since >= self.hold_seconds:
            self.present = candidate
            self.candidate = self.candidate_since = None
        return self.present
