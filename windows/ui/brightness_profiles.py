"""Original Qt editor for named lux threshold profiles and a draggable step graph."""
from bisect import bisect_right
from copy import deepcopy

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QComboBox,
                               QLineEdit, QPushButton, QTableWidget, QDoubleSpinBox, QSpinBox,
                               QAbstractItemView, QHeaderView)

from windows.ui.lux import LuxSpinBox, format_lux
from windows.core.brightness_profiles import default_brightness_profiles, validate_profile, validate_profiles


class LuxStepGraph(QWidget):
    point_moved = Signal(int, float, int)
    point_selected = Signal(int)

    def __init__(self):
        super().__init__()
        self.points = [[0, 2], [100, 30], [300, 55]]
        self.current_lux = None
        self.error = False
        self.drag_index = None
        self.drag_scale = None
        self.setMinimumSize(360, 230)
        self.setAccessibleName("조도 구간별 밝기 그래프")
        self.setToolTip("파란 점을 드래그해 기준 조도와 밝기를 편집합니다. 첫 기준은 0 lux로 고정됩니다.")

    def set_points(self, points):
        self.points = deepcopy(points)
        self.error = False
        self.update()

    def plot_rect(self):
        return QRectF(48, 25, max(1, self.width() - 66), max(1, self.height() - 64))

    def maximum_lux(self):
        if self.drag_index is not None and self.drag_scale is not None:
            return self.drag_scale
        return min(65535, max(10, self.points[-1][0] * 1.2)) if self.points[-1][0] else 100

    def point_position(self, lux, brightness):
        rect = self.plot_rect()
        return QPointF(rect.left() + lux / self.maximum_lux() * rect.width(),
                       rect.bottom() - brightness / 100 * rect.height())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))
        rect = self.plot_rect()
        painter.setPen(QColor("#374151"))
        painter.drawText(QRectF(3, 1, 100, 20), "밝기 (%)")
        for index in range(6):
            y = rect.bottom() - rect.height() * index / 5
            x = rect.left() + rect.width() * index / 5
            painter.setPen(QPen(QColor("#dce3eb"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            painter.setPen(QColor("#4b5563"))
            painter.drawText(QRectF(0, y - 10, 41, 20), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(index * 20))
            painter.drawText(QRectF(x - 35, rect.bottom() + 3, 70, 18), Qt.AlignmentFlag.AlignCenter,
                             format_lux(self.maximum_lux() * index / 5))
        painter.setPen(QPen(QColor("#64748b"), 1))
        painter.drawRect(rect)
        painter.drawText(QRectF(rect.left(), self.height() - 20, rect.width(), 18), Qt.AlignmentFlag.AlignCenter, "조도 (lux)")
        if self.error:
            painter.setPen(QColor("#a62323"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "입력값을 확인하세요.")
            return
        path = QPainterPath(self.point_position(0, self.points[0][1]))
        previous = self.points[0][1]
        for lux, brightness in self.points[1:]:
            path.lineTo(self.point_position(lux, previous))
            path.lineTo(self.point_position(lux, brightness))
            previous = brightness
        path.lineTo(self.point_position(self.maximum_lux(), previous))
        painter.setPen(QPen(QColor("#2463bd"), 2))
        painter.drawPath(path)
        painter.setBrush(QColor("#ffffff"))
        for lux, brightness in self.points:
            painter.drawEllipse(self.point_position(lux, brightness), 4.5, 4.5)
        if self.current_lux is not None and 0 <= self.current_lux <= self.maximum_lux():
            index = bisect_right([point[0] for point in self.points], self.current_lux) - 1
            point = self.point_position(self.current_lux, self.points[index][1])
            painter.setPen(QPen(QColor("#d97706"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(point.x(), rect.top()), QPointF(point.x(), rect.bottom()))
            painter.setBrush(QColor("#d97706"))
            painter.drawEllipse(point, 4.5, 4.5)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.error:
            return
        for index, (lux, brightness) in enumerate(self.points):
            point = self.point_position(lux, brightness)
            if (point.x() - event.position().x()) ** 2 + (point.y() - event.position().y()) ** 2 <= 121:
                self.drag_scale = self.maximum_lux()
                self.drag_index = index
                self.point_selected.emit(index)
                return

    def mouseMoveEvent(self, event):
        if self.drag_index is None or self.error:
            return
        index = self.drag_index
        rect = self.plot_rect()
        lux = (event.position().x() - rect.left()) / rect.width() * self.maximum_lux()
        minimum = self.points[index - 1][0] + .1 if index else 0
        maximum = self.points[index + 1][0] - .1 if index + 1 < len(self.points) else 65535
        lux = round(max(minimum, min(maximum, lux)), 1) if index else 0
        brightness = max(0, min(100, round((rect.bottom() - event.position().y()) / rect.height() * 100)))
        self.point_moved.emit(index, lux, brightness)

    def mouseReleaseEvent(self, event):
        self.drag_index = None
        self.drag_scale = None
        self.update()


class BrightnessProfileEditor(QWidget):
    def __init__(self, profiles, selected):
        super().__init__()
        self.bank = deepcopy(profiles)
        self.selected = selected
        self.loading = False
        self.current_lux = None
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("사용자 프로필"))
        self.profiles = QComboBox()
        row.addWidget(self.profiles, 1)
        for title, method in (("새 프로필", self.new_profile), ("복제", self.duplicate_profile), ("삭제", self.delete_profile)):
            button = QPushButton(title)
            button.clicked.connect(method)
            row.addWidget(button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.name = QLineEdit()
        self.name.setMaxLength(40)
        row.addWidget(QLabel("이름"))
        row.addWidget(self.name, 1)
        rename = QPushButton("이름 변경")
        rename.clicked.connect(self.rename_profile)
        row.addWidget(rename)
        layout.addLayout(row)
        self.graph = LuxStepGraph()
        layout.addWidget(self.graph)
        self.live = QLabel("현재 조도 미확인 · 편집 내용은 밝기 설정 적용 후 사용합니다.")
        self.live.setWordWrap(True)
        layout.addWidget(self.live)
        row = QHBoxLayout()
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["기준 조도 이상 (lux)", "밝기 (%)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(130)
        row.addWidget(self.table, 2)
        form = QFormLayout()
        self.hysteresis = LuxSpinBox()
        self.hysteresis.setRange(0, 65535)
        self.hold = QDoubleSpinBox()
        self.hold.setRange(0, 10)
        self.hold.setDecimals(2)
        form.addRow("하강 이력 (lux)", self.hysteresis)
        form.addRow("전환 유지 (초)", self.hold)
        self.hysteresis.setToolTip("조도가 내려갈 때 현재 기준보다 이 값만큼 더 낮아져야 아래 구간으로 바뀝니다. 0이면 이력을 사용하지 않습니다.")
        for title, method in (("구간 추가", self.add_point), ("선택 구간 삭제", self.remove_point),
                              ("현재 조도로 구간 추가", self.add_current_lux)):
            button = QPushButton(title)
            button.clicked.connect(method)
            form.addRow(button)
        row.addLayout(form, 1)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.profiles.currentTextChanged.connect(self.select_profile)
        self.name.textChanged.connect(self.refresh_graph)
        self.hysteresis.valueChanged.connect(self.refresh_graph)
        self.hold.valueChanged.connect(self.refresh_graph)
        self.graph.point_selected.connect(self.table.selectRow)
        self.graph.point_moved.connect(self.move_point)
        self.refresh_choices()
        self.load_profile()

    def refresh_choices(self):
        with QSignalBlocker(self.profiles):
            self.profiles.clear()
            self.profiles.addItems([profile["name"] for profile in self.bank])
            self.profiles.setCurrentText(self.selected)

    def load_profile(self):
        profile = next(profile for profile in self.bank if profile["name"] == self.selected)
        self.loading = True
        self.name.setText(profile["name"])
        self.hysteresis.setValue(profile["hysteresis_lux"])
        self.hold.setValue(profile["hold_seconds"])
        self.set_points(profile["points"])
        self.loading = False
        self.refresh_graph()

    def set_points(self, points):
        self.table.setRowCount(len(points))
        for index, (lux, brightness) in enumerate(points):
            threshold = LuxSpinBox()
            threshold.setRange(0, 65535)
            threshold.setValue(lux)
            threshold.setEnabled(index != 0)
            percent = QSpinBox()
            percent.setRange(0, 100)
            percent.setValue(brightness)
            for column, widget in enumerate((threshold, percent)):
                self.table.setCellWidget(index, column, widget)
                widget.valueChanged.connect(self.refresh_graph)

    def draft(self):
        return validate_profile({"name": self.name.text().strip(),
            "points": [[self.table.cellWidget(row, 0).value(), self.table.cellWidget(row, 1).value()]
                       for row in range(self.table.rowCount())],
            "hysteresis_lux": self.hysteresis.value(), "hold_seconds": self.hold.value()})

    def refresh_graph(self, *_):
        if self.loading:
            return
        try:
            profile = self.draft()
            self.graph.set_points(profile["points"])
            self.status.setStyleSheet("color:#4b5563")
            self.status.setText("각 기준 이상부터 다음 기준 미만까지 지정 밝기를 사용합니다. 첫 0 lux 구간은 유지됩니다.")
        except ValueError as error:
            self.show_error(str(error), invalidate=True)

    def show_error(self, message, invalidate=False):
        self.status.setStyleSheet("color:#a62323")
        self.status.setText(message)
        if invalidate:
            self.graph.error = True
        self.graph.update()

    def stash(self):
        profile = self.draft()
        bank = deepcopy(self.bank)
        index = next(i for i, item in enumerate(bank) if item["name"] == self.selected)
        bank[index] = profile
        validate_profiles(bank, profile["name"])
        self.bank, self.selected = bank, profile["name"]

    def snapshot(self, include_draft=True):
        if include_draft:
            self.stash()
            self.refresh_choices()
        return deepcopy(self.bank), self.selected

    def select_profile(self, target):
        if not target or target == self.selected:
            return
        try:
            self.stash()
            self.selected = target
            self.refresh_choices()
            self.load_profile()
        except ValueError as error:
            self.refresh_choices()
            self.show_error(str(error))

    def unique_name(self, base):
        names = {item["name"].casefold() for item in self.bank}
        name, index = base[:32], 1
        while name.casefold() in names:
            index += 1
            name = f"{base[:32]} {index}"
        return name

    def create_profile(self, duplicate):
        try:
            self.stash()
            if len(self.bank) >= 32:
                raise ValueError("프로필은 최대 32개까지 만들 수 있습니다.")
            profile = deepcopy(next(item for item in self.bank if item["name"] == self.selected)) if duplicate else default_brightness_profiles()[0]
            profile["name"] = self.unique_name(f"{self.selected} 복사본" if duplicate else "새 프로필")
            self.bank.append(profile)
            self.selected = profile["name"]
            self.refresh_choices()
            self.load_profile()
        except ValueError as error:
            self.refresh_choices()
            self.show_error(str(error))

    def new_profile(self):
        self.create_profile(False)

    def duplicate_profile(self):
        self.create_profile(True)

    def rename_profile(self):
        try:
            self.stash()
            self.refresh_choices()
            self.name.setText(self.selected)
            self.refresh_graph()
        except ValueError as error:
            self.show_error(str(error))

    def delete_profile(self):
        if len(self.bank) <= 1:
            self.show_error("프로필을 하나 이상 유지해야 합니다.")
            return
        self.bank = [item for item in self.bank if item["name"] != self.selected]
        self.selected = self.bank[0]["name"]
        self.refresh_choices()
        self.load_profile()

    def add_point(self, checked=False, lux=None):
        try:
            points = self.draft()["points"]
            if len(points) >= 32:
                raise ValueError("구간은 최대 32개까지 만들 수 있습니다.")
            threshold = min(65535, points[-1][0] + 100) if lux is None else round(lux, 1)
            index = bisect_right([point[0] for point in points], threshold)
            brightness = points[max(0, index - 1)][1]
            points.insert(index, [threshold, brightness])
            validate_profile({**self.draft(), "points": points})
            self.set_points(points)
            self.table.selectRow(index)
            self.refresh_graph()
        except ValueError as error:
            self.show_error(str(error))

    def remove_point(self):
        index = self.table.currentRow()
        if index <= 0:
            self.show_error("첫 0 lux 구간은 삭제하지 않습니다. 다른 구간을 선택하세요.")
            return
        self.table.removeRow(index)
        self.refresh_graph()

    def move_point(self, index, lux, brightness):
        threshold, percent = self.table.cellWidget(index, 0), self.table.cellWidget(index, 1)
        with QSignalBlocker(threshold), QSignalBlocker(percent):
            threshold.setValue(lux)
            percent.setValue(brightness)
        self.refresh_graph()

    def set_current_lux(self, lux):
        if lux == self.current_lux:
            return
        self.current_lux = lux
        self.graph.current_lux = lux
        self.live.setText(("현재 조도 미확인" if lux is None else f"현재 조도 {format_lux(lux)} lux · 주황색 표시") +
                          " · 편집 내용은 밝기 설정 적용 후 사용합니다.")
        self.graph.update()

    def add_current_lux(self):
        if self.current_lux is None:
            self.show_error("최신 정상 조도 데이터가 필요합니다.")
            return
        self.add_point(lux=self.current_lux)
