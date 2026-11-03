import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from windows.core.brightness import Monitor
from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController, State
from windows.core.settings import Settings
from windows.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path):
    calls = []
    controller = DisplayController(SimpleNamespace(off=lambda: calls.append("off")), Diagnostics(tmp_path))
    window = MainWindow(controller.log, Settings(), controller, auto_scan=False)
    window.runtime.input_token_provider = None
    yield window, calls
    window.stop_services()
    window.timer.stop()
    window.tray.hide()
    window.quitting = True
    window.close()
    window.pool.waitForDone(3000)


def test_cancel_and_no_duplicate(window):
    view, calls = window
    view.start_sleep()
    assert view.controller.state == State.COUNTDOWN
    assert view.cancel_button.isEnabled()
    view.cancel_sleep()
    assert view.controller.state == State.IDLE
    assert not calls


def test_mouse_opt_in(window):
    view, calls = window
    view.method.setCurrentIndex(2)
    view.start_sleep()
    assert view.controller.state == State.IDLE
    assert not calls


def test_help_button_opens_local_guide(window, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    from windows.ui import main_window
    view, _ = window
    opened = []
    monkeypatch.setattr(main_window, "QDesktopServices", SimpleNamespace(openUrl=lambda url: opened.append(url) or True))
    button = next(b for b in view.findChildren(QPushButton) if b.text() == "도움말 / Wi-Fi 설정")
    button.click()
    assert len(opened) == 1 and opened[0].isLocalFile()
    from pathlib import Path
    guide = Path(opened[0].toLocalFile())
    assert guide.is_file() and "Wi-Fi 설정과" in guide.read_text(encoding="utf-8")


def test_missing_help_reports_error(window, monkeypatch, tmp_path):
    from windows.ui import main_window
    view, _ = window
    errors = []
    monkeypatch.setattr(main_window, "help_path", lambda: tmp_path / "missing.html")
    monkeypatch.setattr(view, "fail", errors.append)
    view.open_help()
    assert len(errors) == 1 and "도움말 파일이 없습니다" in errors[0]


def test_fallback_preview_persistence_and_countdown_lock(window):
    view, _ = window
    view.delay.setValue(5)
    view.fallback_delay.setValue(30)
    assert "1차 약 5초" in view.schedule.text()
    assert "첫 추가 요청 약 35초" in view.schedule.text()
    view.start_sleep()
    assert not view.fallback_delay.isEnabled()
    assert Settings.load(view.log.root / "settings.json").fallback_seconds == 30
    view.cancel_sleep()
    assert view.fallback_delay.isEnabled()


def test_ui_passes_interval_and_waits_for_all_recovery_attempts(window, monkeypatch):
    from windows.ui import main_window
    view, calls = window
    intervals, timers = [], []
    view.controller.clock = lambda: 0
    view.controller.arm = lambda *args: intervals.append(args[-1])
    view.delay.setValue(5)
    view.fallback_delay.setValue(30)
    view.start_sleep()
    view.controller.clock = lambda: 5
    monkeypatch.setattr(main_window, "QTimer", SimpleNamespace(singleShot=lambda milliseconds, callback: timers.append(milliseconds)))
    monkeypatch.setattr(view, "submit", lambda function, done: done(function()))
    view.tick()
    assert calls == ["off"]
    assert intervals == [30]
    assert timers == [50000]
    assert view.controller.state == State.RECOVERING
    assert not view.sleep_button.isEnabled()
    view.finish_sleep()
    assert view.sleep_button.isEnabled()


def test_worker_does_not_block_ui_and_delivers_on_main_thread(app, window):
    view, _ = window
    received = []
    worker_threads = []
    def work():
        worker_threads.append(QThread.currentThread())
        time.sleep(0.1)
        return 42
    assert view.submit(work, lambda result: received.append((result, QThread.currentThread())))
    assert not view.submit(work, lambda result: None)
    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert received == [(42, app.thread())]
    assert worker_threads[0] != app.thread()
    assert not view.busy


def test_brightness_uses_selected_id(app, window):
    view, _ = window
    calls = []
    view.backend = SimpleNamespace(set_brightness=lambda identifier, level: calls.append((identifier, level)))
    view.monitors.addItem("27B2H2", "exact-id")
    view.set_brightness(50)
    deadline = time.monotonic() + 3
    while view.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert calls == [("exact-id", 50)]
    assert view.last_test


def test_preview_recovers_missing_inventory_using_saved_target_in_worker(app, window, monkeypatch, tmp_path):
    from windows.ui import main_window
    view, _ = window
    view.settings.monitor_id = "saved-target"
    calls, threads = [], []
    def inventory():
        threads.append(QThread.currentThread())
        time.sleep(0.05)
        return [Monitor("other", "Other", 20, "ddcci"), Monitor("saved-target", "Target", 50, "ddcci")]
    def change(identifier, value):
        calls.append((identifier, value))
        threads.append(QThread.currentThread())
        return {"physical_result": "unverified"}
    backend = SimpleNamespace(monitors=inventory, set_brightness=change)
    monkeypatch.setattr(main_window, "discover_twinkle", lambda configured: tmp_path / "Twinkle.exe")
    monkeypatch.setattr(main_window, "TwinkleTrayBackend", lambda *args: backend)
    view.set_brightness(55)
    assert "목록을 확인" in view.action_result.text()
    deadline = time.monotonic() + 3
    while (view.busy or not view.last_test) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert calls == [("saved-target", 55)]
    assert view.monitors.currentData() == "saved-target"
    assert all(thread != app.thread() for thread in threads)
    assert "55% 밝기 요청 접수" in view.action_result.text()
    assert not view.action_result.isHidden()
    assert view.action_result.parentWidget() == view.centralWidget()
    assert view.runtime.brightness.pause_until > time.monotonic() + 890


@pytest.mark.parametrize("failure", ["missing_target", "inventory_error", "no_saved_target"])
def test_preview_inventory_failure_is_visible_and_does_not_change_other_monitor(app, window, monkeypatch, tmp_path, failure):
    from windows.ui import main_window
    view, _ = window
    view.settings.monitor_id = "" if failure == "no_saved_target" else "saved-target"
    calls = []
    def inventory():
        if failure == "inventory_error":
            raise RuntimeError("모니터 목록 조회 실패")
        return [Monitor("other", "Other", 20, "ddcci")]
    backend = SimpleNamespace(monitors=inventory, set_brightness=lambda *args: calls.append(args))
    monkeypatch.setattr(main_window, "discover_twinkle", lambda configured: tmp_path / "Twinkle.exe")
    monkeypatch.setattr(main_window, "TwinkleTrayBackend", lambda *args: backend)
    view.set_brightness(55)
    deadline = time.monotonic() + 3
    while view.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert not calls and not view.last_test
    if failure == "missing_target":
        assert view.monitors.currentData() is None and view.runtime.monitor_id == ""
    assert not view.action_result.isHidden()
    assert any(text in view.action_result.text() for text in ("찾지 못했습니다", "조회 실패", "다시 누르세요"))


def test_preview_backend_error_is_visible_and_not_retried(app, window):
    view, _ = window
    calls = []
    def change(*args):
        calls.append(args)
        raise RuntimeError("Twinkle Tray 응답 실패")
    view.backend = SimpleNamespace(set_brightness=change)
    view.monitors.addItem("Target", "saved-target")
    view.set_brightness(55)
    deadline = time.monotonic() + 3
    while view.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert len(calls) == 1
    assert "Twinkle Tray 응답 실패" in view.action_result.text()
    assert not view.action_result.isHidden()
