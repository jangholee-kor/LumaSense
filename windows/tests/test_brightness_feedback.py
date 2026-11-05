import json
import subprocess

import pytest

from windows.core.brightness import Monitor, TwinkleTrayBackend
from windows.tests.test_automation_runtime import make_runtime, sample


class Backend:
    def __init__(self, *, apply=True):
        self.value = 1
        self.apply = apply
        self.writes = []
        self.reads = 0
        self.error = None

    def monitors(self):
        self.reads += 1
        if self.error:
            raise self.error
        return [Monitor("target", "Test", self.value, "ddcci")]

    def set_brightness(self, identifier, percent, *, before_send=None):
        if before_send:
            before_send()
        self.writes.append(percent)
        if self.error:
            raise self.error
        if self.apply:
            self.value = percent
        return {"accepted": True, "physical_result": "unverified"}


class Harness:
    def __init__(self, tmp_path, **changes):
        options = dict(auto_brightness=True, brightness_mode="two_level", monitor_id="target", light_off_brightness=1)
        self.runtime, self.now, self.power_calls = make_runtime(tmp_path, **{**options, **changes})
        self.backend = Backend()
        self.seq = 0

    def observe(self, t, lux=423.3):
        self.now[0] = t
        self.seq += 1
        self.runtime.ingest(sample(self.seq, t, True, lux=lux))

    def actions(self):
        return self.runtime.tick(self.now[0], 0, False, True)

    def at(self, t, lux=423.3):
        self.observe(t, lux)
        actions = self.actions()
        return [self.runtime.perform(a, self.backend) for a in actions]

    def start(self):
        assert not self.at(0)
        assert self.at(1)[0]["ok"]
        assert self.backend.writes == [55]


def events(root):
    return [json.loads(line) for p in root.glob("events-*.jsonl")
            for line in p.read_text(encoding="utf-8").splitlines()]


def test_recheck_after_two_and_eight_seconds_and_detect_later_reversion(tmp_path):
    h = Harness(tmp_path)
    h.start()
    assert not h.at(2)
    assert h.at(3)[0]["action"]["kind"] == "brightness_verify"
    assert h.backend.writes == [55]
    for t in range(4, 9):
        assert not h.at(t)
    assert h.at(9)[0]["ok"]
    for t in range(10, 39):
        assert not h.at(t)
    h.backend.value = 1
    assert h.at(39)[0]["ok"]  # Read succeeded, report still disagrees.
    assert h.runtime.brightness_feedback.retry_pending
    assert not h.at(40)
    assert h.at(41)[0]["ok"]
    assert h.backend.writes == [55, 55]
    assert h.at(43)[0]["ok"]
    assert h.runtime.brightness_feedback.reported == 55
    assert "실제 화면 미확인" in h.runtime.brightness_feedback.status
    verification = [e for e in events(tmp_path) if e["event"] == "brightness_verification"]
    assert any(e["expected"] == 55 and e["reported"] == 1 and e["lux"] == 423.3 for e in verification)
    assert all(e["physical_result"] == "unverified" for e in verification)


def test_persistent_mismatch_stops_after_two_retries_until_explicit_resume(tmp_path):
    h = Harness(tmp_path)
    h.backend.apply = False
    h.start()
    for t in range(2, 40):
        h.at(t)
    assert h.backend.writes == [55, 55, 55]
    assert h.backend.reads == 3
    assert h.runtime.brightness_feedback.exhausted
    assert "재시도 종료" in h.runtime.brightness_feedback.status
    h.runtime.resume()
    h.at(40)
    h.at(41)
    h.at(42)
    h.at(44)
    assert len(h.backend.writes) == 4


def test_failed_writes_are_also_bounded(tmp_path):
    h = Harness(tmp_path)
    h.backend.error = TimeoutError("CLI timeout")
    h.at(0)
    for t in range(1, 30):
        h.at(t)
    assert h.backend.writes == [55, 55, 55]
    assert not h.backend.reads
    assert h.runtime.brightness_feedback.exhausted


@pytest.mark.parametrize("report", [None, "exception"])
def test_unknown_reports_retry_reads_without_writes(tmp_path, report):
    h = Harness(tmp_path)
    h.start()
    if report == "exception":
        h.backend.error = TimeoutError("inventory timeout")
    else:
        h.backend.value = None
    for t in range(2, 30):
        h.at(t)
    assert h.backend.writes == [55]
    assert h.backend.reads == 3
    assert h.runtime.brightness_feedback.exhausted


def test_queued_dark_request_cancelled_during_light_switch_dwell(tmp_path):
    h = Harness(tmp_path)
    h.start()
    h.at(2, 0)
    h.observe(3, 0)
    action, = h.actions()
    assert action["percent"] == 1
    h.observe(3.1, 423.3)
    result = h.runtime.perform(action, h.backend)
    assert result["cancelled"] and not result["ok"]
    assert h.backend.writes == [55]
    assert not h.runtime.brightness_pending
    assert not h.at(3.5)
    h.at(4.2)
    assert 1 not in h.backend.writes


def test_recheck_after_inventory_prevents_stale_cli_set(tmp_path):
    h = Harness(tmp_path)
    h.start()
    h.at(2, 0)
    h.observe(3, 0)
    action, = h.actions()
    commands = []

    def runner(command, **kwargs):
        commands.append(command)
        if len(commands) == 2:
            h.observe(3.1, 423.3)
        return subprocess.CompletedProcess(command, 0,
            "MonitorNum: 0\nMonitorID: target\nName: Test\nBrightness: 55\nType: ddcci\n", "")

    backend = TwinkleTrayBackend(tmp_path / "fake.exe", h.runtime.log, runner)
    assert h.runtime.perform(action, backend)["cancelled"]
    assert len(commands) == 2 and all(c[-1] == "--List" for c in commands)


@pytest.mark.parametrize("condition", ["manual", "pause", "locked", "disabled", "off", "off_pending", "stale", "monitor", "settings", "reconnect"])
def test_pending_verification_respects_control_changes(tmp_path, condition):
    h = Harness(tmp_path)
    h.start()
    h.observe(3)
    action, = h.actions()
    r = h.runtime
    if condition == "manual": r.manual_brightness(30)
    elif condition == "pause": r.pause()
    elif condition == "locked": r.locked_provider = lambda: True
    elif condition == "disabled": r.settings.auto_brightness = False
    elif condition == "off": r.presence.owns_off = True
    elif condition == "off_pending": r.presence.pending = "off"
    elif condition == "stale": h.now[0] = 7
    elif condition == "monitor": r.set_monitor("other", 30)
    elif condition == "settings": r.apply_settings(r.settings)
    elif condition == "reconnect": r.sensor_status({"connected": False})
    result = r.perform(action, h.backend)
    assert result["cancelled"] and not h.backend.reads
    assert not r.brightness_pending


def test_inflight_read_result_cannot_schedule_old_target_retry(tmp_path):
    h = Harness(tmp_path)
    h.start()
    h.observe(3)
    action, = h.actions()

    def changed_inventory():
        h.runtime.manual_brightness(30)
        return [Monitor("target", "Test", 1, "ddcci")]

    h.backend.monitors = changed_inventory
    assert h.runtime.perform(action, h.backend)["cancelled"]
    assert not h.runtime.brightness_feedback.retry_pending
    assert h.runtime.brightness.requested == 30


def test_wake_reapplies_same_target_after_settle_without_overriding_manual_pause(tmp_path):
    h = Harness(tmp_path)
    h.start()
    h.runtime.presence.owns_off = True
    h.runtime.perform({"kind": "wake", "epoch": h.runtime.epoch, "id": "wake"})
    assert not h.at(2)
    assert h.at(3)[0]["action"]["kind"] == "brightness"
    assert h.backend.writes == [55, 55]
    h.runtime.manual_brightness(30)
    h.runtime.perform({"kind": "wake", "epoch": h.runtime.epoch, "id": "wake2"})
    for t in range(4, 10):
        assert not h.at(t)
    assert h.backend.writes == [55, 55]


def test_retry_waits_for_configured_command_interval(tmp_path):
    h = Harness(tmp_path, brightness_interval=10)
    h.backend.apply = False
    h.start()
    for t in range(2, 11):
        h.at(t)
    assert h.backend.writes == [55]
    h.at(11)
    assert h.backend.writes == [55, 55]


@pytest.mark.parametrize("mode", ["two_level", "steps", "curve"])
def test_all_brightness_modes_verify_accepted_requests(tmp_path, mode):
    h = Harness(tmp_path, brightness_mode=mode)
    h.at(0)
    result, = h.at(1)
    percent = result["action"]["percent"]
    result, = h.at(3)
    assert result["action"]["kind"] == "brightness_verify"
    assert h.runtime.brightness_feedback.reported == percent
    assert h.backend.writes == [percent]


def test_new_light_target_resets_exhausted_retry_budget(tmp_path):
    h = Harness(tmp_path)
    h.backend.apply = False
    h.start()
    for t in range(2, 12):
        h.at(t)
    assert h.runtime.brightness_feedback.exhausted
    h.at(12, 0)
    h.at(13, 0)
    assert h.backend.writes == [55, 55, 55, 1]
    assert not h.runtime.brightness_feedback.exhausted
    assert h.runtime.brightness_feedback.retries == 0


def test_manual_adjustment_suspends_scheduled_retry(tmp_path):
    h = Harness(tmp_path)
    h.backend.apply = False
    h.start()
    h.at(3)
    assert h.runtime.brightness_feedback.retry_pending
    h.runtime.manual_brightness(30)
    for t in range(4, 10):
        assert not h.at(t)
    assert h.backend.writes == [55]
