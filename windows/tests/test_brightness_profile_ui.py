import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from windows.core.settings import Settings
from windows.core.brightness_profiles import default_brightness_profiles
from windows.ui.brightness_profiles import BrightnessProfileEditor
from windows.ui.automation_panel import AutomationPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def editor(app):
    widget = BrightnessProfileEditor(default_brightness_profiles(), "기본")
    widget.resize(900, 650)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()


def test_named_profiles_switch_without_losing_valid_edits_and_can_be_deleted(editor):
    editor.table.cellWidget(1, 1).setValue(33)
    editor.duplicate_profile()
    copied = editor.selected
    assert copied != "기본" and editor.table.cellWidget(1, 1).value() == 33
    editor.name.setText("야간")
    editor.rename_profile()
    editor.table.cellWidget(0, 1).setValue(1)
    editor.profiles.setCurrentText("기본")
    assert editor.table.cellWidget(0, 1).value() == 2
    editor.profiles.setCurrentText("야간")
    assert editor.table.cellWidget(0, 1).value() == 1
    editor.delete_profile()
    assert editor.selected == "기본" and len(editor.bank) == 1
    editor.delete_profile()
    assert len(editor.bank) == 1 and "하나 이상" in editor.status.text()


def test_bad_threshold_or_duplicate_name_blocks_switch_without_losing_draft(editor):
    editor.new_profile()
    target = editor.selected
    editor.profiles.setCurrentText("기본")
    editor.table.cellWidget(1, 0).setValue(0)
    assert editor.graph.error
    editor.profiles.setCurrentText(target)
    assert editor.profiles.currentText() == "기본"
    assert editor.table.cellWidget(1, 0).value() == 0
    with pytest.raises(ValueError):
        editor.snapshot()
    editor.table.cellWidget(1, 0).setValue(100)
    editor.name.setText(target)
    with pytest.raises(ValueError, match="중복"):
        editor.snapshot()


def test_current_lux_addition_stale_rejection_and_base_row_protection(editor):
    editor.set_current_lux(171.25)
    editor.add_current_lux()
    points = editor.draft()["points"]
    assert points[2] == [171.2, 30]
    count = editor.table.rowCount()
    editor.set_current_lux(None)
    editor.add_current_lux()
    assert editor.table.rowCount() == count and "최신 정상" in editor.status.text()
    editor.table.selectRow(0)
    editor.remove_point()
    assert editor.table.rowCount() == count
    editor.table.selectRow(2)
    editor.remove_point()
    assert editor.table.rowCount() == count - 1
    assert not editor.table.cellWidget(0, 0).isEnabled()


def test_real_graph_drag_updates_table_and_keeps_threshold_order(app, editor):
    graph = editor.graph
    start = graph.point_position(100, 30).toPoint()
    end = graph.point_position(150, 70).toPoint()
    QTest.mousePress(graph, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(graph, end)
    QTest.mouseRelease(graph, Qt.MouseButton.LeftButton, pos=end)
    app.processEvents()
    assert abs(editor.table.cellWidget(1, 0).value() - 150) < 1
    assert abs(editor.table.cellWidget(1, 1).value() - 70) <= 1
    start = graph.point_position(0, 2).toPoint()
    QTest.mousePress(graph, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(graph, QPoint(start.x() + 40, start.y() - 40))
    QTest.mouseRelease(graph, Qt.MouseButton.LeftButton)
    assert editor.table.cellWidget(0, 0).value() == 0


def test_apply_collects_bank_and_hidden_invalid_draft_does_not_break_legacy_modes(app, tmp_path):
    panel = AutomationPanel(Settings())
    try:
        panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("steps"))
        editor = panel.profile_editor
        editor.name.setText("집")
        editor.table.cellWidget(1, 0).setValue(200)
        editor.table.cellWidget(1, 1).setValue(40)
        settings = panel.collect(Settings())
        path = tmp_path / "settings.json"
        settings.save(path)
        restored = Settings.load(path)
        assert restored.brightness_profile == "집" and restored.brightness_mode == "steps"
        assert restored.brightness_profiles[0]["points"][1] == [200, 40]
        panel.curve.insertRow(0)
        assert panel.collect(settings).brightness_mode == "steps"
        editor.table.cellWidget(1, 0).setValue(0)
        panel.brightness_mode.setCurrentIndex(panel.brightness_mode.findData("two_level"))
        assert panel.collect(settings).brightness_mode == "two_level"
    finally:
        panel.close()
