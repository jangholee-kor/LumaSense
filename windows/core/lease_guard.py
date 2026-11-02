"""Independent crash/stall recovery while an automatic-off lease is active."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from .diagnostics import Diagnostics
from .power import WindowsPower
from .processes import helper_command, process_cwd
from .watchdog import recovery_sequence


class LeaseGuard:
    def __init__(self, root, method="execution_state", allow_mouse=False, simulate=False):
        self.root = Path(root)
        self.method, self.allow_mouse, self.simulate = method, allow_mouse, simulate
        self.token = uuid.uuid4().hex
        self.path = self.root / f"lease-{self.token}.json"
        self.ready = self.path.with_suffix(".ready")
        self.finished = self.path.with_suffix(".finished")
        self.process = None

    def pulse(self, ttl=5):
        value = {"expires": time.monotonic() + ttl, "released": False}
        self._write(value)

    def _write(self, value):
        temp = self.path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            temp.write_text(json.dumps(value), encoding="utf-8")
            # Windows may briefly deny replace while the helper reads the file.
            for attempt in range(6):
                try:
                    temp.replace(self.path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.02)
        finally:
            temp.unlink(missing_ok=True)

    def arm(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.pulse(10)
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        command = helper_command("windows.core.lease_guard", "--lease", str(self.path), "--method", self.method,
                                 *( ["--allow-mouse"] if self.allow_mouse else []), *( ["--simulate"] if self.simulate else []))
        self.process = subprocess.Popen(command, cwd=process_cwd(), stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if self.ready.exists():
                self.ready.unlink(missing_ok=True)
                return
            if self.process.poll() is not None:
                break
            time.sleep(.05)
        raise RuntimeError("자동 절전 복귀 감시 프로세스 준비 실패")

    def alive(self):
        return self.process is not None and self.process.poll() is None and not self.finished.exists()

    def release(self):
        # Do not kill the helper. A release tells it the normal wake request succeeded.
        self._write({"released": True})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lease", type=Path, required=True)
    parser.add_argument("--method", default="execution_state", choices=("execution_state", "monitor_power", "mouse_move"))
    parser.add_argument("--allow-mouse", action="store_true")
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args()
    log = Diagnostics(args.lease.parent)
    class SimulatedPower:
        def wake(self, method, allow_mouse):
            return {"simulated": True, "accepted": False, "physical_result": "unverified"}
    power = SimulatedPower() if args.simulate else WindowsPower()
    ready = args.lease.with_suffix(".ready")
    finished = args.lease.with_suffix(".finished")
    expires = time.monotonic() + 10
    ready.write_text("ready", encoding="utf-8")
    try:
        while True:
            try:
                value = json.loads(args.lease.read_text(encoding="utf-8"))
                if value.get("released"):
                    log.event("lease_released", token=args.lease.stem)
                    break
                candidate = value.get("expires")
                # A GUI lease may only extend a bounded interval into the future.
                if type(candidate) in (int, float) and time.monotonic() - 60 < candidate <= time.monotonic() + 15:
                    expires = candidate
            except (OSError, ValueError):
                pass
            if time.monotonic() >= expires:
                log.event("lease_expired", token=args.lease.stem)
                recovery_sequence(power, log, args.lease.stem, args.method, args.allow_mouse, fallback_seconds=5)
                break
            time.sleep(.2)
    finally:
        finished.write_text("finished", encoding="utf-8")
        args.lease.unlink(missing_ok=True)
        ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
