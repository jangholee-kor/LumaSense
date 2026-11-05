import os
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from windows.core.diagnostics import Diagnostics
from windows.core.display_controller import DisplayController
from windows.core.settings import Settings
from windows.core.simulation import SimulatedBackend
from windows.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def pump(app, condition, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if condition():
            return True
        time.sleep(.01)
    return False


@pytest.fixture
def simulated(app, tmp_path):
    log = Diagnostics(tmp_path)
    settings = Settings()
    view = MainWindow(log, settings, DisplayController(SimpleNamespace(), log), simulation=True)
    assert pump(app, lambda: bool(view.monitors.currentData()))
    yield view
    view.stop_services()
    view.quitting = True
    view.close()
    view.pool.waitForDone(3000)
    view.power_pool.waitForDone(3000)


def test_manual_tray_slider_and_settings_signals(app, simulated):
    view = simulated
    assert isinstance(view.backend, SimulatedBackend)
    view.auto_panel.auto_brightness.setChecked(True)
    button = next(b for b in view.auto_panel.findChildren(QPushButton) if b.text() == "설정 적용")
    button.click()
    assert view.settings.auto_brightness
    assert Settings.load(view.log.root / "settings.json").auto_brightness
    view.tray_slider.setValue(33)
    view.tray_slider.sliderReleased.emit()
    assert pump(app, lambda: not view.busy)
    assert view.backend.value == 33
    assert view.runtime.brightness.pause_until > time.monotonic() + 890
    view.pause_automation()
    assert view.runtime.pause_until > time.monotonic() + 890
    view.resume_automation()
    assert view.runtime.pause_until == 0


def test_profile_round_trip_without_applying_import(app, simulated, monkeypatch, tmp_path):
    from windows.ui import main_window
    view = simulated
    path = tmp_path / "profile.json"
    view.auto_panel.set_curve([[0, 12], [1000, 80]])
    view.fallback_delay.setValue(45)
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *a: (str(path), ""))
    view.export_settings()
    assert Settings.load(path).curve == [[0, 12], [1000, 80]]
    assert Settings.load(path).fallback_seconds == 45
    view.auto_panel.set_curve([[0, 20], [1000, 50]])
    monkeypatch.setattr(main_window.QFileDialog, "getOpenFileName", lambda *a: (str(path), ""))
    old = view.settings.curve
    view.import_settings()
    assert view.auto_panel.collect(view.settings).curve == [[0, 12], [1000, 80]]
    assert view.settings.curve == old
    view.apply_automation_settings()
    assert view.settings.curve == [[0, 12], [1000, 80]]


def test_simulation_never_launches_live_backend(simulated, monkeypatch):
    from windows.ui import main_window
    view = simulated
    def forbidden(*args, **kwargs):
        raise AssertionError("Live output invoked in simulation")
    monkeypatch.setattr(main_window.subprocess, "Popen", forbidden)
    monkeypatch.setattr(main_window.TwinkleTrayBackend, "command", forbidden)
    view.launch_twinkle()
    assert view.controller.power.off()["simulated"]
    assert view.controller.power.wake("execution_state")["simulated"]
    view.configure_radar()
    assert "시뮬레이션" in view.auto_panel.radar_result.text()


def test_brightness_verification_uses_worker_and_displays_mismatch(app, simulated, monkeypatch):
    import threading
    view = simulated
    view.timer.stop()
    view.sim_timer.stop()
    assert pump(app, lambda: not view.busy)
    main_thread = threading.get_ident()
    threads = []
    pending = [{"kind": "brightness_verify"}]
    def tick(*args):
        result = list(pending)
        pending.clear()
        return result
    def perform(action, backend):
        threads.append(threading.get_ident())
        view.runtime.brightness_feedback.reported = 1
        view.runtime.brightness_feedback.status = "보고값 불일치 · 재시도 종료"
        return {"ok": True}
    monkeypatch.setattr(view.runtime, "tick", tick)
    monkeypatch.setattr(view.runtime, "perform", perform)
    view.automation_tick()
    assert pump(app, lambda: bool(threads) and not view.busy)
    view.automation_tick()
    assert threads[0] != main_thread
    for label in (view.auto_panel.labels["brightness_report"], view.auto_panel.simple_page.brightness_status):
        assert "보고 1%" in label.text() and "재시도 종료" in label.text()


def test_gui_simulation_full_auto_off_and_redetection(app, tmp_path):
    log = Diagnostics(tmp_path)
    settings = Settings(auto_brightness=True, auto_presence=True, absence_seconds=5, stabilization_seconds=1)
    view = MainWindow(log, settings, DisplayController(SimpleNamespace(), log), simulation=True)
    try:
        view.auto_panel.sim_lux.setValue(500)
        view.auto_panel.sim_presence.setCurrentIndex(2)
        assert pump(app, lambda: view.runtime.presence.owns_off, timeout=15)
        assert view.runtime.brightness.requested is not None
        assert view.backend.value != 40
        assert view.runtime.guard is not None
        view.auto_panel.sim_presence.setCurrentIndex(0)
        assert pump(app, lambda: not view.runtime.presence.owns_off)
        assert "wake" in view.runtime.last_action
        view.auto_panel.sim_error.setChecked(True)
        assert pump(app, lambda: view.runtime.presence.state.value == "SENSOR_ERROR")
        assert not view.auto_fault
    finally:
        view.stop_services()
        view.quitting = True
        view.close()
        view.pool.waitForDone(3000)
        view.power_pool.waitForDone(3000)


def test_port_edit_and_invalid_curve(simulated):
    view = simulated
    view.auto_panel.port.setEditText("COM123")
    assert view.auto_panel.selected_port() == "COM123"
    view.auto_panel.curve.insertRow(0)
    with pytest.raises(ValueError, match="셀"):
        view.auto_panel.collect(view.settings)


@pytest.mark.parametrize("ui_mode,expected", [("simple", "new-board"), ("advanced", "old-board")])
def test_visible_usb_port_and_hidden_saved_identity(simulated, monkeypatch, ui_mode, expected):
    from windows.ui import main_window
    view = simulated
    panel = view.auto_panel
    panel.set_ui_mode(ui_mode)
    panel.transport.setCurrentIndex(panel.transport.findData("serial"))
    panel.set_ports([dict(port="COM6", description="ESP32", serial_number="new-board")])
    panel.port.setCurrentIndex(panel.port.findData("COM6"))
    panel.serial_number.setText("old-board")
    options = {}
    worker = SimpleNamespace(start=lambda: None)
    def factory(*args, **kwargs):
        options.update(kwargs)
        return worker
    monkeypatch.setattr(main_window, "SerialManager", factory)
    view.simulation = False
    try:
        view.connect_sensor()
        assert options["port"] == "COM6" and options["serial_number"] == expected
        assert Settings.load(view.log.root / "settings.json").serial_number == expected
    finally:
        view.serial_worker = None
        view.simulation = True


def test_explicit_port_selection_rebinds_identity_but_refresh_preserves_it(simulated):
    panel = simulated.auto_panel
    panel.serial_number.setText("saved-board")
    panel.set_ports([dict(port="COM6", description="ESP32", serial_number="new-board"),
                     dict(port="COM1", description="Serial port", serial_number=None)])
    assert panel.serial_number.text() == "saved-board"
    panel.port.setCurrentIndex(panel.port.findData("COM6"))
    panel.port.activated.emit(panel.port.currentIndex())
    assert panel.serial_number.text() == "new-board"
    panel.port.setCurrentIndex(0)
    panel.port.activated.emit(0)
    assert panel.serial_number.text() == "new-board"
    panel.port.setCurrentIndex(panel.port.findData("COM1"))
    panel.port.activated.emit(panel.port.currentIndex())
    assert panel.serial_number.text() == ""


def test_simple_auto_discovery_preserves_serial_when_saved_port_is_absent(simulated):
    panel = simulated.auto_panel
    panel.set_ui_mode("simple")
    panel.port.setEditText("COM3")
    panel.serial_number.setText("saved-board")
    panel.set_ports([dict(port="COM6", description="ESP32", serial_number="saved-board")])
    assert panel.selected_serial_number() == "saved-board"


def test_tcp_selection_settings_and_export_omit_secret(simulated, monkeypatch, tmp_path):
    from windows.ui import main_window
    view = simulated
    panel = view.auto_panel
    panel.transport.setCurrentIndex(panel.transport.findData("tcp"))
    panel.tcp_host.setText("192.168.0.50")
    panel.tcp_token.setText("b" * 64)
    collected = panel.collect(view.settings)
    assert collected.sensor_transport == "tcp" and collected.tcp_host == "192.168.0.50"
    assert panel.tcp_host.isEnabled() and not panel.port.isEnabled()
    path = tmp_path / "wifi-profile.json"
    monkeypatch.setattr(main_window.QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    view.export_settings()
    assert Settings.load(path).tcp_token == "" and "b" * 64 not in path.read_text(encoding="utf-8")


def test_usb_wifi_setup_does_not_log_password_and_ip_query_updates_endpoint(simulated):
    view = simulated
    panel = view.auto_panel
    requests = []
    view.simulation = False
    view.serial_worker = SimpleNamespace(command=lambda request: requests.append(request))
    try:
        panel.wifi_ssid.setText("test-router")
        panel.wifi_password.setText("private-password")
        view.configure_wifi()
        assert requests[0]["cmd"] == "wifi_config" and requests[0]["password"] == "private-password"
        assert len(requests[0]["token"]) == 64 and not panel.wifi_password.text()
        assert Settings.load(view.log.root / "settings.json").tcp_token == requests[0]["token"]
        view.sensor_command_result(dict(token=view.serial_token, cmd="network_status", ok=True,
            response={"network": {"address": "192.168.0.20", "connected": True}}))
        assert panel.tcp_host.text() == "192.168.0.20"
        view.sensor_command_result(dict(token=view.serial_token, cmd="tof_reset", ok=True, response={}))
        assert "센서 재시작 ACK 성공" in panel.network_result.text()
        assert "private-password" not in (view.log.root / "settings.json").read_text(encoding="utf-8")
    finally:
        view.serial_worker = None
        view.simulation = True


def test_radar_request_requires_explicit_persistent_fields(simulated, tmp_path):
    panel = simulated.auto_panel
    assert panel.radar_request() == {"cmd": "radar_config", "engineering": False}
    panel.radar_range.setChecked(True)
    panel.radar_max.setValue(3)
    panel.radar_thresholds.setChecked(True)
    panel.thresholds.cellWidget(4, 2).setValue(56)
    request = panel.radar_request()
    assert request["max_gate"] == 3 and request["stationary_thresholds"][4] == 56
    path = tmp_path / "radar-profile.json"
    panel.collect(simulated.settings).save(path)
    restored = Settings.load(path)
    assert restored.radar_max_gate == 3 and restored.radar_stationary_thresholds[4] == 56
    panel.radar_min.setValue(5)
    with pytest.raises(ValueError, match="최소"):
        panel.radar_request()


def test_disable_is_immediate_despite_invalid_draft(simulated):
    view = simulated
    view.auto_panel.auto_presence.setChecked(True)
    view.apply_automation_settings()
    assert view.settings.auto_presence
    view.auto_panel.curve.insertRow(0)
    view.auto_panel.auto_presence.setChecked(False)
    assert not view.settings.auto_presence and not view.runtime.settings.auto_presence
    assert not Settings.load(view.log.root / "settings.json").auto_presence


def test_real_serial_worker_signals_reconnect_gui(app, tmp_path, monkeypatch):
    from windows.ui import main_window
    from windows.core.serial_manager import SerialManager
    from windows.tests.test_serial_manager import FakeSerial, packet
    first, second = FakeSerial(), FakeSerial()
    first.add(packet(lux=111))
    second.add(packet(lux=222))
    created = []
    def factory(**kwargs):
        device = (first, second)[len(created)]
        created.append(device)
        return device
    def manager(*args, **kwargs):
        return SerialManager(*args, **kwargs, factory=factory, enumerator=lambda: [], retry_seconds=.05)
    monkeypatch.setattr(main_window, "SerialManager", manager)
    log = Diagnostics(tmp_path)
    view = MainWindow(log, Settings(monitor_id="remember-target"), DisplayController(SimpleNamespace(), log), auto_scan=False)
    try:
        view.auto_panel.port.setEditText("COM-test")
        view.connect_sensor()
        assert pump(app, lambda: view.runtime.sensors.packet is not None)
        assert view.runtime.sensors.packet["lux"] == 111
        assert view.settings.monitor_id == "remember-target"
        first.broken = True
        assert pump(app, lambda: view.runtime.sensors.packet is not None and view.runtime.sensors.packet["lux"] == 222)
        assert "연결됨" in view.auto_panel.connection.text()
    finally:
        view.stop_services()
        view.quitting = True
        view.close()


def test_failed_login_registration_restores_saved_settings(app, tmp_path, monkeypatch):
    from windows.ui import main_window
    log = Diagnostics(tmp_path)
    view = MainWindow(log, Settings(), DisplayController(SimpleNamespace(), log), auto_scan=False)
    def fail(value):
        raise OSError("registry unavailable")
    monkeypatch.setattr(main_window.startup, "set_enabled", fail)
    try:
        view.auto_panel.login_start.setChecked(True)
        view.apply_automation_settings()
        assert not view.settings.login_startup
        assert not Settings.load(log.root / "settings.json").login_startup
    finally:
        view.stop_services()
        view.quitting = True
        view.close()


def test_shutdown_power_recovery_runs_outside_gui_thread(simulated, monkeypatch):
    import threading
    threads = []
    monkeypatch.setattr(simulated.runtime, "shutdown", lambda: threads.append(threading.get_ident()))
    simulated.stop_services()
    assert simulated.power_pool.waitForDone(3000)
    assert threads and threads[0] != threading.get_ident()


def test_two_level_profile_samples_threshold_and_exact_values(simulated):
    view = simulated
    panel = view.auto_panel
    panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("two_level"))
    panel.fields["light_on_brightness"].setValue(55)
    panel.fields["light_off_brightness"].setValue(2)
    panel.set_light_sample("on", 500, "2026-11-02T14:00:00+00:00")
    assert not panel.midpoint_button.isEnabled()
    panel.set_light_sample("off", 4, "2026-11-02T14:01:00+00:00")
    panel.midpoint_button.click()
    panel.curve.insertRow(0)
    view.apply_automation_settings()
    saved = Settings.load(view.log.root / "settings.json")
    assert saved.brightness_mode == "two_level" and saved.light_threshold_lux == 252
    assert saved.light_on_brightness == 55 and saved.light_off_brightness == 2
    assert saved.brightness_min == 10
    assert saved.light_on_lux == 500 and saved.light_off_lux == 4
    assert saved.light_off_recorded_at == "2026-11-02T14:01:00+00:00"
    panel.set_light_sample("off", 600, "2026-11-02T14:02:00+00:00")
    assert not panel.midpoint_button.isEnabled()


def test_light_capture_rejects_expired_data_without_overwriting_sample(simulated):
    view = simulated
    view.auto_panel.sim_lux.setValue(333)
    view.simulation_packet()
    view.record_light_sample("on")
    assert view.auto_panel.light_samples["on"][0] == 333
    view.runtime.sensors.received_at = time.monotonic() - 10
    view.record_light_sample("off")
    assert view.auto_panel.light_samples["off"][0] is None
    assert "최신 정상 조도" in view.output.toPlainText()


def test_two_level_preview_routes_each_preset_through_manual_worker(app, simulated):
    panel = simulated.auto_panel
    buttons = [b for b in panel.two_level_group.findChildren(QPushButton) if b.text() == "이 밝기 미리보기"]
    panel.fields["light_on_brightness"].setValue(55)
    panel.fields["light_off_brightness"].setValue(2)
    buttons[0].click()
    assert pump(app, lambda: not simulated.busy)
    assert simulated.backend.value == 55
    buttons[1].click()
    assert pump(app, lambda: not simulated.busy)
    assert simulated.backend.value == 2
    assert simulated.runtime.brightness.pause_until > time.monotonic() + 890


def test_step_profile_only_changes_runtime_after_apply_and_live_marker_expires(simulated):
    view = simulated
    panel = view.auto_panel
    panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("steps"))
    editor = panel.profile_editor
    editor.name.setText("작업")
    editor.hold.setValue(0)
    editor.table.cellWidget(1, 0).setValue(200)
    editor.table.cellWidget(1, 1).setValue(40)
    assert view.settings.brightness_mode == "curve"
    view.apply_automation_settings()
    assert view.settings.brightness_mode == "steps" and view.settings.brightness_profile == "작업"
    view.auto_panel.sim_lux.setValue(250)
    view.simulation_packet()
    assert view.runtime.brightness.target == 40
    editor.table.cellWidget(1, 1).setValue(60)
    view.simulation_packet()
    assert view.runtime.brightness.target == 40
    view.automation_tick()
    assert editor.graph.current_lux == 250
    view.runtime.sensors.received_at = time.monotonic() - 10
    view.automation_tick()
    assert editor.graph.current_lux is None
    saved = Settings.load(view.log.root / "settings.json")
    assert saved.brightness_profiles[0]["points"][1] == [200, 40]


def test_simple_mode_shared_fields_apply_and_advanced_options_survive(simulated):
    view = simulated
    panel = view.auto_panel
    panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("steps"))
    panel.fields["tof_hold_seconds"].setValue(3)
    panel.fields["recent_input_seconds"].setValue(90)
    view.ui_mode.setCurrentIndex(view.ui_mode.findData("simple"))
    assert panel.tabs.currentWidget() is panel.simple_page
    assert not view.pages.isTabVisible(1)
    assert all(not panel.tabs.isTabVisible(panel.tabs.indexOf(p)) for p in panel.advanced_pages)
    panel.simple_page.fields["light_threshold_lux"].setValue(120.5)
    panel.simple_page.fields["light_on_brightness"].setValue(35)
    panel.simple_page.fields["tof_max_distance_cm"].setValue(100)
    panel.simple_page.fields["absence_seconds"].setValue(7)
    panel.simple_page.auto_presence.setChecked(True)
    assert view.settings.ui_mode == "advanced"
    view.apply_automation_settings()
    saved = Settings.load(view.log.root / "settings.json")
    assert saved.ui_mode == "simple" and saved.brightness_mode == "steps"
    assert saved.tof_hold_seconds == 3 and saved.recent_input_seconds == 90
    assert saved.light_threshold_lux == 120.5 and saved.light_on_brightness == 35
    assert view.runtime.settings.brightness_mode == "two_level"
    assert view.runtime.settings.absence_seconds == 7
    assert view.runtime.settings.tof_hold_seconds == 0 and not view.runtime.settings.use_recent_input
    assert view.centralWidget().layout().itemAt(0).widget() is view.screen_status
    view.ui_mode.setCurrentIndex(view.ui_mode.findData("advanced"))
    assert view.pages.isTabVisible(1)
    view.apply_automation_settings()
    assert view.runtime.settings.brightness_mode == "steps"
    assert view.runtime.settings.tof_hold_seconds == 3 and view.runtime.settings.recent_input_seconds == 90


def test_simple_mode_ignores_hidden_invalid_profile_and_checkbox_disables_immediately(simulated):
    view = simulated
    panel = view.auto_panel
    panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("steps"))
    panel.profile_editor.table.cellWidget(1, 0).setValue(0)
    view.ui_mode.setCurrentIndex(view.ui_mode.findData("simple"))
    panel.simple_page.auto_presence.setChecked(True)
    view.apply_automation_settings()
    assert view.settings.auto_presence and view.runtime.settings.auto_presence
    panel.simple_page.auto_presence.setChecked(False)
    assert not view.settings.auto_presence and not view.runtime.settings.auto_presence


@pytest.mark.parametrize("simulation", [True, False])
@pytest.mark.parametrize("display_enabled", [True, False])
def test_live_no_target_display_uses_absence_countdown_not_sensor_error(simulated, monkeypatch, simulation, display_enabled):
    from unittest.mock import Mock
    from PySide6.QtWidgets import QSystemTrayIcon
    from windows.tests.test_tof import packet
    from windows.tests.test_tof_no_target import missing
    view = simulated
    view.ui_mode.setCurrentIndex(view.ui_mode.findData("simple"))
    view.auto_panel.simple_page.auto_presence.setChecked(True)
    view.auto_panel.simple_page.fields["absence_seconds"].setValue(5)
    view.auto_panel.countdown_page.enabled.setChecked(display_enabled)
    view.apply_automation_settings()
    view.sim_timer.stop()
    view.simulation = simulation
    view.session = SimpleNamespace(input_age=lambda: 1000, locked=lambda: False)
    notification = Mock()
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", notification)
    view.runtime.sensors.invalidate("test", new_session=True)
    base = time.monotonic() - 11
    for i in range(12):
        value = packet(i + 1) if i < 6 else missing(i + 1)
        view.runtime.ingest({"packet": value, "received_at": base + i})
        view.runtime.tick(base + i, 0, False, False)
    view.automation_tick()
    assert "거리 미측정 · 부재 판정" in view.auto_panel.simple_page.live.text()
    assert "거리 미측정 · 부재 판정" in view.auto_panel.labels["distance"].text()
    assert "5초 후 화면이 꺼집니다" == view.screen_status.title.text()
    assert view.runtime.sensors.packet["sensor_ok"] is False
    assert view.countdown_overlay.isVisible() == display_enabled
    if display_enabled:
        assert view.countdown_overlay.number.text() == "5"
    assert "입력으로 취소" in view.tray.toolTip()
    notification.assert_not_called()
    assert not view.auto_fault
    view.runtime.sensor_status({"connected": False, "message": "test disconnect"})
    view.automation_tick()
    assert not view.countdown_overlay.isVisible()


def test_overlay_visible_with_hidden_mainwindow_and_cancel_closes_it(app, simulated):
    from windows.core.display_controller import State
    view = simulated
    token = [100]
    view.runtime.input_token_provider = lambda: token[0]
    view.start_sleep()
    assert view.countdown_overlay.isVisible() and view.countdown_overlay.number.text() == "5"
    view.hide()
    app.processEvents()
    assert view.countdown_overlay.isVisible() and view.countdown_overlay.parentWidget() is None
    token[0] = 101
    view.automation_tick()
    assert view.controller.state == State.IDLE and not view.countdown_overlay.isVisible()
    view.start_sleep()
    assert view.countdown_overlay.isVisible()
    view.stop_services()
    assert not view.countdown_overlay.isVisible()


def test_manual_overlay_cancels_on_newly_detected_person(simulated):
    from windows.core.display_controller import State
    view = simulated
    view.auto_panel.sim_presence.setCurrentIndex(view.auto_panel.sim_presence.findData("absent"))
    view.simulation_packet()
    view.start_sleep()
    assert view.countdown_overlay.isVisible()
    view.auto_panel.sim_presence.setCurrentIndex(view.auto_panel.sim_presence.findData("stationary"))
    view.simulation_packet()
    view.automation_tick()
    assert view.controller.state == State.IDLE and not view.countdown_overlay.isVisible()


@pytest.mark.parametrize("mode", ["simple", "advanced"])
def test_countdown_appearance_applies_persists_and_hidden_manual_countdown_still_cancels(simulated, mode):
    from windows.core.display_controller import State
    view = simulated
    view.ui_mode.setCurrentIndex(view.ui_mode.findData(mode))
    page = view.auto_panel.countdown_page
    assert view.auto_panel.tabs.isTabVisible(view.auto_panel.tabs.indexOf(page))
    page.enabled.setChecked(False)
    page.style.setCurrentIndex(page.style.findData("minimal"))
    page.scale.setValue(65)
    page.position.setCurrentIndex(page.position.findData("bottom_right"))
    page.opacity.setValue(60)
    page.show_hint.setChecked(False)
    assert view.settings.countdown_enabled  # Editing does not change the live overlay.
    view.apply_automation_settings()
    saved = Settings.load(view.log.root / "settings.json")
    assert not saved.countdown_enabled and saved.countdown_style == "minimal"
    assert (saved.countdown_scale, saved.countdown_position, saved.countdown_opacity) == (65, "bottom_right", 60)
    assert not saved.countdown_show_hint
    token = [100]
    view.runtime.input_token_provider = lambda: token[0]
    view.start_sleep()
    assert view.controller.state == State.COUNTDOWN and not view.countdown_overlay.isVisible()
    assert 4 < view.controller.deadline - view.controller.clock() <= 5
    token[0] += 1
    view.automation_tick()
    assert view.controller.state == State.IDLE
    assert not view.countdown_overlay.isVisible()


def test_preview_uses_draft_options_without_power_or_settings_changes(app, simulated, monkeypatch):
    from unittest.mock import Mock
    from windows.core.display_controller import State
    import windows.ui.countdown_settings as countdown_settings
    view = simulated
    page = view.auto_panel.countdown_page
    off = Mock()
    monkeypatch.setattr(view.controller.power, "off", off)
    view.auto_panel.tabs.setCurrentWidget(page)
    page.start_preview()
    assert page.preview.isVisible() and page.preview.number.text() == "5"
    page.style.setCurrentIndex(page.style.findData("minimal"))
    page.scale.setValue(50)
    page.position.setCurrentIndex(page.position.findData("top_right"))
    assert page.preview.width() == 56
    assert view.settings.countdown_style == "large"
    assert view.controller.state == State.IDLE and view.runtime.presence.countdown_until is None
    monkeypatch.setattr(countdown_settings.time, "monotonic", lambda: page.preview_deadline + .01)
    page.update_preview()
    assert not page.preview.isVisible() and not page.preview_timer.isActive()
    off.assert_not_called()


def test_preview_closes_on_disable_tab_change_real_countdown_and_shutdown(app, simulated):
    view = simulated
    page = view.auto_panel.countdown_page
    view.show()
    view.auto_panel.tabs.setCurrentWidget(page)
    app.processEvents()
    page.start_preview()
    page.enabled.setChecked(False)
    assert not page.preview.isVisible() and not page.preview_timer.isActive()
    page.enabled.setChecked(True)
    page.start_preview()
    view.auto_panel.tabs.setCurrentWidget(view.auto_panel.dashboard)
    assert not page.preview.isVisible() and not page.preview_timer.isActive()
    view.auto_panel.tabs.setCurrentWidget(page)
    page.start_preview()
    view.start_sleep()
    assert not page.preview.isVisible() and view.countdown_overlay.isVisible()
    view.cancel_sleep()
    page.start_preview()
    view.stop_services()
    assert not page.preview.isVisible() and not page.preview_timer.isActive()
