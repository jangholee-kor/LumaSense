"""Dashboard, connection controls and validated automation settings."""
from dataclasses import asdict
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLabel,
                               QCheckBox, QSpinBox, QDoubleSpinBox, QLineEdit, QComboBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QTabWidget)
from windows.core.settings import Settings


class AutomationPanel(QWidget):
    connect_requested = Signal()
    disconnect_requested = Signal()
    refresh_requested = Signal()
    apply_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    export_requested = Signal()
    import_requested = Signal()
    simulation_requested = Signal()
    radar_requested = Signal()
    monitor_requested = Signal()

    def __init__(self, settings, simulation=False):
        super().__init__()
        self.simulation = simulation
        layout = QVBoxLayout(self)
        banner = QLabel("시뮬레이션 · 실제 모니터와 USB 장치를 제어하지 않습니다." if simulation
                        else "센서 자동 제어 · 화면 상태는 마지막 요청과 실제 관찰을 구분합니다.")
        banner.setWordWrap(True)
        banner.setStyleSheet("font-size:16px;font-weight:600;color:#147d6b")
        layout.addWidget(banner)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        dashboard = QWidget()
        dash = QVBoxLayout(dashboard)
        group = QGroupBox("센서 연결")
        form = QFormLayout(group)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.addItem("자동 탐색", "")
        if settings.serial_port:
            self.port.addItem(settings.serial_port, settings.serial_port)
            self.port.setCurrentIndex(1)
        form.addRow("COM 포트", self.port)
        self.serial_number = QLineEdit(settings.serial_number)
        self.serial_number.setPlaceholderText("선택 사항: USB 일련번호로 재연결 장치 고정")
        form.addRow("USB 일련번호", self.serial_number)
        row = QHBoxLayout()
        for label, signal in (("포트 새로고침", self.refresh_requested), ("연결", self.connect_requested),
                              ("연결 해제 / 플래시 준비", self.disconnect_requested)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, target=signal: target.emit())
            row.addWidget(button)
        form.addRow(row)
        self.connection = QLabel("연결 대기")
        self.connection.setWordWrap(True)
        form.addRow("연결 상태", self.connection)
        self.target_monitor = QLabel(settings.monitor_id or "선택된 모니터 없음")
        self.target_monitor.setWordWrap(True)
        monitor_button = QPushButton("모니터 선택 / 탐색")
        monitor_button.clicked.connect(self.monitor_requested.emit)
        form.addRow(self.target_monitor, monitor_button)
        dash.addWidget(group)
        live = QGroupBox("현재 상태")
        status = QFormLayout(live)
        self.labels = {}
        for name, caption in (("lux", "조도"), ("brightness", "목표 / 요청 밝기"), ("presence", "인체 감지"),
                              ("motion", "움직임 / 정지"), ("distance", "감지 거리"), ("sensor", "센서 유효성"),
                              ("power", "존재 상태 / 화면 요청"), ("last", "마지막 제어")):
            label = QLabel("미확인")
            label.setWordWrap(True)
            self.labels[name] = label
            status.addRow(caption, label)
        dash.addWidget(live)
        self.auto_brightness = QCheckBox("자동 밝기")
        self.auto_presence = QCheckBox("인체 감지에 따른 자동 절전·복귀")
        self.auto_brightness.setToolTip("켜기는 설정 적용 후, 끄기는 즉시 반영합니다.")
        self.auto_presence.setToolTip("켜기는 설정 적용 후, 끄기는 즉시 반영합니다.")
        self.auto_brightness.setChecked(settings.auto_brightness)
        self.auto_presence.setChecked(settings.auto_presence)
        dash.addWidget(self.auto_brightness)
        dash.addWidget(self.auto_presence)
        row = QHBoxLayout()
        for label, signal in (("설정 적용", self.apply_requested), ("15분 일시 중단 / 절전 취소", self.pause_requested),
                              ("자동 제어 재개", self.resume_requested)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, target=signal: target.emit())
            row.addWidget(button)
        dash.addLayout(row)
        self.pause_status = QLabel("자동 밝기와 절전은 설정 적용 후 활성화됩니다.")
        self.pause_status.setWordWrap(True)
        dash.addWidget(self.pause_status)
        if simulation:
            sim = QGroupBox("가상 센서 입력")
            form = QFormLayout(sim)
            self.sim_lux = QDoubleSpinBox()
            self.sim_lux.setRange(0, 65535)
            self.sim_lux.setValue(125)
            self.sim_presence = QComboBox()
            for label, value in (("정지 상태 착석", "stationary"), ("움직임", "moving"), ("부재", "absent")):
                self.sim_presence.addItem(label, value)
            self.sim_error = QCheckBox("센서 오류 주입")
            form.addRow("Lux", self.sim_lux)
            form.addRow("감지 상태", self.sim_presence)
            form.addRow(self.sim_error)
            dash.addWidget(sim)
        dash.addStretch()
        self.tabs.addTab(dashboard, "대시보드")

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        self.fields = {}
        sections = [
            ("밝기 전환", [("brightness_min", "최소 밝기 (%)", 0, 100, False), ("brightness_max", "최대 밝기 (%)", 0, 100, False),
              ("transition_seconds", "전환 시간 (초)", 1, 3, True), ("ema_alpha", "EMA 반영 비율", .01, 1, True),
              ("brightness_interval", "명령 최소 간격 (초)", .2, 10, True), ("brightness_deadband", "변경 최소 폭 (%)", 1, 20, False),
              ("manual_pause_seconds", "수동 조절 후 자동 밝기 중단 (초)", 0, 86400, False)]),
            ("존재 감지", [("absence_seconds", "연속 부재 시간 (초)", 5, 3600, False), ("max_distance_cm", "PC 감지 범위 (cm)", 1, 900, False),
              ("recent_input_seconds", "최근 입력 보호 시간 (초)", 1, 3600, False),
              ("stabilization_seconds", "연결·오류 복구 후 안정화 (초)", 1, 60, True),
              ("sensor_stale_seconds", "센서 데이터 만료 (초)", .5, 15, True)])]
        for title, fields in sections:
            group = QGroupBox(title)
            form = QFormLayout(group)
            for name, label, low, high, floating in fields:
                widget = QDoubleSpinBox() if floating else QSpinBox()
                widget.setRange(low, high)
                widget.setValue(getattr(settings, name))
                form.addRow(label, widget)
                self.fields[name] = widget
            controls_layout.addWidget(group)
        self.use_input = QCheckBox("최근 Windows 키보드·마우스 입력 우선 (확인 실패 시 절전 보류)")
        self.use_input.setChecked(settings.use_recent_input)
        controls_layout.addWidget(self.use_input)
        self.production_wake = QComboBox()
        for label, value in (("ExecutionState 우선", "execution_state"), ("SC_MONITORPOWER 우선", "monitor_power"), ("마우스 이동 (별도 허용 필요)", "mouse_move")):
            self.production_wake.addItem(label, value)
        self.production_wake.setCurrentIndex(self.production_wake.findData(settings.production_wake_method))
        controls_layout.addWidget(self.production_wake)
        apply_button = QPushButton("설정 적용")
        apply_button.clicked.connect(self.apply_requested.emit)
        controls_layout.addWidget(apply_button)
        controls_layout.addStretch()
        self.tabs.addTab(controls, "자동 제어 설정")

        curve_page = QWidget()
        curve_layout = QVBoxLayout(curve_page)
        curve_layout.addWidget(QLabel("Lux 오름차순으로 지정한 점 사이를 선형 보간합니다."))
        self.curve = QTableWidget(0, 2)
        self.curve.setHorizontalHeaderLabels(["조도 (lux)", "목표 밝기 (%)"])
        self.set_curve(settings.curve)
        curve_layout.addWidget(self.curve)
        row = QHBoxLayout()
        add = QPushButton("점 추가")
        add.clicked.connect(lambda: self.curve.insertRow(self.curve.rowCount()) if self.curve.rowCount() < 32 else None)
        remove = QPushButton("선택 점 삭제")
        remove.clicked.connect(lambda: self.curve.removeRow(self.curve.currentRow()) if self.curve.currentRow() >= 0 else None)
        reset = QPushButton("기본 곡선")
        reset.clicked.connect(lambda: self.set_curve(Settings().curve))
        for button in (add, remove, reset):
            row.addWidget(button)
        curve_layout.addLayout(row)
        apply_curve = QPushButton("곡선과 설정 적용")
        apply_curve.clicked.connect(self.apply_requested.emit)
        curve_layout.addWidget(apply_curve)
        self.tabs.addTab(curve_page, "밝기 곡선 / 프로필")

        system = QWidget()
        system_layout = QVBoxLayout(system)
        self.connect_start = QCheckBox("시작 시 센서 자동 연결")
        self.connect_start.setChecked(settings.connect_on_start)
        self.minimized_start = QCheckBox("시작 시 트레이로 숨기기")
        self.minimized_start.setChecked(settings.start_minimized)
        self.login_start = QCheckBox("Windows 로그인 시 실행")
        self.login_start.setChecked(settings.login_startup)
        for control in (self.connect_start, self.minimized_start, self.login_start):
            system_layout.addWidget(control)
        for label, signal in (("시스템 설정 적용", self.apply_requested), ("설정 / 밝기 프로필 내보내기", self.export_requested),
                              ("설정 / 밝기 프로필 가져오기", self.import_requested), ("별도 시뮬레이션 창 열기", self.simulation_requested)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked=False, target=signal: target.emit())
            system_layout.addWidget(button)
        group = QGroupBox("LD2412 설정 명령")
        form = QFormLayout(group)
        self.engineering = QCheckBox("공학 모드 활성화")
        self.engineering.setChecked(settings.radar_engineering)
        form.addRow(self.engineering)
        self.radar_range = QCheckBox("레이더 감지 범위·유지 시간도 전송")
        self.radar_range.setChecked(settings.radar_apply_range)
        form.addRow(self.radar_range)
        self.radar_min = QSpinBox()
        self.radar_min.setRange(0, 13)
        self.radar_min.setValue(settings.radar_min_gate)
        self.radar_max = QSpinBox()
        self.radar_max.setRange(0, 13)
        self.radar_max.setValue(settings.radar_max_gate)
        self.radar_absence = QSpinBox()
        self.radar_absence.setRange(5, 65535)
        self.radar_absence.setValue(settings.radar_absence_seconds)
        form.addRow("최소 거리문 인덱스", self.radar_min)
        form.addRow("최대 거리문 인덱스", self.radar_max)
        form.addRow("레이더 무인 유지 시간 (초)", self.radar_absence)
        self.radar_thresholds = QCheckBox("거리문별 민감도 임계값도 전송")
        self.radar_thresholds.setChecked(settings.radar_apply_thresholds)
        form.addRow(self.radar_thresholds)
        self.thresholds = QTableWidget(14, 3)
        self.thresholds.setHorizontalHeaderLabels(["거리문 인덱스", "움직임 임계값", "정지 임계값"])
        for i in range(14):
            self.thresholds.setItem(i, 0, QTableWidgetItem(str(i)))
            for col, values in ((1, settings.radar_moving_thresholds), (2, settings.radar_stationary_thresholds)):
                spin = QSpinBox()
                spin.setRange(0, 100)
                spin.setValue(values[i])
                self.thresholds.setCellWidget(i, col, spin)
        self.thresholds.setMinimumHeight(200)
        form.addRow(self.thresholds)
        note = QLabel("표시값은 편집·저장할 요청값이며 장치에서 읽은 현재값이 아닙니다.\n"
                      "범위·유지 시간·임계값은 레이더에 저장됩니다. 거리문 길이는 레이더 해상도에 따릅니다.")
        note.setWordWrap(True)
        form.addRow(note)
        radar_button = QPushButton("레이더에 설정 전송 / ACK 확인")
        radar_button.clicked.connect(self.radar_requested.emit)
        form.addRow(radar_button)
        self.radar_result = QLabel("명령 없음")
        self.radar_result.setWordWrap(True)
        form.addRow(self.radar_result)
        system_layout.addWidget(group)
        system_layout.addStretch()
        self.tabs.addTab(system, "시스템 / 레이더")

    def set_curve(self, points):
        self.curve.setRowCount(len(points))
        for row, point in enumerate(points):
            for col, value in enumerate(point):
                self.curve.setItem(row, col, QTableWidgetItem(str(value)))

    def set_ports(self, values):
        selected = self.selected_port()
        self.port.clear()
        self.port.addItem("자동 탐색", "")
        for value in values:
            self.port.addItem(f"{value['port']} · {value['description']}", value["port"])
        index = self.port.findData(selected)
        if index < 0 and selected:
            self.port.addItem(selected, selected)
            index = self.port.count() - 1
        self.port.setCurrentIndex(max(0, index))

    def selected_port(self):
        index = self.port.currentIndex()
        if index >= 0 and self.port.currentText() == self.port.itemText(index):
            return self.port.currentData() or ""
        return self.port.currentText().strip()

    def collect(self, base):
        result = Settings(**asdict(base))
        result.serial_port = self.selected_port()
        result.serial_number = self.serial_number.text().strip()
        result.auto_brightness = self.auto_brightness.isChecked()
        result.auto_presence = self.auto_presence.isChecked()
        for name, widget in self.fields.items():
            setattr(result, name, widget.value())
        result.use_recent_input = self.use_input.isChecked()
        result.production_wake_method = self.production_wake.currentData()
        result.connect_on_start = self.connect_start.isChecked()
        result.start_minimized = self.minimized_start.isChecked()
        result.login_startup = self.login_start.isChecked()
        result.radar_engineering = self.engineering.isChecked()
        result.radar_apply_range = self.radar_range.isChecked()
        result.radar_min_gate = self.radar_min.value()
        result.radar_max_gate = self.radar_max.value()
        result.radar_absence_seconds = self.radar_absence.value()
        result.radar_apply_thresholds = self.radar_thresholds.isChecked()
        result.radar_moving_thresholds = [self.thresholds.cellWidget(i, 1).value() for i in range(14)]
        result.radar_stationary_thresholds = [self.thresholds.cellWidget(i, 2).value() for i in range(14)]
        try:
            result.curve = [[float(self.curve.item(row, col).text()) for col in range(2)] for row in range(self.curve.rowCount())]
        except (AttributeError, ValueError):
            raise ValueError("곡선의 모든 셀에 숫자를 입력하세요.") from None
        result.validate()
        return result

    def radar_request(self):
        request = {"cmd": "radar_config", "engineering": self.engineering.isChecked()}
        if self.radar_range.isChecked():
            if self.radar_min.value() > self.radar_max.value():
                raise ValueError("레이더 최소 거리문은 최대 거리문 이하여야 합니다.")
            request.update(min_gate=self.radar_min.value(), max_gate=self.radar_max.value(), absence_seconds=self.radar_absence.value())
        if self.radar_thresholds.isChecked():
            request.update(moving_thresholds=[self.thresholds.cellWidget(i, 1).value() for i in range(14)],
                           stationary_thresholds=[self.thresholds.cellWidget(i, 2).value() for i in range(14)])
        return request
