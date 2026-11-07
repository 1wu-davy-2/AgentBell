from __future__ import annotations

import os
from datetime import datetime, timedelta

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


def _submenu(menu, title):
    for action in menu.actions():
        submenu = action.menu()
        if action.text() == title and submenu is not None:
            return submenu
    raise AssertionError(f"未找到子菜单：{title}")


def test_tray_pause_menu_emits_minutes_and_tracks_tooltip(qapp):
    tray = TrayIcon(make_app_icon(), 18766, True)
    try:
        menu = tray.contextMenu()
        pause_menu = _submenu(menu, "勿扰模式")
        actions = {action.text(): action for action in pause_menu.actions()}
        assert actions["关闭勿扰"].isEnabled() is False

        emitted: list[int] = []
        tray.pause_requested.connect(emitted.append)
        actions["暂停 30 分钟"].trigger()
        actions["暂停 1 小时"].trigger()
        actions["暂停到明早 8 点"].trigger()
        assert emitted == [30, 60, -1]

        until = datetime.now().astimezone() + timedelta(minutes=30)
        tray.set_pause_until(until)
        assert pause_menu.title().startswith("勿扰模式 · 至 ")
        assert "勿扰至" in tray.toolTip()
        assert actions["关闭勿扰"].isEnabled() is True

        tray.set_unread(3)
        assert "3 条未读" in tray.toolTip()
        assert "勿扰至" in tray.toolTip()

        emit_clear: list[int] = []
        tray.pause_requested.disconnect()
        tray.pause_requested.connect(emit_clear.append)
        actions["关闭勿扰"].trigger()
        assert emit_clear == [0]

        tray.set_pause_until(None)
        assert pause_menu.title() == "勿扰模式"
        assert "勿扰至" not in tray.toolTip()
        assert actions["关闭勿扰"].isEnabled() is False
    finally:
        tray.hide()
        tray.deleteLater()
