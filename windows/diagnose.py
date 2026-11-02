"""Explicit hardware tests. Default action is read-only inventory."""
import argparse
from dataclasses import asdict
import json
import time
import uuid

from windows.core.brightness import TwinkleTrayBackend, discover_twinkle
from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController
from windows.core.power import WAKE_METHODS, WindowsPower


def brightness_sweep(backend, monitor, log, sleep=time.sleep):
    if monitor.brightness is None or not float(monitor.brightness).is_integer():
        raise ValueError("기존 밝기를 복원할 수 없어 시험을 중단합니다.")
    test_id = uuid.uuid4().hex
    log.event("sweep_started", test_id=test_id, monitor=asdict(monitor))
    try:
        for percent in (20, 50, 80):
            backend.set_brightness(monitor.identifier, percent)
            sleep(2)
            reported = next(m for m in backend.monitors() if m.identifier == monitor.identifier)
            log.event("sweep_sample", test_id=test_id, requested=percent, reported=reported.brightness,
                      physical_result="unverified")
            print(f"밝기 {percent}% 요청 / Twinkle Tray 보고 {reported.brightness}%", flush=True)
    finally:
        backend.set_brightness(monitor.identifier, int(monitor.brightness))
        sleep(2)
        restored = next(m for m in backend.monitors() if m.identifier == monitor.identifier)
        log.event("brightness_restored", test_id=test_id, requested=monitor.brightness, reported=restored.brightness)
        if restored.brightness != monitor.brightness:
            raise RuntimeError("Twinkle Tray 보고 밝기가 원래 값과 다릅니다. 수동 확인이 필요합니다.")
    print(f"기존 밝기 {monitor.brightness}% 복원 요청 완료. 시험 ID: {test_id}", flush=True)
    return test_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--twinkle-path", default="")
    parser.add_argument("--monitor-id", default="")
    parser.add_argument("--monitor-name", default="")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--brightness-sweep", action="store_true")
    actions.add_argument("--sleep-test", action="store_true")
    actions.add_argument("--wake-only", action="store_true")
    actions.add_argument("--record", choices=("pass", "fail", "unverified"))
    parser.add_argument("--method", choices=WAKE_METHODS, default="monitor_power")
    parser.add_argument("--seconds", type=int, default=10)
    parser.add_argument("--allow-mouse", action="store_true")
    parser.add_argument("--test-id", default="")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()
    log = Diagnostics()
    try:
        if args.record:
            if not args.test_id:
                raise ValueError("--test-id 필요")
            log.event("user_observation", test_id=args.test_id, result=args.record, notes=args.notes)
        elif args.sleep_test or args.wake_only:
            if not 5 <= args.seconds <= 30:
                raise ValueError("--seconds는 5~30")
            if args.method == "mouse_move" and not args.allow_mouse:
                raise ValueError("--allow-mouse 필요")
            power = WindowsPower()
            if args.wake_only:
                print(json.dumps(log.event("manual_wake", test_id=uuid.uuid4().hex, method=args.method,
                                           result=power.wake(args.method, args.allow_mouse)), ensure_ascii=False))
            else:
                controller = DisplayController(power, log)
                controller.start()
                try:
                    while time.monotonic() < controller.deadline:
                        print(f"전체 화면 절전까지 {max(1, round(controller.deadline - time.monotonic()))}초 / Ctrl+C로 취소", flush=True)
                        time.sleep(1)
                except KeyboardInterrupt:
                    controller.cancel()
                    print("절전 시험 취소")
                    return 0
                print(f"시험 ID: {controller.test_id} / {args.seconds}초 후 1차 복귀 요청", flush=True)
                controller.execute(args.method, args.seconds, args.allow_mouse)
                # Only waits for the independent helper's bounded request window.
                time.sleep(args.seconds + 16)
                controller.finish()
                print("복귀 시도 시간 경과. 화면의 실제 결과는 별도로 기록하세요.", flush=True)
        else:
            exe = discover_twinkle(args.twinkle_path)
            if not exe:
                raise FileNotFoundError("Twinkle Tray 실행 파일을 찾지 못했습니다.")
            backend = TwinkleTrayBackend(exe, log)
            monitors = backend.monitors()
            print(json.dumps({"executable": str(exe), "monitors": [asdict(m) for m in monitors]}, ensure_ascii=False, indent=2))
            if args.brightness_sweep:
                selected = [m for m in monitors if (args.monitor_id and m.identifier == args.monitor_id)
                            or (not args.monitor_id and args.monitor_name and m.name == args.monitor_name)]
                if len(selected) != 1:
                    raise ValueError("--monitor-id 또는 정확한 --monitor-name으로 한 대를 선택하세요.")
                brightness_sweep(backend, selected[0], log)
        return 0
    except Exception as error:
        log.event("diagnostic_error", error=str(error))
        print(f"오류: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
