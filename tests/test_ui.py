from __future__ import annotations

import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from agentbell.models import Notification
from agentbell.ui.toast import MAX_VISIBLE, ToastManager, ToastWindow

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def make_notification(index: int, **overrides) -> Notification:
    values = {
        "id": f"id{index:04d}",
        "title": f"任务 {index}",
        "status": "succeeded",
        "summary": "已完成任务。",
        "duration": "1m",
    }
    values.update(overrides)
    return Notification(**values)


def test_toast_content_buttons_and_no_focus_flags(qapp):
    notification = make_notification(
        1,
        title="生成竞品分析报告",
        summary="已完成 12 页报告，包含 5 个竞品对比。",
        link="https://example.com/report",
        duration="8m30s",
    )
    toast = ToastWindow(notification, 30, logging.getLogger("agentbell.tests"))
    try:
        title = toast.findChild(QLabel, "title")
        assert title is not None
        assert title.text() == "上一轮【生成竞品分析报告】已完成，请查看"
        assert toast.view_button.text() == "查看"
        assert toast.view_button.isEnabled()
        assert toast.ack_button.text() == "知道了"
        assert toast.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert toast.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
        assert toast.windowFlags() & Qt.WindowType.Tool
        assert toast.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert toast.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    finally:
        toast.close_now()
        toast.deleteLater()
        QTest.qWait(20)


def test_view_button_disabled_without_usable_link(qapp):
    notification = make_notification(2, link="file:///C:/secret.txt")
    toast = ToastWindow(notification, 0, logging.getLogger("agentbell.tests"))
    try:
        assert not toast.view_button.isEnabled()
        assert toast.progress is None
    finally:
        toast.close_now()
        toast.deleteLater()
        QTest.qWait(20)


def test_manager_stacks_five_and_queues_the_rest(qapp):
    manager = ToastManager(30, logging.getLogger("agentbell.tests"))
    try:
        for index in range(7):
            manager.enqueue(make_notification(index))
        QTest.qWait(300)
        assert len(manager._active) == MAX_VISIBLE
        assert len(manager._pending) == 2
        positions = [toast.pos().y() for toast in manager._active]
        assert positions == sorted(positions)
        assert len(set(toast.pos().x() for toast in manager._active)) == 1
        assert all(toast.isVisible() for toast in manager._active)
    finally:
        manager.close_all()
        QTest.qWait(50)


def test_manager_duplicate_ids_are_ignored(qapp):
    manager = ToastManager(30, logging.getLogger("agentbell.tests"))
    try:
        notification = make_notification(10)
        assert manager.enqueue(notification) is True
        assert manager.enqueue(notification) is False
        QTest.qWait(100)
        assert len(manager._active) == 1
    finally:
        manager.close_all()
        QTest.qWait(50)


def test_ack_button_closes_and_promotes_queue(qapp):
    manager = ToastManager(30, logging.getLogger("agentbell.tests"))
    try:
        for index in range(MAX_VISIBLE + 1):
            manager.enqueue(make_notification(20 + index))
        QTest.qWait(250)
        assert len(manager._active) == MAX_VISIBLE
        assert len(manager._pending) == 1
        manager._active[0].ack_button.click()
        QTest.qWait(450)
        # One closed, so the queued item should now be visible.
        assert len(manager._active) == MAX_VISIBLE
        assert len(manager._pending) == 0
    finally:
        manager.close_all()
        QTest.qWait(50)


def test_auto_close_and_hover_pause(qapp):
    manager = ToastManager(1, logging.getLogger("agentbell.tests"))
    try:
        manager.enqueue(make_notification(30))
        QTest.qWait(200)
        assert len(manager._active) == 1
        toast = manager._active[0]
        toast._cursor_over_card = lambda: True
        QTest.qWait(1500)
        assert len(manager._active) == 1
        toast._cursor_over_card = lambda: False
        QTest.qWait(1500)
        assert len(manager._active) == 0
    finally:
        manager.close_all()
        QTest.qWait(50)


def test_failed_and_canceled_headlines(qapp):
    failed = ToastWindow(
        make_notification(40, status="failed", error="HTTP 403"),
        0,
        logging.getLogger("agentbell.tests"),
    )
    canceled = ToastWindow(
        make_notification(41, status="canceled"),
        0,
        logging.getLogger("agentbell.tests"),
    )
    try:
        assert failed.findChild(QLabel, "title").text() == "上一轮【任务 40】执行失败"
        assert canceled.findChild(QLabel, "title").text() == "上一轮【任务 41】已取消"
    finally:
        failed.close_now()
        canceled.close_now()
        failed.deleteLater()
        canceled.deleteLater()
        QTest.qWait(20)
