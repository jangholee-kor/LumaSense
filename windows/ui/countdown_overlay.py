"""Configurable non-activating overlay for the final screen-off countdown."""
import math
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QPainter, QColor, QPen
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSizePolicy, QLayout
from windows.core.display_controller import State
from windows.core.settings import Settings


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


def overlay_geometry(screen, style="large", scale=100, position="center"):
    width, height = {"large": (760, 820), "compact": (320, 200), "minimal": (112, 112)}[style]
    margin = min(24, max(0, (min(screen.width(), screen.height()) - 1) // 2))
    rect = QRect(0, 0, min(round(width * scale / 100), max(1, screen.width() - margin * 2)),
                 min(round(height * scale / 100), max(1, screen.height() - margin * 2)))
    if position == "center":
        rect.moveCenter(screen.center())
    else:
        rect.moveLeft(screen.left() + margin if position.endswith("left") else screen.right() - margin - rect.width() + 1)
        rect.moveTop(screen.top() + margin if position.startswith("top") else screen.bottom() - margin - rect.height() + 1)
    return rect


class CountdownOverlay(QWidget):
    def __init__(self, settings=None, parent=None, preview=False):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle("LumaSense · 화면 꺼짐 카운트다운")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet("QLabel {color:#f9fafb;background:transparent;border:0;}")
        self.layout_box = layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.caption = QLabel("표시 미리보기" if preview else "화면이 꺼집니다")
        self.caption.setWordWrap(True)
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption.setStyleSheet("font-size:28px;font-weight:600")
        layout.addWidget(self.caption)
        self.number = QLabel()
        self.number.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.number.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.number.setStyleSheet("color:#fbbf24")
        layout.addWidget(self.number, 1)
        self.hint = QLabel("화면을 끄지 않습니다" if preview else "키보드·마우스 입력 또는 착석 감지 시 취소")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setStyleSheet("font-size:18px")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.seconds = None
        self.preview = preview
        self.set_settings(settings or Settings())

    def set_settings(self, settings):
        self._appearance = None
        self.enabled = settings.countdown_enabled
        self.style = settings.countdown_style
        self.scale = settings.countdown_scale
        self.position = settings.countdown_position
        self.setWindowOpacity(settings.countdown_opacity / 100)
        self.caption.setVisible(self.style != "minimal")
        self.hint.setText("화면을 끄지 않습니다" if self.preview else (
            "입력·착석 감지로 취소" if self.style == "compact" else "키보드·마우스 입력 또는 착석 감지 시 취소"))
        self.hint.setVisible(self.style != "minimal" and settings.countdown_show_hint)
        if not self.enabled:
            self.set_seconds(None)
        elif self.seconds is not None:
            self.set_seconds(self.seconds)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(17, 24, 39))
        painter.setPen(QPen(QColor("#f59e0b"), 3))
        radius = min(28, min(self.width(), self.height()) * (.5 if self.style == "minimal" else .14))
        painter.drawRoundedRect(self.rect().adjusted(2, 2, -2, -2), radius, radius)

    def set_seconds(self, seconds):
        if not self.enabled or seconds is None or not 1 <= seconds <= 5:
            self.seconds = None
            self.hide()
            return
        screen = QApplication.primaryScreen()
        if screen is None:
            self.hide()
            return
        geometry = overlay_geometry(screen.availableGeometry(), self.style, self.scale, self.position)
        appearance = (geometry, self.style, self.scale)
        if self._appearance != appearance:
            self._appearance = appearance
            self.update_geometry(geometry)
        if self.seconds != seconds:
            self.seconds = seconds
            self.number.setText(str(seconds))
        if not self.isVisible():
            self.show()
            self.raise_()

    def update_geometry(self, geometry):
        factor = min(geometry.width() / {"large": 760, "compact": 320, "minimal": 112}[self.style],
                     geometry.height() / {"large": 820, "compact": 200, "minimal": 112}[self.style])
        margin = max(2, round((28 if self.style == "large" else 10) * factor))
        self.layout_box.setContentsMargins(margin, margin, margin, margin)
        self.layout_box.setSpacing(max(1, round(8 * factor)))
        self.caption.setStyleSheet(f"font-size:{max(8, round((28 if self.style == 'large' else 18) * factor))}px;font-weight:600")
        self.hint.setStyleSheet(f"font-size:{max(7, round((18 if self.style == 'large' else 12) * factor))}px")
        font = QFont("Segoe UI")
        font.setPixelSize(max(12, int(geometry.height() * (.65 if self.style == "minimal" else .44))))
        font.setWeight(QFont.Weight.Bold)
        self.number.setFont(font)
        self.setGeometry(geometry)
