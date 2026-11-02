from types import SimpleNamespace

from windows.core.automation import AutomationRuntime
from windows.core.diagnostics import Diagnostics
from windows.core.settings import Settings


class Guard:
    instances = []
    def __init__(self, *args):
        self.armed = self.released = False
        self.pulses = 0
        Guard.instances.append(self)
    def arm(self):
        self.armed = True
    def release(self):
        self.released = True
    def alive(self):
        return not self.released
    def pulse(self):
        self.pulses += 1


def sample(seq, now, presence=False, **changes):
    return {"packet": {"ver": 1, "type": "telemetry", "device": "smart-monitor-s3", "seq": seq,
            "uptime_ms": int((now + 1) * 1000), "sensor_ok": True, "radar_ok": True, "light_ok": True,
            "lux": 500, "presence": presence, "moving": False, "stationary": presence,
            "distance_cm": 60 if presence else None, **changes}, "received_at": now}


def make_runtime(tmp_path, **changes):
    now = [0]
    calls = []
    settings = Settings(auto_presence=True, absence_seconds=5, stabilization_seconds=1, **changes)
    runtime = AutomationRuntime(settings, Diagnostics(tmp_path),
        SimpleNamespace(off=lambda: calls.append("off"), wake=lambda *args: calls.append("wake")),
        clock=lambda: now[0], guard_factory=Guard, input_provider=lambda: 1000, locked_provider=lambda: False)
    return runtime, now, calls


def advance(runtime, now, start, end, presence=False):
    results = []
    for t in range(start, end + 1):
        now[0] = t
        runtime.ingest(sample(t + 1, t, presence))
        for action in runtime.tick(t, 1000, False, False):
            results.append(runtime.perform(action))
    return results


def test_automatic_off_lease_and_immediate_redetection_wake(tmp_path):
    runtime, now, calls = make_runtime(tmp_path)
    advance(runtime, now, 0, 11)
    assert calls == ["off"] and runtime.guard.armed
    advance(runtime, now, 12, 20)
    guard = runtime.guard
    assert guard.pulses > 0 and calls == ["off"]
    advance(runtime, now, 21, 21, True)
    assert calls == ["off", "wake"] and guard.released and not runtime.presence.owns_off


def test_disconnect_after_off_wakes_and_does_not_repeat_off(tmp_path):
    runtime, now, calls = make_runtime(tmp_path)
    advance(runtime, now, 0, 11)
    runtime.sensor_status({"connected": False, "message": "USB unplugged"})
    for t in range(12, 30):
        now[0] = t
        for action in runtime.tick(t, 1000, False, False):
            runtime.perform(action)
    assert calls == ["off", "wake"]


def test_off_guard_rechecks_input_at_execution(tmp_path):
    runtime, now, calls = make_runtime(tmp_path)
    advance(runtime, now, 0, 10)
    now[0] = 11
    runtime.ingest(sample(12, 11))
    action, = runtime.tick(11, 1000, False, False)
    runtime.input_provider = lambda: 0
    assert not runtime.perform(action)["ok"]
    assert not calls


def test_brightness_pending_is_invalidated_by_manual_pause(tmp_path):
    runtime, now, calls = make_runtime(tmp_path, auto_brightness=True, monitor_id="target")
    runtime.set_monitor("target", 20)
    for t in range(3):
        now[0] = t
        runtime.ingest(sample(t + 1, t, True))
    action, = runtime.tick(2, 1000, False, True)
    runtime.manual_brightness(40)
    backend_calls = []
    result = runtime.perform(action, SimpleNamespace(set_brightness=lambda *args: backend_calls.append(args)))
    assert not result["ok"] and not backend_calls


def test_primary_wake_failure_uses_non_input_fallback(tmp_path):
    runtime, now, calls = make_runtime(tmp_path)
    advance(runtime, now, 0, 11)
    def wake(method, allow_mouse):
        calls.append(method)
        if method == "execution_state":
            raise OSError("primary failure")
    runtime.power.wake = wake
    advance(runtime, now, 12, 12, True)
    assert calls == ["off", "execution_state", "monitor_power"]
