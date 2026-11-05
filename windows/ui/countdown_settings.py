"""Shared countdown appearance controls and a display-only preview."""
from dataclasses import replace
import math
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout,
                               QLabel, QCheckBox, QComboBox, QSlider, QPushButton)

from windows.ui.countdown_overlay import CountdownOverlay


class CountdownSettingsPage(QWidget):
    def __init__(self, settings, apply_requested):
        super().__init__()
        self.base = settings
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("화면 꺼짐 카운트다운 팝업 표시")
        self.enabled.setChecked(settings.countdown_enabled)
        layout.addWidget(self.enabled)
        note = QLabel("팝업을 꺼도 화면이 꺼지기 전 5초 동안 취소할 수 있습니다.\n"
                      "키보드·마우스 입력, 착석 감지, 트레이 메뉴의 카운트다운 취소는 계속 동작합니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.style = QComboBox()
        for label, value in (("큰 숫자", "large"), ("작은 카드", "compact"), ("숫자만 · 아주 작게", "minimal")):
            self.style.addItem(label, value)
        self.style.setCurrentIndex(self.style.findData(settings.countdown_style))
        form.addRow("UI 고르기", self.style)
        self.scale = self.slider(form, "크기", 50, 150, settings.countdown_scale)
        self.position = QComboBox()
        for label, value in (("중앙", "center"), ("왼쪽 위", "top_left"), ("오른쪽 위", "top_right"),
                             ("왼쪽 아래", "bottom_left"), ("오른쪽 아래", "bottom_right")):
            self.position.addItem(label, value)
        self.position.setCurrentIndex(self.position.findData(settings.countdown_position))
        form.addRow("표시 위치", self.position)
        self.opacity = self.slider(form, "불투명도", 35, 100, settings.countdown_opacity)
        self.show_hint = QCheckBox("입력·착석 감지 취소 안내 표시")
        self.show_hint.setChecked(settings.countdown_show_hint)
        form.addRow(self.show_hint)
        layout.addLayout(form)
        note = QLabel("Windows 기본 모니터의 작업 표시줄을 제외한 영역에 표시합니다.\n"
                      "크기가 화면보다 크면 화면 안에 맞춥니다. 숫자만 UI에서는 안내 문구를 생략합니다.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.preview_button = QPushButton("5초 미리보기 · 화면을 끄지 않음")
        self.preview_button.clicked.connect(self.start_preview)
        layout.addWidget(self.preview_button)
        apply = QPushButton("설정 적용")
        apply.clicked.connect(apply_requested.emit)
        layout.addWidget(apply)
        layout.addWidget(QLabel("미리보기에는 편집 중인 값을 사용합니다. 실제 팝업은 설정 적용 후 바뀝니다."))
        layout.addStretch()
        self.preview = CountdownOverlay(settings, parent=self, preview=True)
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(100)
        self.preview_timer.timeout.connect(self.update_preview)
        self.preview_deadline = 0
        self.enabled.toggled.connect(self.update_controls)
        self.style.currentIndexChanged.connect(self.update_controls)
        self.position.currentIndexChanged.connect(self.refresh_preview)
        self.scale.valueChanged.connect(self.refresh_preview)
        self.opacity.valueChanged.connect(self.refresh_preview)
        self.show_hint.toggled.connect(self.refresh_preview)
        self.update_controls()

    @staticmethod
    def slider(form, caption, minimum, maximum, value):
        row = QHBoxLayout()
        widget = QSlider(Qt.Orientation.Horizontal)
        widget.setRange(minimum, maximum)
        widget.setValue(value)
        widget.setAccessibleName(caption)
        label = QLabel(f"{value}%")
        label.setMinimumWidth(48)
        widget.valueChanged.connect(lambda current: label.setText(f"{current}%"))
        row.addWidget(widget, 1)
        row.addWidget(label)
        form.addRow(caption, row)
        return widget

    def collect(self, base):
        return replace(base, countdown_enabled=self.enabled.isChecked(), countdown_style=self.style.currentData(),
                       countdown_scale=self.scale.value(), countdown_position=self.position.currentData(),
                       countdown_opacity=self.opacity.value(), countdown_show_hint=self.show_hint.isChecked())

    def update_controls(self):
        enabled = self.enabled.isChecked()
        for widget in (self.style, self.scale, self.position, self.opacity, self.preview_button):
            widget.setEnabled(enabled)
        self.show_hint.setEnabled(enabled and self.style.currentData() != "minimal")
        if not enabled:
            self.stop_preview()
        self.refresh_preview()

    def start_preview(self):
        self.preview_deadline = time.monotonic() + 5
        self.preview_timer.start()
        self.refresh_preview()

    def refresh_preview(self):
        if self.preview_timer.isActive():
            self.preview.set_settings(self.collect(self.base))
            self.update_preview()

    def update_preview(self):
        seconds = math.ceil(self.preview_deadline - time.monotonic())
        if seconds <= 0:
            self.stop_preview()
        else:
            self.preview.set_seconds(seconds)

    def stop_preview(self):
        self.preview_timer.stop()
        self.preview.set_seconds(None)

    def hideEvent(self, event):
        self.stop_preview()
        super().hideEvent(event)
