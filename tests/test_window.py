from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agentbell.config import AppConfig
from agentbell.models import Notification
from agentbell.store import NotificationStore
from agentbell.ui.window import (
    EmptyState,
    NotificationWindow,
    format_received_at,
)

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def window_factory(qapp):
    windows: list[NotificationWindow] = []

    def create(
        store: NotificationStore | None = None,
        token: str = "test-token",
    ) -> NotificationWindow:
        window = NotificationWindow(
            AppConfig(port=8765, token=token),
            store if store is not None else NotificationStore(),
            logging.getLogger("agentbell.tests"),
        )
        windows.append(window)
        return window

    yield create

    for window in windows:
        window.shutdown()
        window.deleteLater()
    QTest.qWait(30)


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


def test_window_lists_newest_first_and_updates_counts(window_factory):
    store = NotificationStore()
    store.add(make_notification(1))
    store.add(make_notification(2, status="failed", error="boom"))
    store.add(make_notification(3, status="canceled"))

    window = window_factory(store)
    window.refresh_items(store.snapshot())

    assert [card.notification.title for card in window._cards] == [
        "任务 3",
        "任务 2",
        "任务 1",
    ]
    assert window._segment_buttons["all"].text() == "全部 3"
    assert window._segment_buttons["succeeded"].text() == "成功 1"
    assert window._segment_buttons["failed"].text() == "失败 1"
    assert window._segment_buttons["canceled"].text() == "已取消 1"
    assert window._total_label.text() == "共 3 条"


def test_filter_syncs_sidebar_and_segments(window_factory):
    store = NotificationStore()
    store.add(make_notification(1))
    store.add(make_notification(2, status="failed"))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    window.set_filter("failed")

    assert [card.notification.status for card in window._cards] == ["failed"]
    assert window._nav_buttons["failed"].isChecked()
    assert window._segment_buttons["failed"].isChecked()
    assert not window._nav_buttons["all"].isChecked()

    window._segment_buttons["succeeded"].click()
    assert window._filter == "succeeded"
    assert window._nav_buttons["succeeded"].isChecked()
    assert [card.notification.title for card in window._cards] == ["任务 1"]


def test_copy_button_puts_agent_instructions_on_clipboard(window_factory):
    window = window_factory()
    QTest.qWait(20)

    window.copy_button.click()

    text = QGuiApplication.clipboard().text()
    assert "http://127.0.0.1:8765/notify" in text
    assert "X-Token: test-token" in text
    assert "每一轮" in text
    assert window.copy_button.text() == "已复制接入指令"
    assert window.copy_button.property("copied") is True

    window._reset_copy_button()
    assert window.copy_button.text() == "复制 Agent 接入指令"
    assert window.copy_button.property("copied") is False


def test_empty_state_copy_button_works(window_factory):
    window = window_factory()
    window.refresh_items([])

    empty = window._list_layout.itemAt(0).widget()
    assert isinstance(empty, EmptyState)
    assert empty.action.text() == "复制 Agent 接入指令"

    empty.action.click()
    assert "http://127.0.0.1:8765/notify" in QGuiApplication.clipboard().text()


def test_filtered_empty_state_can_return_to_all(window_factory):
    store = NotificationStore()
    store.add(make_notification(1))
    window = window_factory(store)
    window.refresh_items(store.snapshot())
    window.set_filter("failed")

    empty = window._list_layout.itemAt(0).widget()
    assert isinstance(empty, EmptyState)
    assert empty.action.text() == "查看全部通知"

    empty.action.click()
    assert window._filter == "all"
    assert len(window._cards) == 1


def test_replay_button_emits_notification(window_factory):
    store = NotificationStore()
    store.add(make_notification(1, title="重播我"))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    received: list[Notification] = []
    window.replay_requested.connect(received.append)
    window._cards[0].replay_button.click()

    assert [item.title for item in received] == ["重播我"]


def test_close_hides_to_tray_instead_of_quitting(window_factory, qapp):
    window = window_factory()
    window.show_center()
    QTest.qWait(30)
    assert window.isVisible()

    window.close()
    QTest.qWait(30)

    assert not window.isVisible()
    assert QApplication.instance() is qapp


def test_refresh_is_idempotent_and_ignores_unchanged_snapshot(window_factory):
    store = NotificationStore()
    store.add(make_notification(1))
    window = window_factory(store)

    window.refresh_items(store.snapshot())
    first_cards = list(window._cards)
    window.refresh_items(store.snapshot())

    assert list(window._cards) == first_cards


def test_time_formatting():
    now = datetime.now().astimezone().replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    today = now.replace(hour=9, minute=5)
    yesterday = (now - timedelta(days=1)).replace(hour=20, minute=30)
    older = now - timedelta(days=40)

    assert format_received_at(today, now) == "今天 09:05"
    assert format_received_at(yesterday, now) == "昨天 20:30"
    assert format_received_at(older, now) == f"{older:%m-%d %H:%M}"
