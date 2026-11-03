"""Non-activating, primary-screen overlay for the final screen-off countdown."""
import math
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy
from windows.core.display_controller import State


def countdown_seconds(runtime, now, controller):
    if controller.state == State.COUNTDOWN:
        clock = getattr(controller, "clock", lambda: now)
        left = controller.deadline - clock()
    else:
        state = runtime.presence
        if (not runtime.settings.auto_presence or runtime.external_block or now < runtime.pause_until
                or state.owns_off or state.pending is not None or state.countdown_until is None
                or not runtime.sensors.ready(now)):
            return None
        snapshot = runtime.sensors.snapshot(now)
        if snapshot.packet["presence"]:
            return None
        left = state.countdown_until - now
    return min(5, math.ceil(left)) if left > 0 else None


def overlay_geometry(screen):
    rect = QRect(0, 0, min(760, max(1, screen.width() - 64)),
                 min(820, max(1, screen.height() - 64)))
    rect.moveCenter(screen.center())
    return rect


class CountdownOverlay(QWidget):
    cancel_requested = Signal()

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle("LumaSense · 화면 꺼짐 카운트다운")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QLabel {color:#f9fafb;background:transparent;border:0;}"
                           "QPushButton {color:#111827;background:#fbbf24;border:0;border-radius:10px;"
                           "font-size:20px;padding:12px 28px;}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        self.caption = QLabel("화면이 꺼집니다")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("font-size:28px;font-weight:600")
        layout.addWidget(self.caption)
        self.number = QLabel()
        self.number.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setStyleSheet("color:#fbbf24")
        layout.addWidget(self.number, 1)
        self.cancel = QPushButton("꺼짐 취소")
        self.cancel.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self.cancel, 0, Qt.AlignmentFlag.AlignHCenter)
        self.seconds = None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(17, 24, 39, 242))
        painter.setPen(QPen(QColor("#f59e0b"), 3))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), 28, 28)

    def set_seconds(self, seconds):
        if seconds is None or not 1 <= seconds <= 5:
            self.seconds = None
            self.hide()
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            self.hide()
            return
        geometry = overlay_geometry(screen.geometry())
        if self.geometry() != geometry:
            self.setGeometry(geometry)
            font = QFont("Segoe UI")
            font.setPixelSize(max(72, int(geometry.height() * .52)))
            font.setWeight(QFont.Weight.Bold)
            self.number.setFont(font)
        if self.seconds != seconds:
            self.seconds = seconds
            self.number.setText(str(seconds))
        if not self.isVisible():
            self.show()
            self.raise_()
