import math
import os
import subprocess
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu, QPushButton, QSlider,
                               QSpinBox, QSystemTrayIcon, QTextEdit, QVBoxLayout, QWidget)

from windows.core.brightness import TwinkleTrayBackend, discover_twinkle
from windows.core.display_controller import State


class Signals(QObject):
    done = Signal(object)
    error = Signal(str)


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
    def __init__(self, diagnostics, settings, controller, backend=None, auto_scan=True):
        super().__init__()
        self.log, self.settings, self.controller = diagnostics, settings, controller
        self.backend = backend
        self.busy = False
        self.quitting = False
        self.last_test = ""
        self.jobs = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.setWindowTitle("LumaSense · Smart Monitor Controller")
        self.setWindowIcon(app_icon())
        self.resize(900, 820)
        self.setStyleSheet("QGroupBox{font-weight:600;margin-top:12px;padding-top:16px} QPushButton{padding:7px 12px} QLineEdit,QComboBox,QSpinBox{padding:5px}")
        body = QWidget()
        layout = QVBoxLayout(body)
        heading = QLabel("Smart Monitor Controller  /  Phase 1")
        heading.setStyleSheet("font-size:22px;font-weight:600")
        layout.addWidget(heading)
        note = QLabel("수동 모니터 제어 검증 · 센서 자동 제어는 Phase 1 검증 후 연결합니다.\nAPI 응답과 화면의 실제 동작은 별도로 기록합니다.")
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
        self.mouse = QCheckBox("마우스 이동 복귀 허용 (포인터 위치에 잠시 영향을 줄 수 있음)")
        self.mouse.setChecked(settings.allow_mouse)
        form.addRow(self.mouse)
        form.addRow(QLabel("1차 요청 5초 후 다른 API로 추가 복귀를 시도합니다.\n로그의 primary / fallback 시각으로 각 방식의 결과를 구분하세요."))
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
        layout.addWidget(self.output, 1)
        footer = QHBoxLayout()
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
        layout.addLayout(footer)
        self.setCentralWidget(body)

        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Smart Monitor Controller · 수동 검증")
        menu = QMenu(self)
        for label, slot in [("설정 / 시험 창 열기", self.showNormal), ("화면 절전 시험", self.tray_sleep),
                             ("카운트다운 취소", self.cancel_sleep), ("복귀 요청", self.wake_now), ("종료", self.quit_app)]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.showNormal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.message(f"로그 위치: {self.log.root}")
        if auto_scan:
            QTimer.singleShot(0, self.scan_monitors)

    def message(self, text):
        self.output.append(text)

    def fail(self, error):
        self.log.event("ui_error", error=error)
        self.message(f"오류: {error}")

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
        self.settings.monitor_id = self.monitors.currentData() or ""
        self.settings.wake_method = self.method.currentData()
        self.settings.recovery_seconds = self.delay.value()
        self.settings.allow_mouse = self.mouse.isChecked()
        self.settings.save(self.log.root / "settings.json")

    def scan_monitors(self):
        if self.controller.state != State.IDLE:
            return
        configured = self.path.text().strip()
        def scan():
            exe = discover_twinkle(configured)
            if not exe:
                raise FileNotFoundError("Twinkle Tray를 찾지 못했습니다. 설치 경로를 지정하세요.")
            backend = TwinkleTrayBackend(exe, self.log)
            return exe, backend, backend.monitors()
        def done(result):
            exe, self.backend, monitors = result
            self.path.setText(str(exe))
            selected = self.monitors.currentData() or self.settings.monitor_id
            self.monitors.blockSignals(True)
            self.monitors.clear()
            self.monitor_list = monitors
            for monitor in monitors:
                self.monitors.addItem(f"{monitor.name} · {monitor.kind} · {monitor.identifier}", monitor.identifier)
            self.monitors.setCurrentIndex(max(0, self.monitors.findData(selected)))
            self.monitors.blockSignals(False)
            self.selection_changed()
            self.message(f"모니터 {len(monitors)}대 검색됨. 대상 모니터를 확인하세요.")
        self.submit(scan, done)

    def selection_changed(self):
        for monitor in getattr(self, "monitor_list", []):
            if monitor.identifier == self.monitors.currentData():
                self.reported.setText(f"Twinkle Tray 보고 밝기: {monitor.brightness}% (실제 휘도 측정 아님)")

    def launch_twinkle(self):
        exe = discover_twinkle(self.path.text().strip())
        if not exe:
            self.fail("Twinkle Tray를 찾지 못했습니다.")
            return
        subprocess.Popen([str(exe)], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.log.event("twinkle_started", executable=str(exe))
        self.message("Twinkle Tray 실행을 요청했습니다. 잠시 후 목록을 새로고침하세요.")

    def set_brightness(self, value):
        if self.controller.state != State.IDLE or not self.backend or not self.monitors.currentData():
            self.fail("진행 중인 절전 시험이 끝난 뒤 모니터를 선택하세요.")
            return
        backend, identifier = self.backend, self.monitors.currentData()
        test_id = uuid.uuid4().hex
        def change():
            result = backend.set_brightness(identifier, value)
            self.log.event("brightness_test", test_id=test_id, monitor_id=identifier, percent=value, result=result)
            return result
        def done(result):
            self.last_test = test_id
            self.observation.setCurrentIndex(0)
            self.message(f"{value}% 밝기 요청 접수 · 시험 {test_id} · 실제 변화는 관찰 후 기록하세요.")
        self.submit(change, done)

    def start_sleep(self):
        if self.busy:
            self.message("진행 중인 명령이 끝난 뒤 다시 시도하세요.")
            return
        try:
            self.save_settings()
            if self.method.currentData() == "mouse_move" and not self.mouse.isChecked():
                raise ValueError("마우스 이동 복귀를 먼저 허용하세요.")
            self.controller.start()
            self.cancel_button.setEnabled(True)
            self.sleep_button.setEnabled(False)
            self.wake_button.setEnabled(False)
            for widget in (self.method, self.delay, self.mouse):
                widget.setEnabled(False)
        except Exception as error:
            self.fail(str(error))

    def tray_sleep(self):
        self.showNormal()
        self.raise_()
        self.start_sleep()

    def cancel_sleep(self):
        if self.controller.cancel():
            self.power_status.setText("절전 시험 취소됨 · 화면 절전 명령 없음")
            self.reset_controls()

    def reset_controls(self):
        self.cancel_button.setEnabled(False)
        self.sleep_button.setEnabled(True)
        self.wake_button.setEnabled(True)
        for widget in (self.method, self.delay, self.mouse):
            widget.setEnabled(True)

    def tick(self):
        if self.controller.state != State.COUNTDOWN:
            return
        remaining = self.controller.deadline - self.controller.clock()
        self.power_status.setText(f"전체 화면 절전까지 {max(0, math.ceil(remaining))}초 · 취소 가능")
        if remaining <= 0 and not self.busy:
            self.cancel_button.setEnabled(False)
            method, seconds, allow = self.method.currentData(), self.delay.value(), self.mouse.isChecked()
            # Move out of COUNTDOWN before the next event-loop tick submits again.
            self.timer.stop()
            self.last_test = self.controller.test_id
            self.observation.setCurrentIndex(0)
            self.power_status.setText(f"절전 요청 진행 · {seconds}초 후 {method} 복귀 요청 예정")
            self.submit(lambda: self.controller.execute(method, seconds, allow), lambda result: self.message(str(result)))
            # The detached helper performs recovery even if this timer/GUI fails.
            QTimer.singleShot((seconds + 16) * 1000, self.finish_sleep)

    def finish_sleep(self):
        self.controller.finish()
        self.reset_controls()
        self.timer.start()
        self.power_status.setText("복귀 시도 시간 경과 · 화면 상태는 관찰 후 기록하세요.")

    def wake_now(self):
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

    def hide_to_tray(self):
        if self.tray.isVisible() and self.controller.state == State.IDLE:
            self.hide()
        else:
            self.message("트레이가 없거나 절전 시험 중이므로 창을 유지합니다.")

    def quit_app(self):
        self.cancel_sleep()
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
