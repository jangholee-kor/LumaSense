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
    yield window, calls
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
