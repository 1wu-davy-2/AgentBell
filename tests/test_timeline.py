from __future__ import annotations

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from agentbell.models import Notification, RunEvent
from agentbell.ui.timeline import (
    RunTimelineDialog,
    SessionRound,
    SessionTimelineDialog,
)

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def make_notification(**overrides) -> Notification:
    values = {
        "id": "n1",
        "title": "生成报告",
        "status": "succeeded",
        "run_id": "single:n1",
    }
    values.update(overrides)
    return Notification(**values)


def test_single_event_hides_relative_time_and_shows_hint(qapp):
    base = datetime.now().astimezone()
    notification = make_notification(duration="8m30s", source="Qoder")
    event = RunEvent(
        run_id="single:n1",
        kind="finished",
        occurred_at=base,
        status="succeeded",
        title="生成报告",
        detail="已完成",
    )

    dialog = RunTimelineDialog(notification, [event])
    try:
        relative = dialog.findChildren(QLabel, "timelineRelative")
        assert len(relative) == 1
        assert relative[0].text() == ""
        assert relative[0].isHidden()

        hint = dialog.findChild(QLabel, "timelineHint")
        assert hint is not None
        assert "1 个事件" in hint.text()

        chips = [
            label.text()
            for label in dialog.findChildren(QLabel, "timelineMetaChip")
        ]
        assert "耗时 8 分 30 秒" in chips
        assert not any(text.startswith("跨度") for text in chips)
    finally:
        dialog.deleteLater()


def test_multiple_events_show_relative_time_and_span(qapp):
    base = datetime.now().astimezone()
    notification = make_notification(status="running", source="Qoder")
    events = [
        RunEvent(
            run_id="single:n1",
            kind="started",
            occurred_at=base,
            status="running",
            title="生成报告",
        ),
        RunEvent(
            run_id="single:n1",
            kind="finished",
            occurred_at=base + timedelta(seconds=90),
            status="succeeded",
            title="生成报告",
        ),
    ]

    dialog = RunTimelineDialog(notification, events)
    try:
        relative = dialog.findChildren(QLabel, "timelineRelative")
        assert [label.text() for label in relative] == ["+0s", "+1m30s"]
        assert all(not label.isHidden() for label in relative)

        assert dialog.findChild(QLabel, "timelineHint") is None
        chips = [
            label.text()
            for label in dialog.findChildren(QLabel, "timelineMetaChip")
        ]
        assert "跨度 1 分 30 秒" in chips
        assert not any(text.startswith("耗时") for text in chips)
    finally:
        dialog.deleteLater()


def make_round(index: int, when: datetime, status: str, **overrides) -> SessionRound:
    notification = Notification(
        id=f"r{index}",
        title=f"第 {index} 轮任务",
        status=status,
        summary=f"第 {index} 轮结论",
        duration="1m30s",
        session_id="s-1",
        run_id=f"run-{index}",
        received_at=when,
        **overrides,
    )
    events = [
        RunEvent(
            run_id=f"run-{index}",
            kind="started",
            occurred_at=when,
            status="running",
            title=notification.title,
            detail="开始执行",
        ),
        RunEvent(
            run_id=f"run-{index}",
            kind="finished",
            occurred_at=when + timedelta(seconds=45),
            status=status,
            title=notification.title,
            detail="执行结束",
        ),
    ]
    return SessionRound(notification=notification, events=events)


def test_session_dialog_renders_rounds_and_expands_latest(qapp):
    base = datetime.now().astimezone() - timedelta(hours=2)
    rounds = [
        make_round(1, base, "succeeded"),
        make_round(
            2,
            base + timedelta(minutes=20),
            "failed",
            metadata={"session_link": "auto"},
        ),
        make_round(3, base + timedelta(minutes=40), "succeeded"),
    ]
    dialog = SessionTimelineDialog(
        "AgentBell 开发",
        rounds,
        session_id="s-1",
        agent="Qoder",
        project="TaskBeacon",
    )
    try:
        assert len(dialog.rounds) == 3
        assert len(dialog.round_cards) == 3
        assert len(dialog.event_rows) == 6
        assert dialog.empty_label is None

        chips = [
            label.text()
            for label in dialog.findChildren(QLabel, "timelineMetaChip")
        ]
        assert "Qoder" in chips
        assert "项目 TaskBeacon" in chips
        assert "3 轮" in chips
        assert "成功率 67%" in chips
        assert "自动关联 1" in chips
        assert any(text.startswith("跨度 40 分") for text in chips)

        auto_chips = [
            label.text()
            for label in dialog.findChildren(QLabel, "sessionAutoChip")
        ]
        assert auto_chips == ["自动关联"]

        assert dialog.round_event_hosts[-1].isHidden() is False
        assert dialog.round_event_hosts[0].isHidden() is True
        assert dialog.round_toggle_buttons[-1].text() == "收起事件"
        assert dialog.round_toggle_buttons[0].text() == "展开事件 2"

        dialog.round_toggle_buttons[0].click()
        assert dialog.round_event_hosts[0].isHidden() is False
        assert dialog.round_toggle_buttons[0].text() == "收起事件"
        dialog.round_toggle_buttons[0].click()
        assert dialog.round_event_hosts[0].isHidden() is True
        assert dialog.round_toggle_buttons[0].text() == "展开事件 2"
    finally:
        dialog.deleteLater()


def test_session_dialog_empty_state(qapp):
    dialog = SessionTimelineDialog("空会话", [])
    try:
        assert dialog.empty_label is not None
        assert "还没有关联的通知" in dialog.empty_label.text()
        assert dialog.round_cards == []
        chips = [
            label.text()
            for label in dialog.findChildren(QLabel, "timelineMetaChip")
        ]
        assert "0 轮" in chips
    finally:
        dialog.deleteLater()
