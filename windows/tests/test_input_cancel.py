"""Physical input identities cancel off requests independently of input grace settings."""
from types import SimpleNamespace
import pytest
from windows.core.automation import AutomationRuntime
from windows.core.settings import Settings
from windows.core.diagnostics import Diagnostics
from windows.core.simulation import SimulatedGuard
from windows.core.display_controller import DisplayController, State
from windows.tests.test_tof import packet
from windows.tests.test_tof_no_target import missing


def make(tmp_path, mode="simple"):
    now, token, calls = [0], [100], []
    power = SimpleNamespace(off=lambda: calls.append("off"), wake=lambda *args: calls.append("wake"))
    model = AutomationRuntime(Settings(ui_mode=mode, auto_presence=True, use_recent_input=False,
                                       absence_seconds=5), Diagnostics(tmp_path), power,
                              clock=lambda: now[0], guard_factory=SimulatedGuard,
                              input_provider=lambda: 1000, locked_provider=lambda: False,
                              input_token_provider=lambda: token[0])
    return model, now, token, calls


def step(model, now, t):
    now[0] = t
    value = packet(t + 1) if t < 6 else missing(t + 1)
    model.ingest({"packet": value, "received_at": t})
    return model.tick(t, 1000, False, False)


@pytest.mark.parametrize("mode", ["simple", "advanced"])
@pytest.mark.parametrize("display_enabled", [True, False])
def test_input_cancels_countdown_without_fifteen_minute_pause_and_restarts_absence(tmp_path, mode, display_enabled):
    model, now, token, calls = make(tmp_path, mode)
    model.settings.countdown_enabled = display_enabled
    # Advanced mode has one second ToF dwell, so wait until its countdown begins.
    t = 0
    while model.presence.countdown_until is None:
        assert not step(model, now, t)
        t += 1
    token[0] += 1
    assert not step(model, now, t)
    assert model.presence.countdown_until is None and model.pause_until == 0
    assert model.presence.absent_since == t and not model.settings.use_recent_input
    for later in range(t + 1, t + 10):
        assert not step(model, now, later)
    actions = step(model, now, t + 10)
    assert actions[0]["kind"] == "off" and model.perform(actions[0])["ok"]
    assert calls == ["off"]


def test_continuous_new_input_keeps_absence_wait_from_expiring(tmp_path):
    model, now, token, calls = make(tmp_path)
    for t in range(30):
        token[0] += 1
        assert not step(model, now, t)
        assert model.presence.countdown_until is None
    assert not calls


@pytest.mark.parametrize("race", ["queued", "guard_start", "input_unknown"])
def test_input_before_output_cancels_without_error_latch_or_power_call(tmp_path, race):
    model, now, token, calls = make(tmp_path)
    for t in range(17):
        actions = step(model, now, t)
    assert actions[0]["kind"] == "off"
    guards = []
    if race == "guard_start":
        class Guard(SimulatedGuard):
            def arm(self):
                token[0] += 1
                guards.append(self)
        model.guard_factory = Guard
    elif race == "input_unknown":
        token[0] = None
    else:
        token[0] += 1
    result = model.perform(actions[0])
    assert result["cancelled"] and not result["ok"] and not calls
    assert not model.presence.off_failed and model.presence.countdown_until is None
    assert model.presence.pending is None and model.guard is None
    assert all(g.released for g in guards)


@pytest.mark.parametrize("when", ["after_off", "inside_off"])
def test_input_wakes_owned_display_even_without_recent_input_protection(tmp_path, when):
    model, now, token, calls = make(tmp_path)
    for t in range(17):
        actions = step(model, now, t)
    if when == "inside_off":
        def off():
            calls.append("off")
            token[0] += 1
        model.power.off = off
    model.perform(actions[0])
    assert model.presence.owns_off
    if when == "after_off": token[0] += 1
    actions = step(model, now, 17)
    assert actions[0]["kind"] == "wake"
    model.perform(actions[0])
    assert calls == ["off", "wake"] and not model.presence.owns_off


@pytest.mark.parametrize("when", ["before_guard", "after_guard"])
def test_manual_output_rechecks_activity_before_power_api(tmp_path, when):
    now, changed, calls = [0], [False], []
    def arm(*args):
        calls.append("guard")
        if when == "after_guard": changed[0] = True
    controller = DisplayController(SimpleNamespace(off=lambda: calls.append("off")),
                                   Diagnostics(tmp_path), lambda: now[0], arm)
    controller.cancel_check = lambda: changed[0]
    controller.start(); now[0] = 5
    if when == "before_guard": changed[0] = True
    assert controller.execute("monitor_power", 5, False)["cancelled"]
    assert controller.state == State.IDLE and "off" not in calls
