"""Accelerated 24-hour control-model simulation; no physical device access."""
import argparse
import gc
import json
from pathlib import Path
import time
import tracemalloc

from windows.core.automation import AutomationRuntime
from windows.core.diagnostics import Diagnostics
from windows.core.settings import Settings
from windows.core.simulation import SimulatedBackend, SimulatedPower, SimulatedGuard, sensor_packet


def run(root, hours=24, step=.2):
    root.mkdir(parents=True, exist_ok=False)
    settings = Settings(auto_brightness=True, auto_presence=True, monitor_id="SIMULATED-DISPLAY")
    now = [0.0]
    log = Diagnostics(root)
    runtime = AutomationRuntime(settings, log, SimulatedPower(), clock=lambda: now[0], guard_factory=SimulatedGuard,
                                input_provider=lambda: 1000, locked_provider=lambda: False)
    backend = SimulatedBackend(log)
    runtime.set_monitor("SIMULATED-DISPLAY", 40)
    actions = {"brightness": 0, "off": 0, "wake": 0}
    duration = hours * 3600
    start = time.monotonic()
    tracemalloc.start()
    gc.collect()
    baseline = tracemalloc.get_traced_memory()[0]
    for index in range(int(duration / step)):
        t = round(index * step, 3)
        now[0] = t
        cycle = t % 600
        state = "stationary" if cycle < 300 or cycle >= 510 else "absent"
        error = 480 <= cycle < 510
        lux = (20, 125, 500, 1000)[int(t // 60) % 4]
        runtime.ingest({"packet": sensor_packet(index, int(t * 1000), lux, state, error), "received_at": t})
        if index and index % 18000 == 0:
            runtime.manual_brightness(40)
            backend.set_brightness("SIMULATED-DISPLAY", 40)
        for action in runtime.tick(t, 1000, False, True):
            if action["kind"] == "off":
                assert not error and state == "absent" and runtime.sensors.ready(t)
            result = runtime.perform(action, backend)
            assert result["ok"], result
            actions[action["kind"]] += 1
    runtime.shutdown()
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    growth = current - baseline
    assert growth < 8_000_000, f"Unexpected Python allocation growth: {growth}"
    assert actions["off"] > 0 and actions["wake"] == actions["off"]
    report = {"simulated_hours": hours, "samples": int(duration / step), "step_seconds": step,
              "wall_seconds": round(time.monotonic() - start, 3), "python_alloc_growth_bytes": growth,
              "python_peak_bytes": peak, "actions": actions, "pass": True,
              "scope": "accelerated_control_models_only", "real_24h_run": "not_run", "physical_validation": "not_run"}
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=float, default=24)
    parser.add_argument("--step", type=float, default=.2)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not .2 <= args.hours <= 72 or not .1 <= args.step <= 1:
        parser.error("hours .2~72 and step .1~1 required")
    print(json.dumps(run(args.output, args.hours, args.step), indent=2))


if __name__ == "__main__":
    main()
