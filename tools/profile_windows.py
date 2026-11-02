"""Real-time GUI simulation with read-only Windows CPU/RSS measurement."""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import hashlib

from windows.core.settings import Settings


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                *[(name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                  "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]]


def metrics(handle):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(ctypes.c_uint64)] * 4]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    values = [ctypes.c_uint64() for _ in range(4)]
    memory = MemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    if not kernel.GetProcessTimes(handle, *[ctypes.byref(value) for value in values]):
        raise ctypes.WinError(ctypes.get_last_error())
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), ctypes.sizeof(memory)):
        raise ctypes.WinError(ctypes.get_last_error())
    return {"cpu_seconds": (values[2].value + values[3].value) / 10_000_000,
            "rss_bytes": memory.WorkingSetSize, "peak_rss_bytes": memory.PeakWorkingSetSize}


def run(root, seconds, executable):
    root.mkdir(parents=True, exist_ok=False)
    Settings(auto_brightness=True, auto_presence=True, monitor_id="SIMULATED-DISPLAY").save(root / "simulation/settings.json")
    command = [str(executable)]
    command += ["--simulate", "--simulation-seconds", str(seconds)]
    env = {**os.environ, "SMC_DATA_DIR": str(root), "QT_QPA_PLATFORM": "offscreen"}
    start = time.monotonic()
    samples = []
    with (root / "console.log").open("w", encoding="utf-8") as console:
        child = subprocess.Popen(command, env=env, stdout=console, stderr=console,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with (root / "resources.jsonl").open("w", encoding="utf-8") as output:
                while child.poll() is None:
                    if time.monotonic() - start > seconds + 30:
                        raise TimeoutError("GUI simulation did not exit")
                    sample = {"elapsed_seconds": time.monotonic() - start, **metrics(int(child._handle))}
                    samples.append(sample)
                    output.write(json.dumps(sample) + "\n")
                    output.flush()
                    time.sleep(1)
            assert child.returncode == 0, f"GUI exit {child.returncode}; see console.log"
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=10)
    assert samples
    events = [json.loads(line) for path in (root / "simulation").glob("events-*.jsonl")
              for line in path.read_text(encoding="utf-8").splitlines()]
    assert any(e["event"] == "app_stopped" and e["code"] == 0 for e in events)
    assert any(e["event"] == "simulated_brightness" for e in events)
    assert not any(e["event"] in ("unhandled_exception", "twinkle_cli") for e in events)
    wall = time.monotonic() - start
    assert wall >= seconds - .5, "GUI exited before the requested duration"
    cpu = samples[-1]["cpu_seconds"]
    report = {"pass": True, "requested_seconds": seconds, "wall_seconds": round(wall, 3),
              "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "cpu_seconds": cpu, "average_cpu_one_core_percent": round(cpu / wall * 100, 3),
              "peak_rss_bytes": max(s["peak_rss_bytes"] for s in samples),
              "rss_first_bytes": samples[0]["rss_bytes"], "rss_last_bytes": samples[-1]["rss_bytes"],
              "scope": "real_time_gui_simulation", "physical_validation": "not_run",
              "real_24h_simulation": "pass" if seconds >= 86400 else "not_run"}
    (root / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--exe", type=Path, default=Path(".local/windows-dist/LumaSense/LumaSense.exe"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 10 <= args.seconds <= 259200:
        parser.error("seconds must be 10~259200")
    root = args.output or Path(".local/resource-check") / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    print(json.dumps(run(root.resolve(), args.seconds, args.exe.resolve()), indent=2))


if __name__ == "__main__":
    main()
