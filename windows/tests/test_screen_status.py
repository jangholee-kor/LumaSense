import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import pytest
from PySide6.QtWidgets import QApplication
from windows.core.settings import Settings
from windows.core.automation import AutomationRuntime
from windows.core.diagnostics import Diagnostics
from windows.core.simulation import SimulatedPower, SimulatedGuard
from windows.core.display_controller import State
from windows.ui.screen_status import ScreenStatusBanner
from windows.tests.test_tof import packet


@pytest.fixture
def setup(tmp_path):
    app = QApplication.instance() or QApplication([])
    runtime = AutomationRuntime(Settings(ui_mode="simple", auto_presence=True, absence_seconds=5,
                                        tof_max_distance_cm=100), Diagnostics(tmp_path), SimulatedPower(),
                                guard_factory=SimulatedGuard)
    banner = ScreenStatusBanner()
    yield runtime, banner, SimpleNamespace(state=State.IDLE), app
    banner.close()


def feed(runtime, index, distance):
    value = packet(index + 1)
    value["distance_mm"] = distance
    runtime.ingest({"packet": value, "received_at": index})
    return runtime.tick(index, 0, False, False)


def test_banner_wait_countdown_redetection_and_cancel(setup):
    runtime, banner, controller, app = setup
    for index in range(6):
        feed(runtime, index, 600)
    banner.update_status(runtime, 5, controller)
    assert "사용 중" in banner.title.text()
    for index in range(6, 12):
        feed(runtime, index, 1980)
        banner.update_status(runtime, index, controller)
        expected = f"자리 비움 · {11-index}초 후 꺼짐 카운트다운" if index < 11 else "5초 후 화면이 꺼집니다"
        assert banner.title.text() == expected
        assert not hasattr(banner, "cancel")
    feed(runtime, 12, 600)
    banner.update_status(runtime, 12, controller)
    assert "사용 중" in banner.title.text()
    feed(runtime, 13, 1980)
    banner.update_status(runtime, 13, controller)
    runtime.pause_until = 30
    banner.update_status(runtime, 14, controller)
    assert banner.title.text() == "자동 제어 일시 중단"
    assert not banner.resume.isHidden()


def test_banner_sensor_error_never_shows_off_countdown_and_manual_countdown_is_shared(setup):
    runtime, banner, controller, app = setup
    value = packet()
    value.update(tof_ok=False, sensor_ok=False, distance_mm=None, tof_raw_status=4)
    runtime.ingest({"packet": value, "received_at": 0})
    runtime.tick(0, 0, False, False)
    banner.update_status(runtime, 0, controller)
    assert "자동 꺼짐 보류" in banner.title.text()
    controller.state = State.COUNTDOWN
    controller.deadline = 5
    banner.update_status(runtime, 2, controller)
    assert banner.title.text() == "3초 후 화면이 꺼집니다"


def test_banner_signal_failure_is_absence_wait_then_countdown(setup):
    from windows.tests.test_tof_no_target import missing
    runtime, banner, controller, app = setup
    for index in range(12):
        value = packet(index + 1) if index < 6 else missing(index + 1)
        runtime.ingest({"packet": value, "received_at": index})
        runtime.tick(index, 0, False, False)
        banner.update_status(runtime, index, controller)
        if index >= 6:
            assert "보류" not in banner.title.text()
    assert banner.title.text() == "5초 후 화면이 꺼집니다"
