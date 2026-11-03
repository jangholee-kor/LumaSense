"""Coordinate fresh sensors, control models and independently guarded output."""
import threading
import time
import uuid

from .brightness_controller import BrightnessController
from .lease_guard import LeaseGuard
from .presence_controller import PresenceController
from .sensor_manager import SensorManager
from .tof_presence import TofPresence


class OffCancelled(RuntimeError):
    pass


class AutomationRuntime:
    def __init__(self, settings, diagnostics, power, *, clock=time.monotonic, guard_factory=LeaseGuard,
                 input_provider=lambda: None, locked_provider=lambda: True, input_token_provider=None):
        settings = settings.for_control()
        self.settings, self.log, self.power, self.clock = settings, diagnostics, power, clock
        self.guard_factory = guard_factory
        self.input_provider, self.locked_provider = input_provider, locked_provider
        self.input_token_provider = input_token_provider
        self.last_input_token = input_token_provider() if input_token_provider else None
        self.countdown_input_token = None
        self.input_wake_requested = False
        self.sensors = SensorManager(settings.sensor_stale_seconds, settings.stabilization_seconds)
        self.sensors.tof_presence = self._tof_presence(settings)
        self.brightness = BrightnessController(settings)
        self.presence = PresenceController(settings)
        self.lock = threading.RLock()
        self.pause_until = 0.0
        self.external_block = False
        self.brightness_pending = False
        self.guard = None
        self.last_pulse = 0.0
        self.epoch = 0
        self.monitor_id = settings.monitor_id
        self.last_action = "없음"
        self.last_state = None
        self.brightness_retry = 0.0

    @staticmethod
    def _tof_presence(settings):
        return TofPresence(settings.tof_min_distance_cm, settings.tof_max_distance_cm,
                           settings.tof_hysteresis_cm, settings.tof_hold_seconds)

    def sensor_status(self, value):
        if not value.get("connected"):
            with self.lock:
                self.sensors.invalidate(value.get("message", "연결 종료"), new_session=True)
                self.brightness.invalidate_observation()

    def ingest(self, event):
        with self.lock:
            if event.get("new_session"):
                self.sensors.invalidate("새 연결", new_session=True)
                self.brightness.invalidate_observation()
            try:
                snapshot = self.sensors.ingest(event["packet"], event["received_at"])
            except (ValueError, TypeError):
                self.brightness.invalidate_observation()
                raise
            if snapshot.healthy_since is None:
                self.brightness.invalidate_observation()
            if event["packet"]["light_ok"]:
                self.brightness.observe(event["packet"]["lux"], self.clock())

    def set_monitor(self, identifier, reported=None):
        with self.lock:
            if identifier != self.monitor_id:
                self.epoch += 1
                self.monitor_id = identifier
                self.brightness = BrightnessController(self.settings)
            self.brightness.seed(reported, self.clock())

    def pause(self, seconds=900):
        with self.lock:
            self.pause_until = self.clock() + seconds
            self.presence.cancel(self.clock())
            self.epoch += 1

    def resume(self):
        with self.lock:
            self.pause_until = 0
            self.brightness.resume(self.clock())
            self.presence.cancel(self.clock())

    def manual_brightness(self, percent):
        with self.lock:
            self.epoch += 1
            self.brightness.manual(percent, self.clock())

    def apply_settings(self, settings):
        settings.validate()
        settings = settings.for_control()
        with self.lock:
            requested = self.brightness.requested
            self.settings = settings
            self.sensors.stale_seconds = settings.sensor_stale_seconds
            self.sensors.stabilization_seconds = settings.stabilization_seconds
            self.sensors.tof_presence = self._tof_presence(settings)
            self.sensors.invalidate("설정 변경 후 안정화")
            self.brightness = BrightnessController(settings)
            self.brightness.seed(requested, self.clock())
            self.presence.settings = settings
            self.presence.cancel(self.clock())
            self.epoch += 1

    def _safe_off(self, now, input_age, locked, require_countdown=False):
        snap = self.sensors.snapshot(now)
        if not (self.settings.auto_presence and not self.external_block and now >= self.pause_until
                and self.sensors.ready(now) and not locked):
            return False
        if self.settings.use_recent_input and (input_age is None or input_age < self.settings.recent_input_seconds):
            return False
        if self.input_wake_requested:
            return False
        if require_countdown and self.input_token_provider is not None:
            token = self.input_token_provider()
            if token is None or self.countdown_input_token is None or token != self.countdown_input_token:
                return False
        if require_countdown and (self.presence.pending != "off" or self.presence.countdown_until is None
                                  or now < self.presence.countdown_until):
            return False
        present = snap.packet["presence"]
        distance = snap.packet.get("distance_cm")
        return not present or (snap.packet.get("ver") != 2 and distance is not None and distance > self.settings.max_distance_cm)

    def observe_input(self, now):
        if self.input_token_provider is None:
            return False
        token = self.input_token_provider()
        if token is None:
            return False
        with self.lock:
            changed = self.last_input_token is not None and token != self.last_input_token
            self.last_input_token = token
            if changed:
                self.input_wake_requested |= self.presence.owns_off or self.presence.pending == "off"
                countdown = self.presence.countdown_until is not None
                self.presence.cancel(now)
                if countdown:
                    self.log.event("countdown_cancelled_by_input")
            return changed

    def tick(self, now, input_age, locked, backend_ready):
        with self.lock:
            self.observe_input(now)
            snap = self.sensors.snapshot(now)
            ready = self.sensors.ready(now)
            paused = self.external_block or now < self.pause_until
            previous_countdown = self.presence.countdown_until
            power_action = self.presence.tick(now, snap, ready, enabled=self.settings.auto_presence,
                                               paused=paused, input_age=input_age, locked=locked)
            if previous_countdown is None and self.presence.countdown_until is not None:
                self.countdown_input_token = self.last_input_token
            if self.input_wake_requested and self.presence.owns_off and power_action is None:
                power_action = self.presence.request_wake(now)
            if not self.presence.owns_off and self.presence.pending != "off":
                self.input_wake_requested = False
            actions = []
            if power_action == "off" and self.brightness_pending:
                self.presence.pending = None
            elif power_action:
                actions.append({"kind": power_action, "id": uuid.uuid4().hex, "epoch": self.epoch,
                                "countdown_until": self.presence.countdown_until})
            if self.guard and self.presence.owns_off:
                if not self.guard.alive():
                    self.sensors.invalidate("독립 복귀 안전장치 종료")
                elif self._safe_off(now, input_age, locked) and now - self.last_pulse >= 1:
                    self.guard.pulse()
                    self.last_pulse = now
            if (self.settings.auto_brightness and ready and not paused and not locked and backend_ready and self.monitor_id
                    and not self.presence.owns_off and self.presence.pending != "off"
                    and not self.brightness_pending and now >= self.brightness_retry):
                value = self.brightness.propose(now)
                if value is not None:
                    self.brightness_pending = True
                    actions.append({"kind": "brightness", "percent": value, "monitor_id": self.monitor_id,
                                    "epoch": self.epoch, "id": uuid.uuid4().hex})
            state = (self.presence.state.value, self.presence.reason)
            if state != self.last_state:
                self.log.event("presence_state", state=state[0], reason=state[1],
                    auto_presence=self.settings.auto_presence, paused=paused, locked=locked,
                    input_age_seconds=round(input_age, 1) if input_age is not None else None,
                    input_protection=self.settings.use_recent_input, recent_input_seconds=self.settings.recent_input_seconds,
                    sensor_valid=snap.valid, sensor_ready=ready, sensor_reason=snap.reason,
                    presence=snap.packet.get("presence") if snap.packet else None,
                    distance_cm=snap.packet.get("distance_cm") if snap.packet else None,
                    tof_raw_status=snap.packet.get("tof_raw_status") if snap.packet else None,
                    tof_no_target=snap.packet.get("tof_no_target", False) if snap.packet else False,
                    tof_acquisition_ok=snap.packet.get("tof_acquisition_ok", False) if snap.packet else False,
                    absence_seconds=self.settings.absence_seconds,
                    tof_min_distance_cm=self.settings.tof_min_distance_cm, tof_max_distance_cm=self.settings.tof_max_distance_cm)
                self.last_state = state
            return actions

    def perform(self, action, backend=None):
        kind = action["kind"]
        success = False
        result = None
        error = ""
        cancelled = False
        guard = None
        try:
            with self.lock:
                now = self.clock()
                if kind == "off":
                    if (action.get("countdown_until", self.presence.countdown_until) != self.presence.countdown_until
                            or not self._safe_off(now, self.input_provider(), self.locked_provider(), require_countdown=True)):
                        raise OffCancelled("입력·감지 변경으로 화면 꺼짐 취소")
                elif kind == "brightness":
                    if (action["epoch"] != self.epoch or not self.settings.auto_brightness or self.external_block
                            or now < self.pause_until or now < self.brightness.pause_until or not self.sensors.ready(now)
                            or self.presence.owns_off or self.locked_provider()):
                        raise RuntimeError("밝기 요청 취소: 제어 조건 변경")
            if kind == "off":
                guard = self.guard_factory(self.log.root, self.settings.production_wake_method, self.settings.allow_mouse)
                guard.arm()
                self.guard = guard
                with self.lock:
                    if not self._safe_off(self.clock(), self.input_provider(), self.locked_provider(), require_countdown=True):
                        raise OffCancelled("안전장치 준비 중 입력·감지 변경으로 화면 꺼짐 취소")
                result = self.power.off()
            elif kind == "wake":
                try:
                    result = self.power.wake(self.settings.production_wake_method, self.settings.allow_mouse)
                except Exception as first:
                    self.log.event("auto_wake_primary_error", error=str(first))
                    fallback = "monitor_power" if self.settings.production_wake_method != "monitor_power" else "execution_state"
                    result = self.power.wake(fallback, False)
                if self.guard:
                    self.guard.release()
                    self.guard = None
            else:
                if backend is None:
                    raise RuntimeError("밝기 백엔드 없음")
                result = backend.set_brightness(action["monitor_id"], action["percent"])
            success = True
        except OffCancelled as exception:
            cancelled = True
            error = str(exception)
            if guard is not None:
                try:
                    guard.release()
                except Exception as release_error:
                    self.log.event("cancelled_off_guard_release_error", error=str(release_error))
                if self.guard is guard:
                    self.guard = None
        except Exception as exception:
            error = str(exception)
        with self.lock:
            if kind == "brightness":
                self.brightness_pending = False
                if success and action["epoch"] == self.epoch:
                    self.brightness.sent(action["percent"], self.clock())
                elif not success:
                    self.brightness_retry = self.clock() + 5
            elif cancelled:
                self.presence.pending = None
                self.observe_input(self.clock())
                self.presence.cancel(self.clock())
            else:
                self.presence.completed(kind, success, self.clock())
            self.last_action = f"{kind}: {'요청 접수' if success else error}"
            return self.log.event("automation_result", action=action, ok=success, result=result, error=error,
                                  cancelled=cancelled,
                                  physical_result="unverified")

    def shutdown(self):
        self.external_block = True
        # Leave an owned-off lease to expire if normal wake cannot be completed.
        if self.presence.owns_off:
            self.perform({"kind": "wake", "id": uuid.uuid4().hex, "epoch": self.epoch})
