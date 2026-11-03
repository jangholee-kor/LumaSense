"""Compact lux values shared by every UI display and editor."""
from PySide6.QtWidgets import QDoubleSpinBox, QStyledItemDelegate


def format_lux(value):
    return "미확인" if value is None else f"{value:.1f}".rstrip("0").rstrip(".")


class LuxSpinBox(QDoubleSpinBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(1)
        self.setRange(0, 65535)
        self.setSingleStep(0.1)

    def textFromValue(self, value):
        return format_lux(value)


class LuxDelegate(QStyledItemDelegate):
    def displayText(self, value, locale):
        try:
            return format_lux(float(value))
        except (TypeError, ValueError):
            return str(value)

    def createEditor(self, parent, option, index):
        return LuxSpinBox(parent)
