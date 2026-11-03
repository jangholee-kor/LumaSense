import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QPushButton
from windows.core.display_controller import State
from windows.ui.countdown_overlay import CountdownOverlay, countdown_seconds, overlay_geometry


def model():
    packet = {"presence": False}
    runtime = SimpleNamespace(settings=SimpleNamespace(auto_presence=True), external_block=False,
        pause_until=0, presence=SimpleNamespace(owns_off=False, pending=None, countdown_until=15),
        sensors=SimpleNamespace(ready=lambda now: True,
                                snapshot=lambda now: SimpleNamespace(packet=packet)))
    return runtime, SimpleNamespace(state=State.IDLE), packet


def test_final_five_seconds_and_no_zero_overlay():
    runtime, controller, packet = model()
    for now, expected in [(10, 5), (10.01, 5), (11, 4), (12, 3), (13, 2), (14, 1), (15, None)]:
        assert countdown_seconds(runtime, now, controller) == expected
    runtime.presence.pending = "off"
    assert countdown_seconds(runtime, 14, controller) is None


@pytest.mark.parametrize("condition", ["present", "disabled", "paused", "blocked", "error", "off", "cancelled"])
def test_changed_conditions_hide_automatic_overlay(condition):
    runtime, controller, packet = model()
    if condition == "present": packet["presence"] = True
    if condition == "disabled": runtime.settings.auto_presence = False
    if condition == "paused": runtime.pause_until = 100
    if condition == "blocked": runtime.external_block = True
    if condition == "error": runtime.sensors.ready = lambda now: False
    if condition == "off": runtime.presence.owns_off = True
    if condition == "cancelled": runtime.presence.countdown_until = None
    assert countdown_seconds(runtime, 10, controller) is None


def test_manual_countdown_uses_controller_clock_and_ends_without_zero():
    runtime, controller, packet = model()
    runtime.settings.auto_presence = False
    controller.state, controller.deadline = State.COUNTDOWN, 50
    controller.clock = lambda: 45
    assert countdown_seconds(runtime, 900, controller) == 5
    controller.clock = lambda: 49
    assert countdown_seconds(runtime, 900, controller) == 1
    controller.clock = lambda: 50
    assert countdown_seconds(runtime, 900, controller) is None


@pytest.mark.parametrize("screen", [QRect(0, 0, 2560, 1440), QRect(-1920, 0, 1920, 1080),
                                    QRect(1920, -1080, 1080, 1920), QRect(0, 0, 1280, 720)])
def test_geometry_is_centered_on_the_primary_screen_not_the_virtual_desktop(screen):
    rect = overlay_geometry(screen)
    assert abs(rect.center().x() - screen.center().x()) <= 1
    assert abs(rect.center().y() - screen.center().y()) <= 1
    assert screen.contains(rect)
    assert rect.width() <= 760 and rect.height() <= 820


def test_top_level_non_activating_overlay_displays_sequence_without_buttons():
    app = QApplication.instance() or QApplication([])
    overlay = CountdownOverlay()
    try:
        assert overlay.parentWidget() is None and overlay.isWindow()
        assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert not overlay.findChildren(QPushButton)
        for seconds in [5, 4, 3, 2, 1]:
            overlay.set_seconds(seconds)
            app.processEvents()
            assert overlay.isVisible() and overlay.number.text() == str(seconds)
            assert overlay.geometry() == overlay_geometry(app.primaryScreen().geometry())
        overlay.set_seconds(None)
        assert not overlay.isVisible()
    finally:
        overlay.close()
