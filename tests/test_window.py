from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from agentbell.agent_sessions import AgentSession
from agentbell.agent_launch import AgentAvailability, AgentSpec, LaunchResult
from agentbell.config import AgentLauncherConfig, AgentSessionsConfig, AppConfig, load_config
from agentbell.models import Notification, NotificationAction
from agentbell.store import NotificationStore
from agentbell.ui.window import (
    AgentPickCard,
    AgentSessionCard,
    EmptyState,
    LaunchRecordCard,
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
        config: AppConfig | None = None,
        config_path=None,
    ) -> NotificationWindow:
        window = NotificationWindow(
            config if config is not None else AppConfig(port=8765, token=token),
            store if store is not None else NotificationStore(),
            logging.getLogger("agentbell.tests"),
            config_path=config_path,
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


def test_startup_animation_ends_at_full_opacity(window_factory):
    window = window_factory()
    window.show_center(animate=True)
    assert window.isVisible()
    QTest.qWait(400)
    assert window.windowOpacity() == pytest.approx(1.0)
    window.hide_center()
    assert window.windowOpacity() == pytest.approx(1.0)


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


def test_card_focus_action_renders_first_and_emits(window_factory):
    store = NotificationStore()
    focus_value = '{"pid":1234,"window_title":"Qoder","working_dir":"E:\\\\proj"}'
    store.add(
        make_notification(
            1,
            status="succeeded",
            actions=(
                NotificationAction(kind="focus", label="回到终端", value=focus_value),
                NotificationAction(kind="copy", label="复制命令", value="curl http://x"),
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
    assert [button.text() for button in card.action_buttons] == ["回到终端", "复制命令"]
    card.action_buttons[0].click()
    assert received == [("id0001", "focus", focus_value)]


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


def write_view_transcript(tmp_path):
    import json

    path = tmp_path / "session-view.jsonl"
    entries = [
        {
            "type": "summary",
            "cwd": "E:\\opt\\demo",
            "timestamp": "2026-10-30T08:00:00Z",
        },
        {
            "type": "user",
            "cwd": "E:\\opt\\demo",
            "timestamp": "2026-10-30T08:00:00Z",
            "message": {
                "content": [{"type": "text", "text": "帮我重构设置页的布局"}]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:00:05Z",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "先看看现有布局"},
                    {"type": "text", "text": "我先读取设置页代码。"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "agentbell/ui/settings.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:00:07Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "1 from __future__ ...",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:00:12Z",
            "message": {
                "content": [{"type": "text", "text": "布局已调整完成。"}]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:02:00Z",
            "message": {
                "content": [{"type": "text", "text": "再补一组单元测试"}]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:02:05Z",
            "message": {
                "content": [
                    {"type": "text", "text": "已补充设置页布局测试。"},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "Write",
                        "input": {"file_path": "tests/test_settings.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:02:09Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "is_error": True,
                        "content": "permission denied",
                    }
                ]
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries)
        + "\n",
        encoding="utf-8",
    )
    now = datetime.now().astimezone()
    return AgentSession(
        agent="claude",
        session_id="session-view",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(path),
        updated_at=now,
        created_at=now - timedelta(hours=1),
        message_count=len(entries),
        size_bytes=path.stat().st_size,
        title="帮我重构设置页的布局",
    )


def test_session_view_renders_searches_and_exports(window_factory, tmp_path, monkeypatch):
    import agentbell.ui.window as window_module

    window = window_factory()
    session = write_view_transcript(tmp_path)
    window.update_sessions([session])
    window.set_page("sessions")
    QTest.qWait(30)

    cards = window._session_host.findChildren(AgentSessionCard)
    assert len(cards) == 1
    title = cards[0].findChildren(QLabel, "sessionTitle")[0]
    assert title.toolTip() == "帮我重构设置页的布局"

    window._session_search.setText("重构设置页")
    QTest.qWait(20)
    assert len(window._session_host.findChildren(AgentSessionCard)) == 1
    window._session_search.clear()
    QTest.qWait(20)

    cards = window._session_host.findChildren(AgentSessionCard)
    cards[0].view_button.click()
    QTest.qWait(40)

    assert window._session_view_stack.currentIndex() == 1
    assert len(window._turn_views) == 2
    first, second = window._turn_views
    assert first._body is None
    assert second._body is not None
    assert first._expanded is False
    assert second._expanded is True

    first.header.clicked.emit()
    QTest.qWait(20)
    assert first._body is not None
    assert first._expanded is True

    window._transcript_search.setText("permission")
    QTest.qWait(20)
    assert first.isHidden() is True
    assert second.isHidden() is False
    assert "匹配 1 / 2" in window._transcript_hint.text()
    assert second._activity_toggle is not None
    assert second._activity_toggle.isChecked() is True

    window._transcript_search.clear()
    QTest.qWait(20)
    assert first.isHidden() is False
    assert second.isHidden() is False
    assert second._expanded is True
    assert "2 轮" in window._transcript_hint.text()

    outline = [action.text() for action in window._outline_menu.actions()]
    assert outline == [
        "1. 帮我重构设置页的布局",
        "2. 再补一组单元测试",
    ]

    window._detail_copy_button.click()
    clipboard = QGuiApplication.clipboard().text()
    assert clipboard.startswith("# 帮我重构设置页的布局")
    assert "## 1. 帮我重构设置页的布局" in clipboard
    assert "**工具 · Read**" in clipboard
    assert "已复制 Markdown" in window._transcript_hint.text()

    class FakeFileDialog:
        @staticmethod
        def getSaveFileName(*args, **kwargs):
            return str(tmp_path / "export.md"), "Markdown (*.md)"

    monkeypatch.setattr(window_module, "QFileDialog", FakeFileDialog)
    window._detail_export_button.click()
    exported = tmp_path / "export.md"
    assert exported.is_file()
    assert "## 2. 再补一组单元测试" in exported.read_text(encoding="utf-8")
    assert "已导出" in window._transcript_hint.text()

    window._close_session_view()
    assert window._session_view_stack.currentIndex() == 0


def test_session_view_handles_missing_transcript(window_factory, tmp_path):
    window = window_factory()
    now = datetime.now().astimezone()
    session = AgentSession(
        agent="qoder",
        session_id="missing",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(tmp_path / "missing-session"),
        updated_at=now,
        title="缺失记录",
    )
    window.update_sessions([session])
    window.set_page("sessions")
    QTest.qWait(20)

    window._open_session_view(session)
    QTest.qWait(20)

    assert window._session_view_stack.currentIndex() == 1
    assert window._turn_views == []
    assert window._detail_copy_button.isEnabled() is False
    assert window._detail_export_button.isEnabled() is False
    texts = [
        label.text()
        for label in window._transcript_host.findChildren(QLabel, "sessionEmptyText")
    ]
    assert any("未找到" in text for text in texts)

    window._close_session_view()
    assert window._session_view_stack.currentIndex() == 0


def _availability(
    agent_id: str,
    name: str,
    *,
    kind: str = "cli",
    executable: str = r"C:\bin\agent.exe",
) -> AgentAvailability:
    return AgentAvailability(
        spec=AgentSpec(
            id=agent_id,
            name=name,
            kind=kind,
            summary=f"{name} 的说明",
        ),
        executable=executable,
    )


def test_launcher_page_lists_and_selects_installed_agents(
    qapp, window_factory, monkeypatch
):
    import agentbell.ui.window as window_module

    agents = [
        _availability("alpha", "Alpha", executable=r"C:\bin\alpha.exe"),
        _availability("beta", "Beta", kind="desktop", executable=""),
    ]
    monkeypatch.setattr(window_module, "discover_agents", lambda: agents)

    window = window_factory()

    assert len(window._agent_cards) == 2
    assert window._selected_agent_id == "alpha"
    assert window._launcher_start.isEnabled() is True
    assert "Alpha" in window._launcher_status.text()

    beta_card = next(
        card
        for card in window._agent_cards
        if card.availability.spec.id == "beta"
    )
    beta_card.picked.emit(beta_card.availability)

    assert window._selected_agent_id == "beta"
    assert window._launcher_start.isEnabled() is False
    assert "未安装" in window._launcher_status.text()

    window.set_page("launcher")
    assert window._stack.currentIndex() == 3
    assert window._launcher_button.isChecked() is True


def test_launcher_launches_agent_and_remembers_project(
    qapp, window_factory, monkeypatch, tmp_path
):
    import agentbell.ui.window as window_module

    agents = [
        _availability("alpha", "Alpha", executable=r"C:\bin\alpha.exe")
    ]
    monkeypatch.setattr(window_module, "discover_agents", lambda: agents)
    calls: list[tuple[str, str, str]] = []

    def fake_launch(availability, project, prompt=""):
        calls.append((availability.spec.id, project, prompt))
        return LaunchResult(
            ok=True,
            message="已在终端启动 Alpha",
            agent_id="alpha",
            agent_name="Alpha",
            agent_kind="cli",
            pid=4321,
            title="Alpha - demo",
            working_dir=project,
            executable=availability.executable,
            prompt_sent=bool(prompt),
        )

    monkeypatch.setattr(window_module, "launch_agent", fake_launch)
    config_path = tmp_path / "config.json"
    window = window_factory(config_path=config_path)
    window._launcher_project.setText(str(tmp_path))
    window._launcher_prompt.setPlainText("先读项目结构")

    window._launch_selected_agent()

    assert calls == [("alpha", str(tmp_path), "先读项目结构")]
    assert window._launcher_status.text() == "已在终端启动 Alpha"
    assert window.config.agent_launcher.recent_projects == (str(tmp_path),)
    assert window.config.agent_launcher.last_agent == "alpha"
    loaded, _ = load_config(config_path)
    assert loaded.agent_launcher.recent_projects == (str(tmp_path),)
    assert loaded.agent_launcher.last_agent == "alpha"

    assert len(window._launch_records) == 1
    record = window._launch_records_layout.itemAt(0).widget()
    assert isinstance(record, LaunchRecordCard)
    assert record.focus_button.isEnabled() is True

    focused = []
    window.focus_requested.connect(focused.append)
    record.focus_button.click()
    assert len(focused) == 1
    assert focused[0].pid == 4321
    assert focused[0].window_title == "Alpha - demo"
    assert focused[0].working_dir == str(tmp_path)


def test_launcher_rejects_missing_project(
    qapp, window_factory, monkeypatch, tmp_path
):
    import agentbell.ui.window as window_module

    monkeypatch.setattr(
        window_module,
        "discover_agents",
        lambda: [_availability("alpha", "Alpha")],
    )
    calls = []
    monkeypatch.setattr(
        window_module,
        "launch_agent",
        lambda *args, **kwargs: calls.append(args) or LaunchResult(True, "ok"),
    )

    window = window_factory()
    window._launcher_project.setText(str(tmp_path / "missing"))
    window._launch_selected_agent()

    assert calls == []
    assert "项目目录不存在" in window._launcher_status.text()
    assert window._launcher_status.property("state") == "error"


def test_launcher_double_click_starts_agent(
    qapp, window_factory, monkeypatch, tmp_path
):
    import agentbell.ui.window as window_module

    agents = [
        _availability("alpha", "Alpha", executable=r"C:\bin\alpha.exe"),
        _availability("beta", "Beta", executable=r"C:\bin\beta.exe"),
    ]
    monkeypatch.setattr(window_module, "discover_agents", lambda: agents)
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        window_module,
        "launch_agent",
        lambda availability, project, prompt="": calls.append(
            (availability.spec.id, project, prompt)
        )
        or LaunchResult(
            ok=True,
            message=f"已启动 {availability.spec.name}",
            working_dir=project,
        ),
    )

    window = window_factory()
    window._launcher_project.setText(str(tmp_path))
    beta_card = next(
        card
        for card in window._agent_cards
        if card.availability.spec.id == "beta"
    )
    target = beta_card.findChild(QLabel)

    QTest.mouseDClick(
        target,
        Qt.MouseButton.LeftButton,
        pos=target.rect().center(),
    )
    QTest.qWait(20)

    assert calls == [("beta", str(tmp_path), "")]
    assert window._selected_agent_id == "beta"
    assert window._launcher_status.text() == "已启动 Beta"


def test_launcher_double_click_ignores_missing_project(
    qapp, window_factory, monkeypatch, tmp_path
):
    import agentbell.ui.window as window_module

    monkeypatch.setattr(
        window_module,
        "discover_agents",
        lambda: [_availability("alpha", "Alpha")],
    )
    calls = []
    monkeypatch.setattr(
        window_module,
        "launch_agent",
        lambda *args, **kwargs: calls.append(args) or LaunchResult(True, "ok"),
    )

    window = window_factory()
    window._launcher_project.setText(str(tmp_path / "missing"))
    card = window._agent_cards[0]

    QTest.mouseDClick(card, Qt.MouseButton.LeftButton, pos=card.rect().center())
    QTest.qWait(20)

    assert calls == []
    assert "项目目录不存在" in window._launcher_status.text()


def test_session_terminal_button_and_focus_request(window_factory):
    window = window_factory()
    session = make_session(2, "TaskBeacon")

    card = AgentSessionCard(session)
    received = []
    card.terminal_requested.connect(received.append)
    card.terminal_button.click()
    assert received == [session]

    focused = []
    window.focus_requested.connect(focused.append)
    window._focus_session(session)
    assert len(focused) == 1
    assert focused[0].pid is None
    assert focused[0].window_title == "TaskBeacon"
    assert focused[0].working_dir == r"E:\opt\TaskBeacon"

    window._session_detail_session = session
    window._focus_detail_session()
    assert len(focused) == 2


def test_launcher_prefills_chat_workspace_and_opens_project_page(
    qapp, window_factory, monkeypatch, tmp_path
):
    import agentbell.ui.window as window_module

    chat = tmp_path / "chat"
    chat.mkdir()
    monkeypatch.setattr(window_module, "default_project_dir", lambda: chat)
    agents = [
        AgentAvailability(
            spec=AgentSpec(
                id="alpha",
                name="Alpha",
                kind="cli",
                summary="Alpha 的说明",
                project_url="https://github.com/acme/alpha",
            ),
            executable=r"C:\bin\alpha.exe",
        )
    ]
    monkeypatch.setattr(window_module, "discover_agents", lambda: agents)

    window = window_factory()

    assert window._launcher_project.text() == str(chat)
    assert window._agent_link.isEnabled() is True
    assert window._agent_link.toolTip() == "https://github.com/acme/alpha"

    opened = []

    class FakeDesktop:
        @staticmethod
        def openUrl(url):
            opened.append(url.toString())
            return True

    monkeypatch.setattr(window_module, "QDesktopServices", FakeDesktop)
    window._agent_link.click()

    assert opened == ["https://github.com/acme/alpha"]


def test_launcher_update_button_emits_request(qapp, window_factory, monkeypatch):
    import agentbell.ui.window as window_module

    monkeypatch.setattr(
        window_module,
        "discover_agents",
        lambda: [_availability("alpha", "Alpha")],
    )
    window = window_factory()
    requested = []
    window.update_check_requested.connect(lambda: requested.append(True))

    window._update_button.click()

    assert requested == [True]


def test_agent_link_disabled_without_project_url(
    qapp, window_factory, monkeypatch
):
    import agentbell.ui.window as window_module

    monkeypatch.setattr(
        window_module,
        "discover_agents",
        lambda: [_availability("alpha", "Alpha")],
    )
    window = window_factory()

    assert window._agent_link.isEnabled() is False
