"""Small set of shared controls for the everyday lighting and distance workflow."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QGroupBox, QLabel, QCheckBox, QSpinBox, QPushButton)
from windows.ui.lux import LuxSpinBox


class SimpleSettingsPage(QWidget):
    def __init__(self, panel):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(18)
        self.live = QLabel("센서를 연결하면 현재 조도와 거리가 표시됩니다.")
        self.live.setWordWrap(True)
        self.live.setStyleSheet("font-size:15px;color:#23665b;padding:8px")
        layout.addWidget(self.live)
        self.fields = {}
        light = QGroupBox("조명에 맞춰 밝기 바꾸기")
        form = QFormLayout(light)
        self.auto_brightness = self.checkbox(panel.auto_brightness, "자동 밝기 사용")
        form.addRow(self.auto_brightness)
        for name, caption in (("light_threshold_lux", "조명 ON 기준"),
                              ("light_on_brightness", "조명이 켜졌을 때 밝기"),
                              ("light_off_brightness", "조명이 꺼졌을 때 밝기")):
            widget = self.field(panel, name)
            widget.setSuffix(" lux" if name.endswith("lux") else " %")
            form.addRow(caption, widget)
        note = QLabel("기준 조도 미만이면 OFF 밝기, 기준 이상이면 ON 밝기를 사용합니다.")
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(light)
        presence = QGroupBox("자리를 비우면 화면 끄기")
        form = QFormLayout(presence)
        self.auto_presence = self.checkbox(panel.auto_presence, "자동 화면 꺼짐·켜짐 사용")
        form.addRow(self.auto_presence)
        distances = QHBoxLayout()
        minimum = self.field(panel, "tof_min_distance_cm")
        maximum = self.field(panel, "tof_max_distance_cm")
        minimum.setSuffix(" cm"); maximum.setSuffix(" cm")
        separator = QLabel("~")
        separator.setFixedWidth(16)
        distances.addWidget(minimum, 1)
        distances.addWidget(separator)
        distances.addWidget(maximum, 1)
        form.addRow("앉아 있을 때 거리 범위", distances)
        seconds = self.field(panel, "absence_seconds")
        seconds.setSuffix(" 초")
        form.addRow("범위 밖에서 기다릴 시간", seconds)
        note = QLabel("범위 밖 상태가 위 시간 동안 이어지면 5초 카운트다운 후 화면을 끕니다.\n"
                      "다시 범위 안으로 돌아오면 취소하거나 화면을 켭니다.\n"
                      "반사 대상이 없으면 부재로 판단하고, 통신·센서 오류일 때는 꺼짐을 보류합니다.")
        note.setWordWrap(True)
        form.addRow(note)
        layout.addWidget(presence)
        apply = QPushButton("설정 적용")
        apply.setMinimumHeight(44)
        apply.clicked.connect(panel.apply_requested.emit)
        layout.addWidget(apply)
        hint = QLabel("연결 / 상태에서 센서와 모니터를 연결하세요. 변경한 값은 설정 적용 후 사용합니다.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

    def field(self, panel, name):
        source = panel.fields[name]
        widget = LuxSpinBox() if name.endswith("lux") else QSpinBox()
        widget.setRange(source.minimum(), source.maximum())
        widget.setValue(source.value())
        widget.valueChanged.connect(source.setValue)
        source.valueChanged.connect(widget.setValue)
        self.fields[name] = widget
        return widget

    @staticmethod
    def checkbox(source, caption):
        widget = QCheckBox(caption)
        widget.setChecked(source.isChecked())
        widget.toggled.connect(source.setChecked)
        source.toggled.connect(widget.setChecked)
        return widget
