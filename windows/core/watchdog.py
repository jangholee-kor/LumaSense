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
from .processes import helper_command, process_cwd


def recovery_methods(method, allow_mouse):
    if method not in WAKE_METHODS or (method == "mouse_move" and not allow_mouse):
        raise ValueError("복귀 방식과 마우스 허용 설정 오류")
    methods = [method, "monitor_power", "execution_state"]
    if allow_mouse:
        methods.append("mouse_move")
    return list(dict.fromkeys(methods))


def validate_timing(seconds, fallback_seconds):
    if type(seconds) is not int or not 5 <= seconds <= 30:
        raise ValueError("1차 복귀 지연은 5~30초")
    if type(fallback_seconds) is not int or not 5 <= fallback_seconds <= 60:
        raise ValueError("추가 복귀 간격은 5~60초")


def recovery_window_seconds(method, seconds, allow_mouse, fallback_seconds):
    validate_timing(seconds, fallback_seconds)
    return seconds + (len(recovery_methods(method, allow_mouse)) - 1) * fallback_seconds + 15


def recovery_sequence(power, diagnostics, test_id, method, allow_mouse, sleep=time.sleep, fallback_seconds=30):
    validate_timing(5, fallback_seconds)
    for index, item in enumerate(recovery_methods(method, allow_mouse)):
        if index:
            sleep(fallback_seconds)
        try:
            stage = "primary" if index == 0 else "fallback"
            diagnostics.event("wake_request_started", test_id=test_id, stage=stage, method=item,
                              fallback_seconds=fallback_seconds)
            diagnostics.event("wake_attempt", test_id=test_id, stage=stage,
                              method=item, result=power.wake(item, allow_mouse))
        except Exception as error:
            diagnostics.event("wake_error", test_id=test_id, method=item, error=str(error))
    diagnostics.event("recovery_finished", test_id=test_id, physical_result="unverified")


def arm_watchdog(root: Path, test_id: str, method: str, seconds: int, allow_mouse: bool, fallback_seconds=30, *, simulate=False):
    validate_timing(seconds, fallback_seconds)
    recovery_methods(method, allow_mouse)
    root.mkdir(parents=True, exist_ok=True)
    ready = root / f"watchdog-{uuid.uuid4().hex}.ready"
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(helper_command("windows.core.watchdog", "--root", str(root),
                                "--ready", str(ready), "--test-id", test_id, "--method", method,
                                "--seconds", str(seconds), "--fallback-seconds", str(fallback_seconds),
                                *( ["--allow-mouse"] if allow_mouse else []),
                                *( ["--simulate"] if simulate else [])),
                               cwd=process_cwd(), stdin=subprocess.DEVNULL,
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
    parser.add_argument("--fallback-seconds", type=int, default=30)
    parser.add_argument("--allow-mouse", action="store_true")
    parser.add_argument("--simulate", action="store_true", help="장치 제어 없는 안전장치 통합 테스트")
    args = parser.parse_args()
    log = Diagnostics(args.root)
    try:
        validate_timing(args.seconds, args.fallback_seconds)
        recovery_methods(args.method, args.allow_mouse)
        class SimulatedPower:
            def wake(self, method, allow_mouse):
                return {"accepted": False, "simulated": True, "physical_result": "unverified"}
        power = SimulatedPower() if args.simulate else WindowsPower()
        log.event("watchdog_ready", test_id=args.test_id, seconds=args.seconds, method=args.method,
                  fallback_seconds=args.fallback_seconds,
                  first_fallback_after_seconds=args.seconds + args.fallback_seconds)
        args.ready.write_text(json.dumps({"ready": True}), encoding="utf-8")
        time.sleep(args.seconds)
        recovery_sequence(power, log, args.test_id, args.method, args.allow_mouse,
                          fallback_seconds=args.fallback_seconds)
    except Exception as error:
        log.event("watchdog_error", test_id=args.test_id, error=str(error))
        raise


if __name__ == "__main__":
    main()
