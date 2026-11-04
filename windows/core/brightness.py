"""Twinkle Tray CLI adapter. No shell interpolation; select a full internal ID."""
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .diagnostics import Diagnostics


@dataclass(frozen=True)
class Monitor:
    identifier: str
    name: str
    brightness: float | None
    kind: str


class MonitorListUnavailable(ValueError):
    """Twinkle Tray returned no monitor entries."""


class BrightnessBackend(Protocol):
    def monitors(self) -> list[Monitor]: ...
    def set_brightness(self, identifier: str, percent: int) -> dict: ...


def discover_twinkle(configured: str = "") -> Path | None:
    candidates = [configured, os.environ.get("TWINKLE_TRAY_PATH", "")]
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates += [str(local / "Programs/twinkle-tray/Twinkle Tray.exe"),
                   str(local / "Microsoft/WindowsApps/Twinkle-Tray.exe")]
    for base in ("ProgramFiles", "ProgramFiles(x86)"):
        candidates.append(str(Path(os.environ.get(base, "")) / "Twinkle Tray/Twinkle Tray.exe"))
    candidates += [shutil.which("Twinkle-Tray.exe") or "", shutil.which("Twinkle Tray.exe") or ""]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    return None


def parse_monitors(output: str) -> list[Monitor]:
    text = re.sub(r"\x1b\[[0-9;]*m", "", output)
    blocks = re.split(r"(?m)^\s*MonitorNum:", text)[1:]
    monitors = []
    for block in blocks:
        values = dict(re.findall(r"(?m)^\s*(MonitorID|Name|Brightness|Type):\s*([^\r\n]*)", block))
        identifier = values.get("MonitorID", "").strip()
        if not identifier or any(m.identifier == identifier for m in monitors):
            raise ValueError("모니터 ID 누락 또는 중복")
        try:
            brightness = float(values.get("Brightness", ""))
            if not 0 <= brightness <= 100:
                brightness = None
        except ValueError:
            brightness = None
        monitors.append(Monitor(identifier, values.get("Name", identifier).strip(), brightness, values.get("Type", "unknown").strip()))
    if not monitors:
        raise MonitorListUnavailable("Twinkle Tray --List에서 모니터를 읽지 못했습니다. 앱 실행 상태와 원본 로그를 확인하세요.")
    return monitors


class TwinkleTrayBackend:
    def __init__(self, executable: Path, diagnostics: Diagnostics, runner=subprocess.run):
        self.executable, self.diagnostics, self.runner = executable, diagnostics, runner

    def command(self, *args):
        command = [str(self.executable), *args]
        try:
            result = self.runner(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                 timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.diagnostics.event("twinkle_cli", command=command, returncode=result.returncode,
                                   stdout=result.stdout, stderr=result.stderr)
            if result.returncode != 0:
                raise RuntimeError(f"Twinkle Tray 종료 코드 {result.returncode}: {result.stderr or result.stdout}")
            return result.stdout
        except Exception as error:
            self.diagnostics.event("twinkle_error", command=command, error=str(error))
            raise

    def monitors(self):
        # A running Twinkle Tray can briefly return only a newline while its
        # monitor inventory is not ready. Retry reads, never brightness writes.
        for attempt in range(3):
            output = self.command("--List")
            if output.strip():
                return parse_monitors(output)
            if attempt < 2:
                time.sleep(0.25)
        return parse_monitors(output)

    def set_brightness(self, identifier, percent):
        if type(percent) is not int or not 0 <= percent <= 100:
            raise ValueError("밝기는 0~100 정수")
        matches = [m for m in self.monitors() if m.identifier == identifier]
        if len(matches) != 1 or matches[0].kind.lower() not in ("ddcci", "wmi"):
            raise ValueError("밝기를 제어할 수 있는 모니터 ID를 다시 선택하세요.")
        # Twinkle Tray accepts partial IDs: reject ambiguous substring matches.
        if sum(identifier.lower() in m.identifier.lower() for m in self.monitors()) != 1:
            raise ValueError("모호한 모니터 ID")
        output = self.command(f"--MonitorID={identifier}", f"--Set={percent}")
        if not re.search(r"(?m)^\s*OK\s*$", output):
            raise RuntimeError("Twinkle Tray가 OK를 반환하지 않았습니다. 로그를 확인하세요.")
        return self.diagnostics.event("brightness_requested", monitor_id=identifier, percent=percent,
                                      physical_result="unverified")
