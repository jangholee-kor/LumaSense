"""Fixed, shared screen countdown display; all output stays in the runtime."""
import math
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton
from windows.core.display_controller import State


class ScreenStatusBanner(QWidget):
    cancel_requested = Signal()
    resume_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QHBoxLayout(self)
        words = QVBoxLayout()
        self.title = QLabel("센서 연결을 기다리고 있습니다")
        self.title.setStyleSheet("font-size:21px;font-weight:600")
        self.title.setWordWrap(True)
        self.detail = QLabel("화면 자동 꺼짐 상태가 여기에 표시됩니다.")
        self.detail.setWordWrap(True)
        words.addWidget(self.title)
        words.addWidget(self.detail)
        layout.addLayout(words, 1)
        self.cancel = QPushButton("꺼짐 취소")
        self.cancel.setMinimumHeight(40)
        self.cancel.clicked.connect(self.cancel_requested.emit)
        self.cancel.setVisible(False)
        layout.addWidget(self.cancel)
        self.resume = QPushButton("자동 제어 재개")
        self.resume.setMinimumHeight(40)
        self.resume.clicked.connect(self.resume_requested.emit)
        self.resume.setVisible(False)
        layout.addWidget(self.resume)
        self.tone = None
        self.set_tone("idle")

    def set_tone(self, tone):
        if self.tone == tone:
            return
        self.tone = tone
        background, border = {"idle": ("#edf7f4", "#bad9cf"),
                              "waiting": ("#fff7e6", "#e1b75b"),
                              "countdown": ("#fff0ee", "#db7b70")}[tone]
        self.setStyleSheet(f"ScreenStatusBanner {{background:{background};border:1px solid {border};border-radius:8px;}}")

    def update_status(self, runtime, now, controller):
        state = runtime.presence
        snap = runtime.sensors.snapshot(now)
        title, detail, tone, cancel = state.status_text(now), "", "idle", False
        if controller.state == State.COUNTDOWN:
            left = max(0, math.ceil(controller.deadline - now))
            title, detail, tone, cancel = f"{left}초 후 화면이 꺼집니다", "수동 화면 꺼짐 시험 · 취소할 수 있습니다.", "countdown", True
        elif runtime.external_block and controller.state == State.IDLE:
            title, detail = "자동 제어가 중단되었습니다", "설정과 센서 상태를 확인한 뒤 설정 적용 또는 자동 제어 재개를 누르세요."
        elif state.pending == "off":
            title, detail, tone = "화면 끄기를 요청하고 있습니다", "연결된 화면 전체에 적용됩니다.", "countdown"
        elif state.owns_off:
            title, detail = "화면 끄기 요청 완료", "다시 감지하면 화면 켜기를 요청합니다."
        elif not runtime.settings.auto_presence:
            title, detail = "자리 비움 자동 꺼짐이 꺼져 있습니다", "자동 화면 꺼짐·켜짐을 선택하고 설정 적용을 누르세요."
        elif now < runtime.pause_until:
            title, detail = "자동 제어 일시 중단", f"{math.ceil(runtime.pause_until - now)}초 후 재개 · 자동 제어 재개로 바로 시작할 수 있습니다."
        elif not snap.valid or not snap.packet or not snap.packet["sensor_ok"]:
            title, detail = "센서 확인 중 · 자동 꺼짐 보류", snap.reason
        elif not runtime.sensors.ready(now):
            title, detail = "센서 안정화 중", "정상 측정이 이어지면 자동으로 시작합니다."
        elif state.countdown_until is not None:
            left = max(0, math.ceil(state.countdown_until - now))
            title, detail, tone, cancel = f"{left}초 후 화면이 꺼집니다", "다시 감지하거나 꺼짐 취소를 누르면 취소됩니다.", "countdown", True
        elif state.reason == "연속 부재 확인 중":
            left = max(0, math.ceil(runtime.settings.absence_seconds - (now - state.absent_since)))
            title, detail, tone, cancel = f"자리 비움 · {left}초 후 꺼짐 카운트다운", "다시 범위 안으로 돌아오면 대기를 취소합니다.", "waiting", True
        elif state.reason == "인체 감지":
            title, detail = "사용 중 · 착석 범위 안입니다", "자리를 비우면 설정한 시간 뒤에 꺼짐 카운트다운을 시작합니다."
        else:
            detail = "이 조건이 해제되면 자리 비움 확인을 시작합니다."
        self.title.setText(title)
        self.detail.setText(detail)
        self.cancel.setVisible(cancel)
        self.cancel.setToolTip("수동 화면 꺼짐 시험 취소" if controller.state == State.COUNTDOWN else "자동 제어를 15분 중단하고 꺼짐을 취소합니다.")
        self.resume.setVisible(title == "자동 제어 일시 중단")
        self.set_tone(tone)
