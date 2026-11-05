import math
import os
import subprocess
import uuid
import json
import time
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSlider,
                               QSpinBox, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget, QScrollArea,
                               QTabWidget, QWidgetAction, QInputDialog)

from windows.core.brightness import MonitorListUnavailable, TwinkleTrayBackend, discover_twinkle
from windows.core.display_controller import State
from windows.core.watchdog import recovery_window_seconds, arm_watchdog
from windows.core.automation import AutomationRuntime
from windows.core.serial_manager import SerialManager
from windows.core.tcp_manager import TcpManager
import secrets
from windows.core.sensor_protocol import ports
from windows.core.simulation import SimulatedBackend, SimulatedGuard, SimulatedPower, sensor_packet
from windows.core.windows_session import WindowsSession
from windows.core.processes import application_command, process_cwd
from windows.core import startup
from windows.core.settings import Settings
from windows.core.help_page import help_path
from windows.core.sensor_log import SensorRecorder
from windows.ui.automation_panel import AutomationPanel
from windows.ui.lux import format_lux
from windows.ui.screen_status import ScreenStatusBanner
from windows.ui.countdown_overlay import CountdownOverlay, countdown_seconds
from windows import __version__


STARTUP_MONITOR_RETRY_DELAYS_MS = (5000, 15000, 30000)


class Signals(QObject):
    done = Signal(object)
    error = Signal(str)


class SerialSignals(QObject):
    packet = Signal(object)
    status = Signal(object)
    command = Signal(object)


class Job(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = Signals()

    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as error:
            self.signals.error.emit(f"{type(error).__name__}: {error}")


def app_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#178b7c"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(3, 3, 58, 58, 14, 14)
    painter.setPen(QColor("white"))
    painter.drawRect(15, 17, 34, 24)
    painter.drawLine(32, 41, 32, 48)
    painter.drawLine(23, 48, 41, 48)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, diagnostics, settings, controller, backend=None, auto_scan=True, simulation=False):
        super().__init__()
        self.log, self.settings, self.controller = diagnostics, settings, controller
        if simulation:
            controller.power = SimulatedPower()
            controller.arm = lambda *values: arm_watchdog(*values, simulate=True)
        self.backend = SimulatedBackend(diagnostics) if simulation else backend
        self.simulation = simulation
        self.session = None if simulation else WindowsSession()
        self.runtime = AutomationRuntime(settings, diagnostics, controller.power,
            input_provider=(lambda: 1000) if simulation else self.session.input_age,
            locked_provider=(lambda: False) if simulation else self.session.locked,
            input_token_provider=None if simulation else self.session.input_token,
            **({"guard_factory": SimulatedGuard} if simulation else {}))
        self.manual_input_token = None
        self.manual_absent_seen = False
        self.controller.cancel_check = self.manual_should_cancel
        self.serial_worker = None
        self.serial_token = 0
        self.pending_connect = False
        self.serial_signals = SerialSignals(self)
        self.serial_signals.packet.connect(self.sensor_packet)
        self.serial_signals.status.connect(self.sensor_status)
        self.serial_signals.command.connect(self.sensor_command_result)
        self.sim_seq = 0
        self.sim_recorder = SensorRecorder(diagnostics.root) if simulation else None
        self.services_stopped = False
        self.auto_fault = False
        self.sim_started = time.monotonic()
        self.sim_timer = QTimer(self)
        self.sim_timer.setInterval(200)
        self.sim_timer.timeout.connect(self.simulation_packet)
        self.queued_manual = None
        self.power_jobs = set()
        self.power_pool = QThreadPool(self)
        self.power_pool.setMaxThreadCount(1)
        self.busy = False
        self.quitting = False
        self.last_test = ""
        self.jobs = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle(f"LumaSense {__version__} · Smart Monitor Controller" + (" · 시뮬레이션" if simulation else ""))
        self.setWindowIcon(app_icon())
        self.resize(940, 900)
        self.setStyleSheet("QGroupBox{font-weight:600;margin-top:12px;padding-top:16px} QPushButton{padding:7px 12px} QLineEdit,QComboBox,QSpinBox{padding:5px}")
        body = QWidget()
        layout = QVBoxLayout(body)
        heading = QLabel("Smart Monitor Controller · 수동 진단")
        heading.setStyleSheet("font-size:22px;font-weight:600")
        layout.addWidget(heading)
        note = QLabel("선택한 모니터의 밝기와 전체 화면의 절전·복귀 방식을 시험합니다.\nAPI 응답과 화면의 실제 동작은 별도로 기록합니다.")
        layout.addWidget(note)

        group = QGroupBox("01  모니터 연결")
        form = QFormLayout(group)
        self.path = QLineEdit(settings.twinkle_path)
        row = QHBoxLayout()
        row.addWidget(self.path)
        browse = QPushButton("경로 선택")
        browse.clicked.connect(self.browse)
        row.addWidget(browse)
        form.addRow("Twinkle Tray", row)
        controls = QHBoxLayout()
        self.scan = QPushButton("자동 탐색 / 목록 새로고침")
        self.scan.clicked.connect(self.scan_monitors)
        controls.addWidget(self.scan)
        launch = QPushButton("Twinkle Tray 실행")
        launch.clicked.connect(self.launch_twinkle)
        controls.addWidget(launch)
        form.addRow(controls)
        self.monitors = QComboBox()
        self.monitors.currentIndexChanged.connect(self.selection_changed)
        form.addRow("대상 모니터", self.monitors)
        self.reported = QLabel("Twinkle Tray 보고 밝기: 미확인")
        form.addRow(self.reported)
        layout.addWidget(group)

        group = QGroupBox("02  밝기 시험")
        row = QHBoxLayout(group)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        row.addWidget(self.slider)
        self.level = QSpinBox()
        self.level.setRange(0, 100)
        self.level.setSuffix(" %")
        self.level.setValue(50)
        self.slider.valueChanged.connect(self.level.setValue)
        self.slider.sliderReleased.connect(lambda: self.set_brightness(self.slider.value()))
        self.level.valueChanged.connect(self.slider.setValue)
        row.addWidget(self.level)
        apply = QPushButton("적용")
        apply.clicked.connect(lambda: self.set_brightness(self.level.value()))
        row.addWidget(apply)
        for percent in (20, 50, 80):
            button = QPushButton(f"{percent}%")
            button.clicked.connect(lambda checked=False, p=percent: self.set_brightness(p))
            row.addWidget(button)
        layout.addWidget(group)

        group = QGroupBox("03  화면 절전 · 복귀 시험 (연결된 화면 전체)")
        form = QFormLayout(group)
        self.method = QComboBox()
        for label, value in [("SC_MONITORPOWER (-1)", "monitor_power"),
                             ("SetThreadExecutionState (일회성)", "execution_state"),
                             ("SendInput 마우스 +1 / -1 이동", "mouse_move")]:
            self.method.addItem(label, value)
        self.method.setCurrentIndex(max(0, self.method.findData(settings.wake_method)))
        form.addRow("1차 복귀 방식", self.method)
        self.delay = QSpinBox()
        self.delay.setRange(5, 30)
        self.delay.setValue(settings.recovery_seconds)
        self.delay.setSuffix(" 초 후 복귀")
        form.addRow("절전 후 복귀", self.delay)
        self.fallback_delay = QSpinBox()
        self.fallback_delay.setRange(5, 60)
        self.fallback_delay.setValue(settings.fallback_seconds)
        self.fallback_delay.setSuffix(" 초 간격")
        self.fallback_delay.setToolTip("1차 복귀 API 요청 후 다음 복귀 API까지 기다리는 시간입니다.")
        form.addRow("추가 복귀 간격", self.fallback_delay)
        self.mouse = QCheckBox("마우스 이동 복귀 허용 (포인터 위치에 잠시 영향을 줄 수 있음)")
        self.mouse.setChecked(settings.allow_mouse)
        form.addRow(self.mouse)
        self.schedule = QLabel()
        self.schedule.setWordWrap(True)
        self.delay.valueChanged.connect(self.update_schedule)
        self.fallback_delay.valueChanged.connect(self.update_schedule)
        self.method.currentIndexChanged.connect(self.update_schedule)
        self.mouse.toggled.connect(self.update_schedule)
        self.update_schedule()
        form.addRow(self.schedule)
        row = QHBoxLayout()
        self.sleep_button = QPushButton("5초 후 화면 절전 시험")
        self.sleep_button.clicked.connect(self.start_sleep)
        row.addWidget(self.sleep_button)
        self.cancel_button = QPushButton("카운트다운 취소")
        self.cancel_button.clicked.connect(self.cancel_sleep)
        self.cancel_button.setEnabled(False)
        row.addWidget(self.cancel_button)
        self.wake_button = QPushButton("선택 방식으로 지금 복귀 요청")
        self.wake_button.clicked.connect(self.wake_now)
        row.addWidget(self.wake_button)
        form.addRow(row)
        self.power_status = QLabel("화면 상태 미확인 · 마지막 절전/복귀 요청 없음")
        self.power_status.setWordWrap(True)
        form.addRow(self.power_status)
        layout.addWidget(group)

        row = QHBoxLayout()
        self.observation = QComboBox()
        self.observation.addItems(["실제 화면 결과: 미검증", "실제 화면 결과: 성공", "실제 화면 결과: 실패"])
        row.addWidget(self.observation)
        self.notes = QLineEdit()
        self.notes.setPlaceholderText("밝기 변화, 꺼짐/켜짐 시점, HDR/SDR, 수동 복귀 여부")
        row.addWidget(self.notes)
        record = QPushButton("관찰 결과 기록")
        record.clicked.connect(self.record_observation)
        row.addWidget(record)
        layout.addLayout(row)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.document().setMaximumBlockCount(500)
        layout.addWidget(self.output, 1)
        footer = QHBoxLayout()
        help_button = QPushButton("도움말 / Wi-Fi 설정")
        help_button.clicked.connect(self.open_help)
        footer.addWidget(help_button)
        logs = QPushButton("로그 폴더 열기")
        logs.clicked.connect(lambda: os.startfile(self.log.root))
        footer.addWidget(logs)
        footer.addStretch()
        hide = QPushButton("트레이로 숨기기")
        hide.clicked.connect(self.hide_to_tray)
        footer.addWidget(hide)
        quit_button = QPushButton("종료")
        quit_button.clicked.connect(self.quit_app)
        footer.addWidget(quit_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.screen_status = ScreenStatusBanner()
        self.countdown_overlay = CountdownOverlay()
        self.screen_status.resume_requested.connect(self.resume_automation)
        root_layout.addWidget(self.screen_status)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(12, 0, 12, 0)
        mode_row.addWidget(QLabel("사용 모드"))
        self.ui_mode = QComboBox()
        self.ui_mode.addItem("일반", "simple")
        self.ui_mode.addItem("고급", "advanced")
        self.ui_mode.setMinimumWidth(120)
        self.ui_mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.ui_mode.setCurrentIndex(self.ui_mode.findData(settings.ui_mode))
        mode_row.addWidget(self.ui_mode)
        mode_row.addWidget(QLabel("변경 후 설정 적용을 누르세요."))
        mode_row.addStretch()
        root_layout.addLayout(mode_row)
        self.action_result = QLabel()
        self.action_result.setWordWrap(True)
        self.action_result.setContentsMargins(12, 4, 12, 4)
        self.action_result.hide()
        root_layout.addWidget(self.action_result)
        self.pages = QTabWidget()
        self.diagnostic_page = scroll
        self.auto_scroll = QScrollArea()
        self.auto_scroll.setWidgetResizable(True)
        self.install_auto_panel(settings)
        self.pages.addTab(self.auto_scroll, "자동 제어 / 센서")
        self.pages.addTab(scroll, "수동 모니터 시험")
        self.ui_mode.currentIndexChanged.connect(self.change_ui_mode)
        self.change_ui_mode()
        root_layout.addWidget(self.pages)
        root_layout.addLayout(footer)
        self.setCentralWidget(root)

        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Smart Monitor Controller" + (" · 시뮬레이션" if simulation else ""))
        menu = QMenu(self)
        help_action = QAction("도움말 / Wi-Fi 설정", self)
        help_action.triggered.connect(self.open_help)
        menu.addAction(help_action)
        menu.addSeparator()
        self.tray_auto_brightness = QAction("자동 밝기", self)
        self.tray_auto_brightness.setCheckable(True)
        self.tray_auto_brightness.setChecked(settings.auto_brightness)
        self.tray_auto_brightness.triggered.connect(lambda checked: self.tray_toggle("brightness", checked))
        menu.addAction(self.tray_auto_brightness)
        self.tray_auto_presence = QAction("인체 감지 자동 절전", self)
        self.tray_auto_presence.setCheckable(True)
        self.tray_auto_presence.setChecked(settings.auto_presence)
        self.tray_auto_presence.triggered.connect(lambda checked: self.tray_toggle("presence", checked))
        menu.addAction(self.tray_auto_presence)
        self.tray_slider = QSlider(Qt.Orientation.Horizontal)
        self.tray_slider.setRange(0, 100)
        self.tray_slider.setValue(50)
        self.tray_slider.sliderReleased.connect(lambda: self.set_brightness(self.tray_slider.value()))
        slider_action = QWidgetAction(self)
        slider_action.setDefaultWidget(self.tray_slider)
        menu.addAction(slider_action)
        pause_action = QAction("자동 제어 15분 일시 중단", self)
        pause_action.triggered.connect(self.pause_automation)
        menu.addAction(pause_action)
        resume_action = QAction("자동 제어 재개", self)
        resume_action.triggered.connect(self.resume_automation)
        menu.addAction(resume_action)
        menu.addSeparator()
        for label, slot in [("설정 / 시험 창 열기", self.show_main_window), ("화면 절전 시험", self.tray_sleep),
                             ("카운트다운 취소", self.cancel_sleep), ("복귀 요청", self.wake_now), ("종료", self.quit_app)]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_main_window() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.startup_scan_failures = 0
        self.startup_scan_timer = QTimer(self)
        self.startup_scan_timer.setSingleShot(True)
        self.startup_scan_timer.timeout.connect(lambda: self.scan_monitors(startup=True))
        self.message(f"로그 위치: {self.log.root}")
        if auto_scan:
            QTimer.singleShot(0, lambda: self.scan_monitors(startup=True))
        if simulation or settings.connect_on_start:
            QTimer.singleShot(0, self.connect_sensor)

    def message(self, text):
        self.output.append(text)

    def open_help(self):
        path = help_path()
        if not path.is_file():
            self.fail("도움말 파일이 없습니다. 배포 폴더 전체를 다시 풀어 주세요.")
        elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.fail("도움말을 열 수 없습니다. Windows 기본 브라우저 설정을 확인하세요.")

    def fail(self, error):
        self.log.event("ui_error", error=error)
        self.message(f"오류: {error}")
        self.show_action_result(f"오류: {error}", error=True)

    def show_action_result(self, text, error=False):
        self.action_result.setText(text)
        self.action_result.setStyleSheet("color:#b3261e" if error else "color:#147d6b")
        self.action_result.show()

    def submit(self, function, done):
        if self.busy:
            self.message("진행 중인 명령이 끝난 뒤 다시 시도하세요.")
            return False
        self.busy = True
        job = Job(function)
        self.jobs.add(job)
        def success(value):
            self.jobs.discard(job)
            self.busy = False
            try:
                done(value)
            except Exception as error:
                self.fail(str(error))
        def error(text):
            self.jobs.discard(job)
            self.busy = False
            self.fail(text)
        job.signals.done.connect(success)
        job.signals.error.connect(error)
        self.pool.start(job)
        return True

    def browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Twinkle Tray 선택", "", "실행 파일 (*.exe)")
        if filename:
            self.path.setText(filename)

    def save_settings(self):
        self.settings.twinkle_path = self.path.text().strip()
        self.settings.monitor_id = self.monitors.currentData() or self.settings.monitor_id
        self.settings.wake_method = self.method.currentData()
        self.settings.recovery_seconds = self.delay.value()
        self.settings.fallback_seconds = self.fallback_delay.value()
        self.settings.allow_mouse = self.mouse.isChecked()
        self.settings.save(self.log.root / "settings.json")

    def update_schedule(self):
        first, interval = self.delay.value(), self.fallback_delay.value()
        extra = f" · 다음 추가 요청 약 {first + interval * 2}초" if self.mouse.isChecked() else ""
        self.schedule.setText(f"절전 요청 직전 기준: 1차 약 {first}초 · 첫 추가 요청 약 {first + interval}초{extra}\n"
                              "추가 요청 전에 켜지는지 확인하세요. 실제 화면 켜짐에는 모니터 자체 지연이 더해집니다.")

    def scan_monitors(self, on_ready=None, *, startup=False):
        if not startup:
            self.startup_scan_timer.stop()
            self.startup_scan_failures = 0
        if self.controller.state != State.IDLE:
            if startup:
                self.startup_scan_timer.start(1000)
                return False
            self.fail("진행 중인 화면 절전 시험이 끝난 뒤 모니터를 검색하세요.")
            return False
        if self.busy:
            if startup:
                self.startup_scan_timer.start(1000)
                return False
            self.show_action_result("진행 중인 요청이 끝난 뒤 모니터를 다시 검색하세요.")
            return False
        self.show_action_result("Twinkle Tray에서 모니터 목록을 확인하고 있습니다.")
        configured = self.path.text().strip()
        def scan():
            if self.simulation:
                backend = self.backend if isinstance(self.backend, SimulatedBackend) else SimulatedBackend(self.log)
                return "시뮬레이션", backend, backend.monitors()
            exe = discover_twinkle(configured)
            if not exe:
                raise FileNotFoundError("Twinkle Tray를 찾지 못했습니다. 설치 경로를 지정하세요.")
            backend = TwinkleTrayBackend(exe, self.log)
            try:
                return exe, backend, backend.monitors()
            except MonitorListUnavailable as error:
                if startup:
                    return error
                raise
        def done(result):
            if isinstance(result, MonitorListUnavailable):
                if self.startup_scan_failures < len(STARTUP_MONITOR_RETRY_DELAYS_MS):
                    delay = STARTUP_MONITOR_RETRY_DELAYS_MS[self.startup_scan_failures]
                    self.startup_scan_failures += 1
                    self.startup_scan_timer.start(delay)
                    self.log.event("monitor_scan_retry", attempt=self.startup_scan_failures,
                                   delay_seconds=delay / 1000, error=str(result))
                    self.show_action_result(f"Twinkle Tray 모니터 목록 준비 중 · {delay // 1000}초 후 다시 검색합니다.")
                else:
                    self.fail(str(result))
                return
            self.startup_scan_timer.stop()
            self.startup_scan_failures = 0
            exe, self.backend, monitors = result
            self.path.setText(str(exe))
            selected = self.monitors.currentData() or self.settings.monitor_id
            self.monitors.blockSignals(True)
            self.monitors.clear()
            self.monitor_list = monitors
            for monitor in monitors:
                self.monitors.addItem(f"{monitor.name} · {monitor.kind} · {monitor.identifier}", monitor.identifier)
            self.monitors.setCurrentIndex(self.monitors.findData(selected) if selected else (0 if monitors else -1))
            self.monitors.blockSignals(False)
            self.selection_changed()
            self.message(f"모니터 {len(monitors)}대 검색됨. 대상 모니터를 확인하세요.")
            self.show_action_result(f"모니터 {len(monitors)}대 검색됨 · 대상 모니터를 확인하세요.")
            if callable(on_ready):
                on_ready()
        return self.submit(scan, done)

    def selection_changed(self):
        if not self.monitors.currentData():
            self.reported.setText("Twinkle Tray 보고 밝기: 미확인")
            self.runtime.set_monitor("")
            self.auto_panel.target_monitor.setText("선택된 모니터 없음 · 모니터 선택 / 탐색에서 선택하세요.")
            return
        for monitor in getattr(self, "monitor_list", []):
            if monitor.identifier == self.monitors.currentData():
                self.reported.setText(f"Twinkle Tray 보고 밝기: {monitor.brightness}% (실제 휘도 측정 아님)")
                self.runtime.set_monitor(monitor.identifier, monitor.brightness)
                self.auto_panel.target_monitor.setText(f"{monitor.name} · {monitor.identifier}")

    def launch_twinkle(self):
        if self.simulation:
            self.message("시뮬레이션에서는 실제 Twinkle Tray를 실행하지 않습니다.")
            return
        exe = discover_twinkle(self.path.text().strip())
        if not exe:
            self.fail("Twinkle Tray를 찾지 못했습니다.")
            return
        subprocess.Popen([str(exe)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log.event("twinkle_started", executable=str(exe))
        self.message("Twinkle Tray 실행을 요청했습니다. 잠시 후 목록을 새로고침하세요.")

    def set_brightness(self, value):
        if self.controller.state != State.IDLE:
            self.fail("진행 중인 화면 절전 시험이 끝난 뒤 밝기를 미리 보세요.")
            return
        if not self.backend or not self.monitors.currentData():
            identifier = self.monitors.currentData() or self.settings.monitor_id
            def ready():
                if not identifier:
                    self.show_action_result("모니터 선택 / 탐색에서 대상 모니터를 선택한 뒤 미리보기를 다시 누르세요.")
                elif self.monitors.currentData() != identifier:
                    self.fail("기존 대상 모니터를 찾지 못했습니다. 모니터 선택 / 탐색에서 다시 선택하세요.")
                else:
                    self.set_brightness(value)
            self.scan_monitors(on_ready=ready)
            return
        self.runtime.manual_brightness(value)
        if self.busy:
            self.queued_manual = (self.monitors.currentData(), value)
            self.message("진행 중인 요청 이후 마지막 수동 밝기를 적용합니다.")
            self.show_action_result(f"진행 중인 요청이 끝나면 {value}% 밝기를 적용합니다.")
            return
        backend, identifier = self.backend, self.monitors.currentData()
        test_id = uuid.uuid4().hex
        self.show_action_result(f"선택한 모니터에 {value}% 밝기를 요청하고 있습니다.")
        def change():
            result = backend.set_brightness(identifier, value)
            self.log.event("brightness_test", test_id=test_id, monitor_id=identifier, percent=value, result=result)
            return result
        def done(result):
            self.last_test = test_id
            self.observation.setCurrentIndex(0)
            self.message(f"{value}% 밝기 요청 접수 · 시험 {test_id} · 실제 변화는 관찰 후 기록하세요.")
            self.show_action_result(f"{value}% 밝기 요청 접수 · 실제 밝기 변화는 화면에서 확인하세요.")
        self.submit(change, done)

    def start_sleep(self):
        if self.busy or self.power_pool.activeThreadCount() or self.runtime.presence.owns_off:
            self.message("진행 중인 명령이 끝난 뒤 다시 시도하세요.")
            return
        try:
            self.save_settings()
            if self.method.currentData() == "mouse_move" and not self.mouse.isChecked():
                raise ValueError("마우스 이동 복귀를 먼저 허용하세요.")
            self.runtime.pause()
            self.runtime.external_block = True
            self.runtime.observe_input(time.monotonic())
            self.manual_input_token = self.runtime.last_input_token
            snap = self.runtime.sensors.snapshot(time.monotonic())
            self.manual_absent_seen = not (snap.valid and snap.packet and snap.packet.get("presence"))
            self.controller.start()
            self.countdown_overlay.set_seconds(5)
            self.cancel_button.setEnabled(True)
            self.sleep_button.setEnabled(False)
            self.wake_button.setEnabled(False)
            for widget in (self.method, self.delay, self.fallback_delay, self.mouse):
                widget.setEnabled(False)
        except Exception as error:
            self.fail(str(error))

    def tray_sleep(self):
        self.showNormal()
        self.raise_()
        self.start_sleep()

    def cancel_sleep(self):
        if self.controller.cancel():
            self.countdown_overlay.set_seconds(None)
            self.power_status.setText("절전 시험 취소됨 · 화면 절전 명령 없음")
            self.reset_controls()
            self.runtime.external_block = False

    def reset_controls(self):
        self.cancel_button.setEnabled(False)
        self.sleep_button.setEnabled(True)
        self.wake_button.setEnabled(True)
        for widget in (self.method, self.delay, self.fallback_delay, self.mouse):
            widget.setEnabled(True)

    def tick(self):
        self.automation_tick()
        if self.controller.state != State.COUNTDOWN:
            return
        remaining = self.controller.deadline - self.controller.clock()
        self.power_status.setText(f"전체 화면 절전까지 {max(0, math.ceil(remaining))}초 · 취소 가능")
        if remaining <= 0 and not self.busy:
            self.cancel_button.setEnabled(False)
            method, seconds, allow = self.method.currentData(), self.delay.value(), self.mouse.isChecked()
            interval = self.fallback_delay.value()
            # Move out of COUNTDOWN before the next event-loop tick submits again.
            self.timer.stop()
            self.last_test = self.controller.test_id
            self.observation.setCurrentIndex(0)
            self.power_status.setText(f"시험 {self.last_test} · 1차 약 {seconds}초 / 추가 약 {seconds + interval}초")
            self.message(f"시험 {self.last_test} · 1차 {method}, 지연 {seconds}초, 추가 복귀 간격 {interval}초")
            self.submit(lambda: self.controller.execute(method, seconds, allow, interval), self.manual_power_result)
            # The detached helper performs recovery even if this timer/GUI fails.
            window_seconds = recovery_window_seconds(method, seconds, allow, interval)
            test_id = self.controller.test_id
            QTimer.singleShot(window_seconds * 1000, lambda: self.finish_sleep()
                              if self.controller.test_id == test_id and self.controller.state == State.RECOVERING else None)

    def manual_should_cancel(self):
        provider = self.runtime.input_token_provider
        if provider is not None:
            token = provider()
            if token is None or self.manual_input_token is None or token != self.manual_input_token:
                return True
        with self.runtime.lock:
            snap = self.runtime.sensors.snapshot(time.monotonic())
            present = snap.packet.get("presence") if snap.valid and snap.packet else None
            if present is False:
                self.manual_absent_seen = True
            return bool(present and self.manual_absent_seen)

    def manual_power_result(self, result):
        if isinstance(result, dict) and result.get("cancelled"):
            self.finish_sleep()
            self.message("입력·감지 변경으로 수동 화면 꺼짐을 취소했습니다.")
        else:
            self.message(str(result))

    def finish_sleep(self):
        self.controller.finish()
        self.reset_controls()
        self.timer.start()
        self.runtime.external_block = False
        self.power_status.setText("복귀 시도 시간 경과 · 화면 상태는 관찰 후 기록하세요.")

    def wake_now(self):
        self.runtime.pause()
        if self.runtime.presence.owns_off or self.power_pool.activeThreadCount():
            self.message("자동 절전 복귀를 요청했습니다. 진행 중인 전원 요청 후 처리합니다.")
            return
        if self.controller.state != State.IDLE:
            self.message("예약된 복귀 프로세스가 실행 중입니다.")
            return
        method, allow = self.method.currentData(), self.mouse.isChecked()
        test_id = uuid.uuid4().hex
        def wake():
            result = self.controller.power.wake(method, allow)
            return self.log.event("manual_wake", test_id=test_id, method=method, result=result)
        def done(result):
            self.last_test = test_id
            self.observation.setCurrentIndex(0)
            self.message(str(result))
        self.submit(wake, done)

    def record_observation(self):
        if not self.last_test or self.busy or self.controller.state != State.IDLE:
            self.fail("완료된 시험을 선택한 뒤 관찰 결과를 기록하세요.")
            return
        self.log.event("user_observation", test_id=self.last_test,
                       result=("unverified", "pass", "fail")[self.observation.currentIndex()], notes=self.notes.text())
        self.message(f"관찰 결과 기록됨 · {self.last_test}")

    def show_main_window(self):
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.raise_()
        self.activateWindow()

    def hide_to_tray(self):
        if self.tray.isVisible() and self.controller.state == State.IDLE:
            self.hide()
        else:
            self.message("트레이가 없거나 절전 시험 중이므로 창을 유지합니다.")

    def install_auto_panel(self, settings):
        panel = AutomationPanel(settings, self.simulation)
        for signal, method in ((panel.connect_requested, self.connect_sensor), (panel.disconnect_requested, self.disconnect_sensor),
                (panel.refresh_requested, self.refresh_ports), (panel.apply_requested, self.apply_automation_settings),
                (panel.pause_requested, self.pause_automation), (panel.resume_requested, self.resume_automation),
                (panel.export_requested, self.export_settings), (panel.import_requested, self.import_settings),
                (panel.simulation_requested, self.open_simulation), (panel.radar_requested, self.configure_radar)):
            signal.connect(method)
        panel.wifi_config_requested.connect(self.configure_wifi)
        panel.network_status_requested.connect(lambda: self.sensor_request({"cmd": "network_status"}))
        panel.tof_reset_requested.connect(self.reset_tof)
        panel.monitor_requested.connect(self.choose_monitor)
        panel.light_sample_requested.connect(self.record_light_sample)
        panel.light_preview_requested.connect(self.set_brightness)
        panel.auto_brightness.toggled.connect(lambda checked: self.disable_automation("brightness") if not checked else None)
        panel.auto_presence.toggled.connect(lambda checked: self.disable_automation("presence") if not checked else None)
        if self.simulation:
            panel.login_start.setEnabled(False)
        self.auto_panel = panel
        self.auto_scroll.setWidget(panel)
        if hasattr(self, "ui_mode"):
            self.ui_mode.blockSignals(True)
            self.ui_mode.setCurrentIndex(self.ui_mode.findData(settings.ui_mode))
            self.ui_mode.blockSignals(False)
            self.change_ui_mode()

    def change_ui_mode(self):
        simple = self.ui_mode.currentData() == "simple"
        self.auto_panel.set_ui_mode(self.ui_mode.currentData())
        if self.pages.count() > 1:
            self.pages.setTabVisible(1, not simple)
            if simple:
                self.pages.setCurrentIndex(0)

    def choose_monitor(self):
        if self.ui_mode.currentData() == "advanced":
            self.pages.setCurrentWidget(self.diagnostic_page)
            return
        if not self.monitors.count():
            self.scan_monitors()
            self.message("모니터를 검색합니다. 검색 후 모니터 선택을 다시 누르세요.")
            return
        names = [self.monitors.itemText(i) for i in range(self.monitors.count())]
        chosen, ok = QInputDialog.getItem(self, "밝기를 바꿀 모니터", "모니터", names,
                                        max(0, self.monitors.currentIndex()), False)
        if ok:
            self.monitors.setCurrentIndex(names.index(chosen))

    def record_light_sample(self, state):
        try:
            if state not in ("on", "off"):
                raise ValueError("ON/OFF 조도 기록 대상 필요")
            snapshot = self.runtime.sensors.snapshot(time.monotonic())
            if not snapshot.valid or not snapshot.packet or not snapshot.packet["light_ok"]:
                raise ValueError("최신 정상 조도 데이터가 필요합니다.")
            lux = snapshot.packet["lux"]
            recorded_at = datetime.now(timezone.utc).isoformat()
            self.auto_panel.set_light_sample(state, lux, recorded_at)
            self.log.event("lighting_sample_captured", state=state, lux=lux, recorded_at=recorded_at,
                           simulated=self.simulation)
            self.message(f"{state.upper()} 조도 {format_lux(lux)} lux를 기록했습니다. 밝기 설정 적용을 누르면 저장됩니다.")
        except Exception as error:
            self.fail(str(error))

    def disable_automation(self, kind):
        # Turning a control off must work even if a different draft field is invalid.
        field = "auto_brightness" if kind == "brightness" else "auto_presence"
        if not getattr(self.settings, field):
            return
        with self.runtime.lock:
            setattr(self.settings, field, False)
            setattr(self.runtime.settings, field, False)
            self.runtime.epoch += 1
            if kind == "presence":
                self.countdown_overlay.set_seconds(None)
                self.runtime.presence.cancel(time.monotonic())
        if hasattr(self, "tray_auto_brightness"):
            (self.tray_auto_brightness if kind == "brightness" else self.tray_auto_presence).setChecked(False)
        try:
            self.save_settings()
        except Exception as error:
            self.fail(str(error))

    def refresh_ports(self):
        if self.simulation:
            self.auto_panel.set_ports([])
        else:
            self.submit(ports, self.auto_panel.set_ports)

    def connect_sensor(self):
        if self.simulation:
            self.sim_timer.start()
            self.auto_panel.connection.setText("가상 센서 연결됨 · 실제 USB 미사용")
            self.runtime.sensor_status({"connected": False, "message": "시뮬레이션 시작"})
            self.simulation_packet(new_session=True)
            return
        if self.serial_worker and self.serial_worker.thread and self.serial_worker.thread.is_alive():
            if self.serial_worker.stop_event.is_set():
                self.pending_connect = True
                self.auto_panel.connection.setText("기존 포트 종료 후 다시 연결합니다.")
            else:
                self.message("시리얼 작업이 이미 실행 중입니다.")
            return
        port = self.auto_panel.selected_port()
        number = self.auto_panel.selected_serial_number() if self.auto_panel.transport.currentData() == "serial" else self.auto_panel.serial_number.text().strip()
        try:
            self.settings.serial_port, self.settings.serial_number = port, number
            self.settings.sensor_transport = self.auto_panel.transport.currentData()
            self.settings.tcp_host = self.auto_panel.tcp_host.text().strip()
            self.settings.tcp_port = self.auto_panel.tcp_port.value()
            self.settings.tcp_token = self.auto_panel.tcp_token.text().strip()
            self.save_settings()
            self.serial_token += 1
            token = self.serial_token
            manager = TcpManager if self.settings.sensor_transport == "tcp" else SerialManager
            options = dict(host=self.settings.tcp_host, port=self.settings.tcp_port, token=self.settings.tcp_token) if manager is TcpManager else dict(port=port, serial_number=number)
            self.serial_worker = manager(self.log,
                lambda event: self.serial_signals.packet.emit({**event, "token": token}),
                lambda event: self.serial_signals.status.emit({**event, "token": token}),
                lambda event: self.serial_signals.command.emit({**event, "token": token}),
                **options, stale_seconds=self.runtime.settings.sensor_stale_seconds)
            self.serial_worker.start()
        except Exception as error:
            self.fail(str(error))

    def disconnect_sensor(self):
        self.pending_connect = False
        self.sim_timer.stop()
        if self.serial_worker:
            self.serial_worker.stop()
        self.runtime.sensor_status({"connected": False, "message": "연결 종료"})
        self.auto_panel.connection.setText("연결 종료 요청 · 포트가 닫힌 뒤 플래시할 수 있습니다.")

    def sensor_packet(self, event):
        if event.get("token", self.serial_token) != self.serial_token:
            return
        try:
            self.runtime.ingest(event)
            self.auto_panel.radar_group.setEnabled(event["packet"].get("presence_sensor") != "vl53l1x")
        except ValueError as error:
            self.fail(str(error))

    def sensor_status(self, event):
        if event.get("token") != self.serial_token:
            return
        self.runtime.sensor_status(event)
        self.auto_panel.connection.setText(f"{event.get('port', '')} · {event['message']}")

    def sensor_command_result(self, event):
        if event.get("token") != self.serial_token:
            return
        self.auto_panel.radar_result.setText("설정 ACK 성공 · 실제 감지 결과는 확인이 필요합니다." if event["ok"] else f"설정 실패: {event['error']}")
        response = event.get("response") or {}
        if event.get("cmd") in ("wifi_config", "network_status", "get_status", "tof_reset"):
            network = response.get("network", {})
            address = network.get("address", "")
            if address:
                self.auto_panel.tcp_host.setText(address)
            if not event["ok"]:
                message = f"명령 실패: {event['error']}"
            elif network:
                message = f"IP {address or '미할당'} · 공유기 {'연결됨' if network.get('connected') else '접속 대기'}"
            elif event.get("cmd") == "tof_reset":
                message = "센서 재시작 ACK 성공 · 새 측정과 안정화 완료를 확인하세요."
            else:
                message = "설정 저장 ACK 성공 · 잠시 후 장치 IP를 조회하세요."
            self.auto_panel.network_result.setText(message)

    def sensor_request(self, payload):
        if self.simulation:
            self.auto_panel.network_result.setText("시뮬레이션에서는 장치 명령을 보내지 않습니다.")
            return
        try:
            if not self.serial_worker:
                raise RuntimeError("먼저 센서를 연결하세요.")
            return self.serial_worker.command(payload)
        except Exception as error:
            self.auto_panel.network_result.setText(str(error))

    def reset_tof(self):
        if self.sensor_request({"cmd": "tof_reset"}):
            self.runtime.sensors.invalidate("ToF 재시작 후 안정화", new_session=True)

    def configure_wifi(self):
        panel = self.auto_panel
        if self.simulation:
            panel.network_result.setText("시뮬레이션에서는 Wi-Fi 설정을 저장하지 않습니다.")
            return
        try:
            if not self.serial_worker or isinstance(self.serial_worker, TcpManager):
                raise ValueError("Wi-Fi 설정은 센서에 USB로 연결한 뒤 저장하세요.")
            ssid, password = panel.wifi_ssid.text(), panel.wifi_password.text()
            if '\0' in ssid or '\0' in password or not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password.encode()) <= 63:
                raise ValueError("공유기 이름은 UTF-8 1~32바이트, 비밀번호는 8~63바이트여야 합니다.")
            token = panel.tcp_token.text().strip() or secrets.token_hex(32)
            candidate = replace(self.settings, tcp_token=token).validate()
            self.serial_worker.command(dict(cmd="wifi_config", ssid=ssid, password=password, token=token))
            self.settings.tcp_token = token
            panel.tcp_token.setText(token)
            candidate.save(self.log.root / "settings.json")
            panel.wifi_password.clear()
            panel.network_result.setText("장치 설정 저장 응답 대기 중")
        except Exception as error:
            panel.network_result.setText(str(error))

    def simulation_packet(self, new_session=False):
        if not self.simulation:
            return
        now = time.monotonic()
        self.sim_seq += 1
        panel = self.auto_panel
        packet = sensor_packet(self.sim_seq, int((now - self.sim_started) * 1000), panel.sim_lux.value(),
                               panel.sim_presence.currentData(), panel.sim_error.isChecked())
        self.sim_recorder.write(packet, now, simulated=True)
        self.sensor_packet({"packet": packet, "received_at": now, "new_session": new_session})

    def collect_settings(self):
        candidate = self.auto_panel.collect(replace(self.settings, allow_mouse=self.mouse.isChecked()))
        candidate.twinkle_path = self.path.text().strip() if not self.simulation else self.settings.twinkle_path
        candidate.monitor_id = self.monitors.currentData() or self.settings.monitor_id
        candidate.wake_method = self.method.currentData()
        candidate.recovery_seconds = self.delay.value()
        candidate.fallback_seconds = self.fallback_delay.value()
        candidate.allow_mouse = self.mouse.isChecked()
        return candidate.validate()

    def apply_automation_settings(self):
        try:
            candidate = self.collect_settings()
            if self.simulation:
                candidate.login_startup = False
            candidate.validate()
            candidate.save(self.log.root / "settings.json")
            if not self.simulation and candidate.login_startup != self.settings.login_startup:
                try:
                    startup.set_enabled(candidate.login_startup)
                except Exception:
                    self.settings.save(self.log.root / "settings.json")
                    raise
            reconnect = any(getattr(candidate, field) != getattr(self.settings, field) for field in
                            ("serial_port", "serial_number", "sensor_transport", "tcp_host", "tcp_port", "tcp_token"))
            active = bool(self.serial_worker and self.serial_worker.thread and self.serial_worker.thread.is_alive())
            self.settings = candidate
            self.runtime.apply_settings(candidate)
            self.countdown_overlay.set_seconds(None)
            self.runtime.external_block = self.controller.state != State.IDLE
            self.runtime.set_monitor(candidate.monitor_id,
                                     next((m.brightness for m in getattr(self, "monitor_list", []) if m.identifier == candidate.monitor_id), None))
            self.auto_fault = False
            if self.serial_worker:
                self.serial_worker.stale_seconds = self.runtime.settings.sensor_stale_seconds
            if reconnect and active:
                self.disconnect_sensor()
                self.pending_connect = True
            self.tray_auto_brightness.setChecked(candidate.auto_brightness)
            self.tray_auto_presence.setChecked(candidate.auto_presence)
            self.auto_panel.pause_status.setText("설정을 적용했습니다.")
            self.message("자동 제어 설정을 적용했습니다. 센서 안정화 후 제어합니다.")
            self.log.event("automation_settings_applied", auto_brightness=candidate.auto_brightness, auto_presence=candidate.auto_presence,
                           ui_mode=candidate.ui_mode, effective_brightness_mode=self.runtime.settings.brightness_mode,
                           effective_input_protection=self.runtime.settings.use_recent_input,
                           absence_seconds=candidate.absence_seconds, use_recent_input=candidate.use_recent_input,
                           recent_input_seconds=candidate.recent_input_seconds,
                           tof_min_distance_cm=candidate.tof_min_distance_cm, tof_max_distance_cm=candidate.tof_max_distance_cm,
                           tof_hysteresis_cm=candidate.tof_hysteresis_cm, tof_hold_seconds=candidate.tof_hold_seconds,
                           simulated=self.simulation)
        except Exception as error:
            self.fail(str(error))

    def pause_automation(self):
        self.countdown_overlay.set_seconds(None)
        self.runtime.pause(900)
        self.cancel_sleep()
        self.message("자동 제어를 15분 중단합니다.")

    def resume_automation(self):
        self.runtime.resume()
        self.runtime.sensors.invalidate("수동 재개 후 안정화")
        self.runtime.external_block = self.controller.state != State.IDLE
        self.auto_fault = False
        self.message("자동 제어를 재개합니다.")

    def tray_toggle(self, kind, checked):
        widget = self.auto_panel.auto_brightness if kind == "brightness" else self.auto_panel.auto_presence
        widget.setChecked(checked)
        self.apply_automation_settings()
        self.tray_auto_brightness.setChecked(self.settings.auto_brightness)
        self.tray_auto_presence.setChecked(self.settings.auto_presence)

    def export_settings(self):
        filename, _ = QFileDialog.getSaveFileName(self, "설정과 밝기 프로필 저장", "monitor-profile.json", "JSON (*.json)")
        if filename:
            try:
                replace(self.collect_settings(), tcp_token="").save(Path(filename))
                self.message("설정과 밝기 프로필을 저장했습니다.")
            except Exception as error:
                self.fail(str(error))

    def import_settings(self):
        filename, _ = QFileDialog.getOpenFileName(self, "설정과 밝기 프로필 열기", "", "JSON (*.json)")
        if filename:
            try:
                candidate = Settings.load(Path(filename))
                if not candidate.tcp_token:
                    candidate.tcp_token = self.settings.tcp_token
                self.path.setText(candidate.twinkle_path)
                self.method.setCurrentIndex(self.method.findData(candidate.wake_method))
                self.delay.setValue(candidate.recovery_seconds)
                self.fallback_delay.setValue(candidate.fallback_seconds)
                self.mouse.setChecked(candidate.allow_mouse)
                index = self.monitors.findData(candidate.monitor_id)
                if index >= 0:
                    self.monitors.setCurrentIndex(index)
                self.install_auto_panel(candidate)
                self.message("설정을 불러왔습니다. 내용을 확인하고 설정 적용을 누르세요.")
            except Exception as error:
                self.fail(str(error))

    def open_simulation(self):
        subprocess.Popen(application_command("--simulate"), cwd=process_cwd(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    def configure_radar(self):
        try:
            if self.simulation:
                self.auto_panel.radar_result.setText("시뮬레이션: 실제 레이더 설정은 전송하지 않습니다.")
                return
            if not self.serial_worker:
                raise RuntimeError("센서 연결이 필요합니다.")
            request = self.auto_panel.radar_request()
            request_id = self.serial_worker.command(request)
            self.auto_panel.radar_result.setText(f"ACK 대기: {request_id}")
        except Exception as error:
            self.fail(str(error))

    def submit_power_action(self, action):
        job = Job(lambda: self.runtime.perform(action))
        self.power_jobs.add(job)
        def done(result):
            self.power_jobs.discard(job)
            self.message("입력·감지 변경으로 화면 꺼짐을 취소했습니다." if result.get("cancelled") else
                         f"자동 {action['kind']}: {result['ok']} · 실제 화면 상태는 관찰 필요")
        def failed(error):
            self.power_jobs.discard(job)
            self.runtime.presence.completed(action["kind"], False, time.monotonic())
            self.fail(error)
        job.signals.done.connect(done)
        job.signals.error.connect(failed)
        self.power_pool.start(job)

    def automation_tick(self):
        if self.services_stopped:
            return
        try:
            if self.pending_connect and (not self.serial_worker or not self.serial_worker.thread.is_alive()):
                self.pending_connect = False
                self.connect_sensor()
            if self.queued_manual and not self.busy:
                identifier, percent = self.queued_manual
                self.queued_manual = None
                if identifier == self.monitors.currentData():
                    self.set_brightness(percent)
            now = time.monotonic()
            if not self.auto_fault:
                age = 1000 if self.simulation else self.session.input_age()
                locked = False if self.simulation else self.session.locked()
                actions = self.runtime.tick(now, age, locked, bool(self.backend and not self.busy))
                for action in actions:
                    if action["kind"] == "brightness":
                        backend = self.backend
                        if not self.submit(lambda item=action: self.runtime.perform(item, backend),
                                           lambda result: self.message(f"자동 밝기: {result['ok']}")):
                            self.runtime.brightness_pending = False
                    else:
                        self.submit_power_action(action)
            if self.controller.state == State.COUNTDOWN and self.manual_should_cancel():
                self.cancel_sleep()
                self.message("키보드·마우스 입력 또는 재감지로 카운트다운을 취소했습니다.")
            snapshot = self.runtime.sensors.snapshot(now)
            packet = snapshot.packet or {}
            previous = " (이전 값)" if not snapshot.valid and packet else ""
            def text(value):
                return "미확인" if value is None else str(value)
            def detection(value):
                return "미확인 / 오류" if value is None else ("감지" if value else "미감지")
            labels = self.auto_panel.labels
            labels["lux"].setText(f"{format_lux(packet.get('lux'))} lux{previous}")
            self.auto_panel.profile_editor.set_current_lux(packet.get("lux") if snapshot.valid and packet.get("light_ok") else None)
            labels["presence"].setText(f"{detection(packet.get('presence'))}{previous}")
            labels["motion"].setText("VL53L1X 거리 기준 · 움직임 분류 없음" if packet.get("ver") == 2 else
                                     f"{detection(packet.get('moving'))} / {detection(packet.get('stationary'))}{previous}")
            distance_text = "거리 미측정 · 부재 판정" if packet.get("tof_no_target") else f"{text(packet.get('distance_cm'))} cm"
            labels["distance"].setText(f"{distance_text}{previous}")
            ready = self.runtime.sensors.ready(now)
            labels["sensor"].setText(f"{snapshot.reason} · {'안정화 완료' if ready else '자동 절전 보류'}")
            labels["brightness"].setText(f"{text(self.runtime.brightness.target)} / {text(self.runtime.brightness.requested)} %")
            light_on = self.runtime.brightness.light_on
            lighting = "조도 곡선"
            if self.runtime.settings.brightness_mode == "two_level":
                lighting = "미확인" if not snapshot.valid or not packet.get("light_ok") or light_on is None else (
                    "기준 이상 · 형광등 ON 밝기" if light_on else "기준 미만 · 불 끔 밝기")
            elif self.runtime.settings.brightness_mode == "steps":
                steps = self.runtime.brightness.steps
                lighting = "미확인" if not snapshot.valid or not packet.get("light_ok") or steps.index is None else (
                    f"{self.settings.brightness_profile} · {format_lux(steps.points[steps.index][0])} lux 이상 → {steps.points[steps.index][1]}%" +
                    (" · 구간 전환 대기" if steps.candidate is not None else ""))
            labels["lighting"].setText(lighting)
            state = self.runtime.presence
            countdown = f" · 절전까지 {max(0, math.ceil(state.countdown_until - now))}초" if state.countdown_until is not None and not state.owns_off else ""
            if countdown:
                self.tray.setToolTip(f"LumaSense{countdown} · 키보드·마우스 입력으로 취소")
            else:
                self.tray.setToolTip("Smart Monitor Controller" + (" · 시뮬레이션" if self.simulation else ""))
            labels["power"].setText(f"{state.state.value} · {state.status_text(now)}{countdown}")
            labels["last"].setText(self.runtime.last_action)
            remaining = max(0, math.ceil(self.runtime.pause_until - now))
            manual = max(0, math.ceil(self.runtime.brightness.pause_until - now))
            self.auto_panel.pause_status.setText(f"자동 밝기 {'ON' if self.settings.auto_brightness else 'OFF'} · 자동 절전 {'ON' if self.settings.auto_presence else 'OFF'}\n"
                                                f"전체 중단 {remaining}초 · 수동 밝기 보호 {manual}초")
            self.auto_panel.simple_page.live.setText(
                f"현재 조도 {format_lux(packet.get('lux'))} lux · {distance_text}{previous}")
            self.screen_status.update_status(self.runtime, now, self.controller)
            self.countdown_overlay.set_seconds(countdown_seconds(self.runtime, now, self.controller))
        except Exception as error:
            self.countdown_overlay.set_seconds(None)
            self.auto_fault = True
            self.runtime.external_block = True
            self.fail(f"자동 제어 중단: {error}")

    def stop_services(self):
        if self.services_stopped:
            return
        self.services_stopped = True
        self.countdown_overlay.close()
        self.timer.stop()
        self.startup_scan_timer.stop()
        self.sim_timer.stop()
        if self.serial_worker:
            self.serial_worker.stop()
            if not self.serial_worker.wait(2):
                self.log.event("serial_shutdown_pending")
        self.runtime.external_block = True
        self.shutdown_job = Job(self.runtime.shutdown)
        self.power_pool.start(self.shutdown_job)
        if self.sim_recorder:
            self.sim_recorder.close()

    def quit_app(self):
        self.cancel_sleep()
        self.stop_services()
        try:
            self.save_settings()
        except Exception as error:
            self.fail(str(error))
        self.quitting = True
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, event):
        if not self.quitting and self.tray.isVisible():
            self.hide_to_tray()
            event.ignore()
        else:
            self.cancel_sleep()
            if not self.quitting:
                self.quit_app()
            event.accept()
