"""Verify bundled GUI and independent helpers using simulated output only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import os
import subprocess
import time
import uuid
import argparse
import hashlib


def records(root):
    return [json.loads(line) for path in root.glob("events-*.jsonl") for line in path.read_text(encoding="utf-8").splitlines()]


def check(executable, root):
    root.mkdir(parents=True, exist_ok=False)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    def gui():
        folder = root / "gui"
        folder.mkdir()
        image = folder / "ui.png"
        env = {**os.environ, "SMC_DATA_DIR": str(folder), "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run([str(executable), "--smoke-test", "--screenshot", str(image)], env=env, timeout=30, creationflags=flags)
        assert result.returncode == 0, f"GUI exit code {result.returncode}"
        assert image.exists() and image.stat().st_size > 1024
        guide = executable.parent / "_internal/windows/resources/help.html"
        assert guide.is_file(), "Offline help missing from package"
        assert "Wi-Fi 설정과" in guide.read_text(encoding="utf-8")
        events = records(folder / "smoke")
        assert any(e["event"] == "app_started" and e["mode"] == "smoke" for e in events)
        assert not any(e["event"] == "twinkle_cli" for e in events)
        return {"case": "gui", "pass": True, "screenshot": str(image), "help_page": str(guide)}
    def watchdog():
        folder = root / "watchdog"
        folder.mkdir()
        result = subprocess.run([str(executable), "--helper", "windows.core.watchdog", "--root", str(folder),
                                 "--ready", str(folder / "ready"), "--test-id", "packaged-watchdog",
                                 "--method", "monitor_power", "--seconds", "5", "--fallback-seconds", "5", "--simulate"],
                                timeout=25, creationflags=flags)
        assert result.returncode == 0
        attempts = [e for e in records(folder) if e["event"] == "wake_attempt"]
        assert len(attempts) == 2 and all(e["result"]["simulated"] for e in attempts)
        return {"case": "watchdog", "pass": True, "simulated": True}
    def lease():
        folder = root / "lease"
        folder.mkdir()
        path = folder / "lease.json"
        path.write_text(json.dumps({"released": False, "expires": time.monotonic() + 1}), encoding="utf-8")
        result = subprocess.run([str(executable), "--helper", "windows.core.lease_guard", "--lease", str(path),
                                 "--method", "execution_state", "--simulate"], timeout=25, creationflags=flags)
        assert result.returncode == 0 and path.with_suffix(".finished").exists()
        attempts = [e for e in records(folder) if e["event"] == "wake_attempt"]
        assert len(attempts) == 2 and all(e["result"]["simulated"] for e in attempts)
        return {"case": "lease_guard", "pass": True, "simulated": True}
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda function: function(), (gui, watchdog, lease)))
    report = {"executable": str(executable), "exe_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "checks": results, "physical_validation": "not_run"}
    (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path, default=Path(".local/windows-dist/LumaSense/LumaSense.exe"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    folder = args.output or Path(".local/exe-check") / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])
    print(json.dumps(check(args.exe.resolve(), folder.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
