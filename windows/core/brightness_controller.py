"""Independent lux mapping, filtering, transitions and command rate limits."""
import math
from .brightness_profiles import StepBrightness


def map_lux(lux, curve):
    if type(lux) not in (int, float) or not math.isfinite(lux) or lux < 0:
        raise ValueError("유효한 lux 필요")
    if lux <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if lux <= x1:
            return y0 + (y1 - y0) * (lux - x0) / (x1 - x0)
    return curve[-1][1]


class BrightnessController:
    def __init__(self, settings):
        self.settings = settings
        self.filtered_lux = None
        self.target = None
        self.requested = None
        self.last_sent = -math.inf
        self.ramp_start = 0.0
        self.ramp_value = 0.0
        self.pause_until = 0.0
        self.light_on = None
        self.light_candidate = None
        self.light_candidate_since = 0.0
        self.steps = StepBrightness(next(profile for profile in settings.brightness_profiles
                                        if profile["name"] == settings.brightness_profile)) if settings.brightness_mode == "steps" else None

    def invalidate_observation(self):
        """Discard pending threshold dwell across missing/invalid sensor observations."""
        self.light_candidate = self.light_on = None
        self.target = self.filtered_lux = None
        if self.steps:
            self.steps.reset()

    @property
    def settled(self):
        if self.settings.brightness_mode == "two_level":
            return self.light_on is not None and self.light_on == self.light_candidate
        return self.steps is None or self.steps.candidate is None

    def seed(self, brightness, now):
        if brightness is None or not 0 <= brightness <= 100:
            return
        self.requested = round(brightness)
        self.ramp_value = brightness
        self.ramp_start = now

    def observe(self, lux, now):
        if type(lux) not in (int, float) or not math.isfinite(lux) or lux < 0:
            raise ValueError("유효한 lux 필요")
        if self.steps:
            self.filtered_lux = lux
            self.target = self.steps.observe(lux, now)
            return self.target
        if self.settings.brightness_mode == "two_level":
            self.filtered_lux = lux
            candidate = lux >= self.settings.light_threshold_lux
            if candidate != self.light_candidate:
                self.light_candidate = candidate
                self.light_candidate_since = now
            if self.light_on is None or now - self.light_candidate_since >= self.settings.light_switch_seconds:
                self.light_on = candidate
            self.target = self.settings.light_on_brightness if self.light_on else self.settings.light_off_brightness
            return self.target
        old = self.filtered_lux
        fast_change = old is not None and (abs(lux - old) >= 100 or abs(lux - old) >= max(5, old * 2))
        self.filtered_lux = lux if old is None or fast_change else old + self.settings.ema_alpha * (lux - old)
        mapped = round(map_lux(self.filtered_lux, self.settings.curve))
        target = max(self.settings.brightness_min, min(self.settings.brightness_max, mapped))
        if self.target is None or abs(target - self.target) >= self.settings.brightness_deadband:
            self.target = target
            self.ramp_value = self.requested if self.requested is not None else target
            self.ramp_start = max(now, self.pause_until)
        return self.target

    def manual(self, brightness, now):
        self.seed(brightness, now)
        self.pause_until = now + self.settings.manual_pause_seconds
        self.ramp_start = self.pause_until
        self.last_sent = now

    def resume(self, now):
        self.pause_until = now
        self.ramp_start = now
        self.ramp_value = self.requested if self.requested is not None else (self.target or 0)

    def propose(self, now):
        if self.target is None or now < self.pause_until or now - self.last_sent < self.settings.brightness_interval:
            return None
        if self.settings.brightness_mode in ("two_level", "steps"):
            return self.target if self.target != self.requested else None
        progress = min(1, max(0, (now - self.ramp_start) / self.settings.transition_seconds))
        value = round(self.ramp_value + (self.target - self.ramp_value) * progress)
        if self.requested is not None and abs(value - self.requested) < self.settings.brightness_deadband:
            return None
        return value

    def sent(self, brightness, now):
        self.requested = brightness
        self.last_sent = now
