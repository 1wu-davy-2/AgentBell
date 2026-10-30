from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from agentbell.ui.icons import make_app_icon
from agentbell.ui.tray import TrayIcon

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_tray_about_action_emits_signal(qapp):
    tray = TrayIcon(make_app_icon(), 18766, True)
    try:
        menu = tray.contextMenu()
        assert menu is not None
        actions = {action.text(): action for action in menu.actions()}
        assert "关于 AgentBell…" in actions
        assert "退出" in actions

        emitted: list[bool] = []
        tray.about_requested.connect(lambda: emitted.append(True))
        actions["关于 AgentBell…"].trigger()
        assert emitted == [True]
    finally:
        tray.hide()
        tray.deleteLater()
