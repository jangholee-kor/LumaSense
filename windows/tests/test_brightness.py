import subprocess

import pytest

from windows.core.brightness import TwinkleTrayBackend, discover_twinkle, parse_monitors
from windows.core.diagnostics import Diagnostics

LIST = "\x1b[36mMonitorNum:\x1b[0m 0\nMonitorID: full&ID\nName: Test panel\nBrightness: 24\nType: ddcci\n"


def test_real_cli_format():
    monitor, = parse_monitors(LIST)
    assert monitor.identifier == "full&ID"
    assert monitor.brightness == 24


@pytest.mark.parametrize("text", ["", "Error parsing response", LIST + LIST, "MonitorNum: 1\nName: missing ID"])
def test_bad_lists(text):
    with pytest.raises(ValueError):
        parse_monitors(text)


def test_command_and_validation(tmp_path):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, LIST if "--List" in command else "OK\n", "")
    backend = TwinkleTrayBackend(tmp_path / "a path.exe", Diagnostics(tmp_path), runner)
    assert backend.set_brightness("full&ID", 50)["physical_result"] == "unverified"
    assert calls[-1][-2:] == ["--MonitorID=full&ID", "--Set=50"]
    with pytest.raises(ValueError):
        backend.set_brightness("full&ID", 101)
    with pytest.raises(ValueError):
        backend.set_brightness("missing", 50)


@pytest.mark.parametrize("mode", ["timeout", "nonzero", "no_ok"])
def test_command_failure(tmp_path, mode):
    def runner(command, **kwargs):
        if "--List" in command:
            return subprocess.CompletedProcess(command, 0, LIST, "")
        if mode == "timeout":
            raise subprocess.TimeoutExpired(command, 15)
        return subprocess.CompletedProcess(command, 1 if mode == "nonzero" else 0, "Error", "failure")
    with pytest.raises((RuntimeError, subprocess.TimeoutExpired)):
        TwinkleTrayBackend(tmp_path / "test.exe", Diagnostics(tmp_path), runner).set_brightness("full&ID", 20)


def test_explicit_discovery(tmp_path):
    exe = tmp_path / "custom.exe"
    exe.touch()
    assert discover_twinkle(str(exe)) == exe.resolve()


def test_empty_inventory_is_retried_but_not_a_brightness_write(tmp_path):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "\n" if len(calls) < 3 else LIST, "")
    backend = TwinkleTrayBackend(tmp_path / "test.exe", Diagnostics(tmp_path), runner)
    assert backend.monitors()[0].identifier == "full&ID"
    assert len(calls) == 3 and all(command[-1] == "--List" for command in calls)


def test_empty_inventory_has_bounded_retries_and_never_sets_brightness(tmp_path):
    calls = []
    def runner(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "\n", "")
    backend = TwinkleTrayBackend(tmp_path / "test.exe", Diagnostics(tmp_path), runner)
    with pytest.raises(ValueError, match="모니터를 읽지 못했습니다"):
        backend.set_brightness("full&ID", 55)
    assert len(calls) == 3 and all(command[-1] == "--List" for command in calls)
