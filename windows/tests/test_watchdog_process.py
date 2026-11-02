import json
import subprocess
import sys
import time


def test_recovery_survives_owner_exit_without_controlling_display(tmp_path):
    # Actual subprocess handshake and owner exit; the recovery API is simulated.
    script = """
import os, sys
from pathlib import Path
from windows.core.watchdog import arm_watchdog
arm_watchdog(Path(sys.argv[1]), 'owner-exit-test', 'monitor_power', 5, False, 5, simulate=True)
os._exit(0)
"""
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], timeout=8, capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    events = []
    deadline = time.monotonic() + 14
    while time.monotonic() < deadline:
        for path in tmp_path.glob("events-*.jsonl"):
            events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        if any(event["event"] == "recovery_finished" for event in events):
            break
        time.sleep(0.1)
    attempts = [event for event in events if event["event"] == "wake_attempt"]
    assert [event["stage"] for event in attempts] == ["primary", "fallback"]
    assert all(event["result"]["simulated"] for event in attempts)
    assert next(event for event in events if event["event"] == "watchdog_ready")["fallback_seconds"] == 5
    from datetime import datetime
    assert (datetime.fromisoformat(attempts[1]["time"]) - datetime.fromisoformat(attempts[0]["time"])).total_seconds() >= 5
    assert events[-1]["event"] == "recovery_finished"
