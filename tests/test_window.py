from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from agentbell.agent_sessions import AgentSession
from agentbell.config import AgentSessionsConfig, AppConfig
from agentbell.models import Notification, NotificationAction
from agentbell.store import NotificationStore
from agentbell.ui.window import (
    AgentSessionCard,
    EmptyState,
    NotificationWindow,
    format_received_at,
    format_seconds,
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


def test_format_seconds():
    assert format_seconds(None) == "—"
    assert format_seconds(0.4) == "<1 秒"
    assert format_seconds(45) == "45 秒"
    assert format_seconds(90) == "1.5 分钟"
    assert format_seconds(7200) == "2.0 小时"


def test_running_filter_and_progress(window_factory):
    store = NotificationStore()
    store.add(make_notification(1))
    store.add(make_notification(2, status="running", progress=60))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    assert window._segment_buttons["running"].text() == "进行中 1"
    assert window._nav_buttons["running"].toolTip() == "共 1 条通知"

    window.set_filter("running")
    assert [card.notification.status for card in window._cards] == ["running"]
    card = window._cards[0]
    assert card.progress_bar is not None
    assert card.progress_bar.value() == 60


def test_search_filters_cards_and_can_reset(window_factory):
    store = NotificationStore()
    store.add(make_notification(1, title="生成竞品分析报告"))
    store.add(make_notification(2, title="整理素材"))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    window._search_input.setText("竞品")
    window._perform_search()
    assert [card.notification.title for card in window._cards] == [
        "生成竞品分析报告"
    ]
    assert window._total_label.text() == "搜索到 1 条"

    window._search_input.setText("完全不存在")
    window._perform_search()
    empty = window._list_layout.itemAt(0).widget()
    assert isinstance(empty, EmptyState)
    assert empty.action.text() == "清除搜索"

    empty.action.click()
    assert window._search_input.text() == ""
    assert window._query == ""
    assert len(window._cards) == 2
    assert window._total_label.text() == "共 2 条"


def test_card_ack_and_snooze_signals(window_factory):
    store = NotificationStore()
    store.add(make_notification(1, status="failed", require_ack=True))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    acks: list[str] = []
    snoozes: list[tuple[str, int]] = []
    window.ack_requested.connect(acks.append)
    window.snooze_requested.connect(
        lambda notification_id, minutes: snoozes.append((notification_id, minutes))
    )

    card = window._cards[0]
    assert card.ack_button is not None
    assert card.snooze_button is not None
    card.ack_button.click()
    assert acks == ["id0001"]

    menu = card.snooze_button.menu()
    assert menu is not None
    menu.actions()[1].trigger()
    assert snoozes == [("id0001", 15)]


def test_card_action_button_emits_request(window_factory):
    store = NotificationStore()
    store.add(
        make_notification(
            1,
            status="failed",
            actions=(
                NotificationAction(
                    kind="copy", label="复制命令", value="curl http://x"
                ),
            ),
        )
    )
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    received: list[tuple[str, str, str]] = []
    window.action_requested.connect(
        lambda notification, action: received.append(
            (notification.id, action.kind, action.value)
        )
    )
    card = window._cards[0]
    assert [button.text() for button in card.action_buttons] == ["复制命令"]
    card.action_buttons[0].click()
    assert received == [("id0001", "copy", "curl http://x")]


def test_card_shows_priority_repeat_source_and_ack_chips(window_factory):
    store = NotificationStore()
    store.add(
        make_notification(
            1,
            status="failed",
            priority="critical",
            source="deploy-bot",
            occurrence_count=3,
            require_ack=True,
        )
    )
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    texts = [label.text() for label in window._cards[0].findChildren(QLabel)]
    assert "紧急" in texts
    assert "来源 deploy-bot" in texts
    assert "更新 ×3" in texts
    assert "待确认" in texts


def test_stats_page_reflects_store_totals(window_factory):
    store = NotificationStore()
    store.add(make_notification(1, duration="2m"))
    store.add(make_notification(2, status="failed", duration="1m"))
    store.add(make_notification(3, status="running"))
    window = window_factory(store)
    window.refresh_items(store.snapshot())

    window.set_page("stats")
    assert window._stats_button.isChecked()
    assert window._stat_values["total"].text() == "3"
    assert window._stat_values["success"].text() == "50%"
    assert window._stat_values["avg"].text() == "1.5 分钟"
    assert window._stat_values["awaiting"].text() == "0"
    assert window._stats_status_labels["failed"].text() == "失败 1"
    assert window._stats_status_labels["running"].text() == "进行中 1"

    window.set_filter("failed")
    assert window._page == "list"
    assert not window._stats_button.isChecked()


def make_session(
    index: int,
    project: str = "TaskBeacon",
    *,
    agent: str = "claude",
    message_count: int = 5,
) -> AgentSession:
    now = datetime.now().astimezone()
    return AgentSession(
        agent=agent,
        session_id=f"session-{index:04d}",
        project=project,
        project_path=f"E:\\opt\\{project}",
        path=f"E:\\opt\\{project}\\session-{index:04d}.jsonl",
        updated_at=now - timedelta(minutes=index),
        created_at=now - timedelta(hours=1),
        message_count=message_count,
        size_bytes=2048 * (index + 1),
    )


def test_sessions_page_groups_filters_and_requests_refresh(window_factory):
    window = window_factory()
    window.update_sessions(
        [
            make_session(0, "TaskBeacon"),
            make_session(1, "TaskBeacon", agent="qoder", message_count=0),
            make_session(2, "EmoChat"),
        ]
    )
    requests: list[bool] = []
    window.session_refresh_requested.connect(lambda: requests.append(True))

    window.set_page("sessions")
    QTest.qWait(30)

    assert window._page == "sessions"
    assert window._sessions_button.isChecked()
    assert requests == [True]
    assert "共 3 个会话" in window._session_summary.text()
    titles = [
        label.text()
        for label in window._session_host.findChildren(QLabel, "sessionGroupTitle")
    ]
    assert titles == ["TaskBeacon", "EmoChat"]
    cards = window._session_host.findChildren(AgentSessionCard)
    assert len(cards) == 3
    assert {card.session.project for card in cards} == {"TaskBeacon", "EmoChat"}

    window._session_search.setText("EmoChat")
    QTest.qWait(30)
    cards = window._session_host.findChildren(AgentSessionCard)
    assert [card.session.project for card in cards] == ["EmoChat"]

    window._session_search.clear()
    QTest.qWait(30)
    window._copy_session_path(window._sessions[0])
    assert "E:\\opt" in QGuiApplication.clipboard().text()


def test_sessions_page_empty_states(window_factory):
    window = window_factory()
    window.set_page("sessions")
    QTest.qWait(20)
    assert window._session_summary.text() == "尚未扫描"
    texts = [
        label.text()
        for label in window._session_host.findChildren(QLabel, "sessionEmptyTitle")
    ]
    assert texts == ["还没有扫描到会话"]

    window.apply_config(
        AppConfig(port=8765, agent_sessions=AgentSessionsConfig(enabled=False))
    )
    window.set_page("list")
    window.set_page("sessions")
    QTest.qWait(20)
    assert "关闭" in window._session_summary.text()
    titles = [
        label.text()
        for label in window._session_host.findChildren(QLabel, "sessionEmptyTitle")
    ]
    assert titles == ["会话扫描已关闭"]


def test_apply_config_updates_service_labels(window_factory):
    window = window_factory()
    new_config = AppConfig(port=18765, token="")
    window.apply_config(new_config)

    assert window._endpoint_label.text() == "127.0.0.1:18765"
    assert window._auth_label.text() == "X-Token 未开启"
    assert window._status_address.text() == "127.0.0.1:18765 · 运行中"
    assert window._hotkey_label.text() == "快捷键 Ctrl+Alt+A"
