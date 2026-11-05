import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from types import SimpleNamespace
from dataclasses import replace
import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QApplication, QPushButton
from windows.core.display_controller import State
from windows.core.settings import Settings
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
            assert overlay.geometry() == overlay_geometry(app.primaryScreen().availableGeometry())
        overlay.set_seconds(None)
        assert not overlay.isVisible()
    finally:
        overlay.close()


@pytest.mark.parametrize("style", ["large", "compact", "minimal"])
@pytest.mark.parametrize("scale", [50, 100, 150])
@pytest.mark.parametrize("position", ["center", "top_left", "top_right", "bottom_left", "bottom_right"])
def test_styles_scale_and_anchor_fit_work_area(style, scale, position):
    for screen in (QRect(-1920, 30, 1920, 1010), QRect(1080, -1920, 1080, 1880), QRect(0, 0, 320, 240)):
        rect = overlay_geometry(screen, style, scale, position)
        assert screen.contains(rect)
        if position == "center":
            assert abs(rect.center().x() - screen.center().x()) <= 1
            assert abs(rect.center().y() - screen.center().y()) <= 1
        else:
            assert (rect.left() == screen.left() + 24 if position.endswith("left")
                    else rect.right() == screen.right() - 24)
            assert (rect.top() == screen.top() + 24 if position.startswith("top")
                    else rect.bottom() == screen.bottom() - 24)


def test_visible_overlay_resizes_and_disables_without_restarting_countdown():
    app = QApplication.instance() or QApplication([])
    settings = Settings()
    overlay = CountdownOverlay(settings)
    try:
        overlay.set_seconds(3)
        app.processEvents()
        for style in ("minimal", "compact", "large", "minimal"):
            settings = replace(settings, countdown_style=style, countdown_scale=50, countdown_position="bottom_right")
            overlay.set_settings(settings)
            app.processEvents()
            assert overlay.geometry() == overlay_geometry(app.primaryScreen().availableGeometry(), style, 50, "bottom_right")
            assert overlay.seconds == 3 and overlay.isVisible()
            assert overlay.caption.isHidden() == (style == "minimal")
        overlay.set_settings(replace(settings, countdown_enabled=False))
        overlay.set_seconds(2)
        assert not overlay.isVisible()
        overlay.set_settings(replace(settings, countdown_enabled=True, countdown_show_hint=False, countdown_opacity=35))
        overlay.set_seconds(1)
        assert overlay.isVisible() and overlay.hint.isHidden()
        assert overlay.windowOpacity() == pytest.approx(.35, abs=.005)
    finally:
        overlay.close()


def test_countdown_settings_load_legacy_and_roundtrip_in_both_modes(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"absence_seconds": 17}', encoding="utf-8")
    settings = Settings.load(path)
    assert settings.countdown_enabled and settings.countdown_style == "large"
    for mode in ("simple", "advanced"):
        expected = replace(settings, ui_mode=mode, countdown_enabled=False, countdown_style="minimal",
                           countdown_scale=50, countdown_position="bottom_right", countdown_opacity=35,
                           countdown_show_hint=False)
        expected.save(path)
        loaded = Settings.load(path)
        assert loaded == expected
        assert loaded.for_control().countdown_enabled is False
        assert loaded.for_control().countdown_style == "minimal"


@pytest.mark.parametrize("field,value", [("countdown_enabled", 0), ("countdown_show_hint", "false"),
    ("countdown_style", "invalid"), ("countdown_position", "invalid"), ("countdown_scale", True),
    ("countdown_scale", 49), ("countdown_scale", 151), ("countdown_opacity", 34), ("countdown_opacity", 101)])
def test_invalid_countdown_settings_rejected(field, value):
    with pytest.raises(ValueError):
        replace(Settings(), **{field: value}).validate()
