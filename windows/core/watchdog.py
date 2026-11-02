"""Detached recovery helper survives the GUI process. Uses only the stdlib."""
import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .diagnostics import Diagnostics
from .power import WAKE_METHODS, WindowsPower


def recovery_sequence(power, diagnostics, test_id, method, allow_mouse, sleep=time.sleep):
    methods = [method, "monitor_power", "execution_state"]
    if allow_mouse:
        methods.append("mouse_move")
    for index, item in enumerate(dict.fromkeys(methods)):
        if index:
            sleep(5)
        try:
            diagnostics.event("wake_attempt", test_id=test_id, stage="primary" if index == 0 else "fallback",
                              method=item, result=power.wake(item, allow_mouse))
        except Exception as error:
            diagnostics.event("wake_error", test_id=test_id, method=item, error=str(error))
    diagnostics.event("recovery_finished", test_id=test_id, physical_result="unverified")


def arm_watchdog(root: Path, test_id: str, method: str, seconds: int, allow_mouse: bool):
    if method not in WAKE_METHODS or not 5 <= seconds <= 30:
        raise ValueError("복귀 설정 범위 오류")
    if method == "mouse_move" and not allow_mouse:
        raise ValueError("마우스 이동 허용 필요")
    root.mkdir(parents=True, exist_ok=True)
    ready = root / f"watchdog-{uuid.uuid4().hex}.ready"
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen([sys.executable, "-m", "windows.core.watchdog", "--root", str(root),
                                "--ready", str(ready), "--test-id", test_id, "--method", method,
                                "--seconds", str(seconds), *( ["--allow-mouse"] if allow_mouse else [])],
                               cwd=Path(__file__).resolve().parents[2], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if ready.exists():
            ready.unlink(missing_ok=True)
            return process.pid
        if process.poll() is not None:
            break
        time.sleep(0.05)
    raise RuntimeError("복귀 안전장치 준비 실패: 화면 절전을 중단합니다.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--test-id", required=True)
    parser.add_argument("--method", choices=WAKE_METHODS, required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--allow-mouse", action="store_true")
    args = parser.parse_args()
    log = Diagnostics(args.root)
    try:
        if not 5 <= args.seconds <= 30:
            raise ValueError("복귀 지연 범위 오류")
        power = WindowsPower()
        log.event("watchdog_ready", test_id=args.test_id, seconds=args.seconds, method=args.method)
        args.ready.write_text(json.dumps({"ready": True}), encoding="utf-8")
        time.sleep(args.seconds)
        recovery_sequence(power, log, args.test_id, args.method, args.allow_mouse)
    except Exception as error:
        log.event("watchdog_error", test_id=args.test_id, error=str(error))
        raise


if __name__ == "__main__":
    main()
