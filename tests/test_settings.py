from __future__ import annotations

import json
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTime
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from agentbell.config import AppConfig, load_config
from agentbell.ui.settings import SettingsDialog

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def make_dialog(qapp, config_path=None) -> SettingsDialog:
    dialog = SettingsDialog(
        AppConfig(port=18765, token="old", auto_close_seconds=20),
        config_path,
        logging.getLogger("agentbell.tests"),
    )
    return dialog


def test_save_validates_and_writes_config(qapp, tmp_path):
    path = tmp_path / "config.json"
    dialog = make_dialog(qapp, path)
    try:
        dialog._port_spin.setValue(18888)
        dialog._token_edit.setText("new-token")
        dialog._auto_close_spin.setValue(12)
        dialog._success_popup_check.setChecked(False)
        dialog._open_center_check.setChecked(False)
        dialog._overlay_image_edit.setText(str(tmp_path / "bg.png"))
        dialog._quiet_enabled_check.setChecked(True)
        dialog._quiet_start_edit.setTime(QTime.fromString("21:30", "HH:mm"))
        dialog._quiet_end_edit.setTime(QTime.fromString("07:15", "HH:mm"))
        dialog._digest_threshold_spin.setValue(6)
        dialog._popup_mode_combo.setCurrentIndex(
            dialog._popup_mode_combo.findData("center")
        )
        dialog._popup_skin_combo.setCurrentIndex(
            dialog._popup_skin_combo.findData("amber")
        )
        dialog._hold_when_locked_check.setChecked(False)
        dialog._agent_enabled_check.setChecked(False)
        dialog._agent_interval_spin.setValue(300)
        dialog._agent_max_spin.setValue(42)
        dialog._template_edits["failed"].setText("上一轮【{title}】出错了")
        dialog._rules_editor.setPlainText(
            json.dumps(
                [
                    {
                        "name": "失败需确认",
                        "status": "failed",
                        "priority": "critical",
                        "require_ack": True,
                    }
                ],
                ensure_ascii=False,
            )
        )
        dialog._channels_editor.setPlainText(
            json.dumps(
                [
                    {
                        "type": "ntfy",
                        "topic": "agentbell-test",
                        "min_priority": "normal",
                        "when_away": False,
                    }
                ],
                ensure_ascii=False,
            )
        )

        dialog._save()

        assert dialog.result_config is not None
        loaded, created = load_config(path)
        assert created is False
        assert loaded.port == 18888
        assert loaded.token == "new-token"
        assert loaded.auto_close_seconds == 12
        assert loaded.success_popup is False
        assert loaded.open_center_on_start is False
        assert loaded.overlay_image == str(tmp_path / "bg.png")
        assert loaded.quiet_hours.enabled is True
        assert loaded.quiet_hours.start == "21:30"
        assert loaded.quiet_hours.end == "07:15"
        assert loaded.digest.threshold == 6
        assert loaded.popup_mode == "center"
        assert loaded.popup_skin == "amber"
        assert loaded.hold_when_locked is False
        assert loaded.agent_sessions.enabled is False
        assert loaded.agent_sessions.scan_interval_seconds == 300
        assert loaded.agent_sessions.max_sessions == 42
        assert loaded.templates["failed"] == "上一轮【{title}】出错了"
        assert len(loaded.rules) == 1
        assert loaded.rules[0].require_ack is True
        assert loaded.channels[0].type == "ntfy"
        assert loaded.channels[0].topic == "agentbell-test"
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_invalid_json_does_not_save(qapp, tmp_path):
    path = tmp_path / "config.json"
    dialog = make_dialog(qapp, path)
    try:
        errors: list[str] = []
        dialog._show_error = errors.append  # type: ignore[method-assign]
        dialog._rules_editor.setPlainText('{"not": "a list"}')
        dialog._save()

        assert dialog.result_config is None
        assert errors and "规则" in errors[0]
        assert not path.exists()
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_invalid_template_is_reported(qapp):
    dialog = make_dialog(qapp)
    try:
        errors: list[str] = []
        dialog._show_error = errors.append  # type: ignore[method-assign]
        dialog._template_edits["succeeded"].setText("没有占位符")
        dialog._save()

        assert dialog.result_config is None
        assert errors and "title" in errors[0]
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_every_settings_tab_is_scrollable(qapp):
    dialog = make_dialog(qapp)
    try:
        assert dialog._tabs.count() == 6
        for index in range(dialog._tabs.count()):
            page = dialog._tabs.widget(index)
            assert isinstance(page, QScrollArea)
            assert page.widgetResizable() is True
            assert page.widget() is not None
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_empty_rules_and_channels_are_valid(qapp):
    dialog = make_dialog(qapp)
    try:
        dialog._rules_editor.setPlainText("")
        dialog._channels_editor.setPlainText("[]")
        dialog._save()
        assert dialog.result_config is not None
        assert dialog.result_config.rules == ()
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_preview_uses_selected_appearance_and_cleans_up(qapp, tmp_path):
    dialog = make_dialog(qapp)
    try:
        image_path = tmp_path / "bg.png"
        dialog._popup_mode_combo.setCurrentIndex(
            dialog._popup_mode_combo.findData("overlay")
        )
        dialog._popup_skin_combo.setCurrentIndex(
            dialog._popup_skin_combo.findData("amber")
        )
        dialog._overlay_image_edit.setText(str(image_path))
        dialog._preview_popup()

        preview = dialog._preview
        assert preview is not None
        assert preview.popup_mode == "overlay"
        assert preview.popup_skin == "amber"
        assert preview._overlay_backdrop is not None
        assert preview._overlay_backdrop.has_image is False

        preview.dismiss("ack")
        QTest.qWait(260)
        assert dialog._preview is None
    finally:
        if dialog._preview is not None:
            dialog._preview.close_now()
        dialog.deleteLater()
        QTest.qWait(20)
