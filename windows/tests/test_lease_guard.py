import json
from pathlib import Path
import subprocess
import sys
import time

from windows.core.lease_guard import LeaseGuard


def test_lease_release_does_not_send_wake(tmp_path):
    guard = LeaseGuard(tmp_path, simulate=True)
    guard.arm()
    guard.release()
    guard.process.wait(timeout=4)
    records = [json.loads(line) for p in tmp_path.glob("events-*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]
    assert not any(r["event"] == "wake_request_started" for r in records)
    assert guard.finished.exists()


def test_lease_wakes_after_owner_process_exits(tmp_path):
    code = """
from pathlib import Path
import os,sys
from windows.core.lease_guard import LeaseGuard
guard=LeaseGuard(Path(sys.argv[1]),simulate=True)
guard.arm()
guard.pulse(.5)
os._exit(0)
"""
    owner = subprocess.run([sys.executable, "-c", code, str(tmp_path)], timeout=8, capture_output=True)
    assert owner.returncode == 0, owner.stderr.decode(errors="replace")
    deadline = time.monotonic() + 9
    while time.monotonic() < deadline and not list(tmp_path.glob("*.finished")):
        time.sleep(.1)
    assert list(tmp_path.glob("*.finished"))
    records = [json.loads(line) for p in tmp_path.glob("events-*.jsonl") for line in p.read_text(encoding="utf-8").splitlines()]
    assert any(r["event"] == "lease_expired" for r in records)
    assert len([r for r in records if r["event"] == "wake_attempt"]) == 2
    assert all(r["result"]["simulated"] for r in records if r["event"] == "wake_attempt")


def test_windows_temporary_replace_denial_is_retried(tmp_path, monkeypatch):
    guard = LeaseGuard(tmp_path, simulate=True)
    original = Path.replace
    calls = []
    def replace(path, target):
        calls.append(path)
        if len(calls) == 1:
            raise PermissionError("reader temporarily holds file")
        return original(path, target)
    monkeypatch.setattr(Path, "replace", replace)
    guard.pulse()
    assert len(calls) == 2 and guard.path.exists()
    assert not list(tmp_path.glob("*.tmp"))
