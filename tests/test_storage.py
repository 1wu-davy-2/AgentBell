from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta

from agentbell.models import Notification, NotificationAction, RunEvent
from agentbell.storage import NotificationStorage
from agentbell.store import NotificationStore

_LEGACY_SCHEMA = """
CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    duration TEXT NOT NULL DEFAULT '',
    duration_seconds REAL,
    link TEXT,
    error TEXT,
    received_at TEXT NOT NULL,
    updated_at TEXT,
    priority TEXT NOT NULL DEFAULT 'normal',
    source TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT,
    require_ack INTEGER NOT NULL DEFAULT 0,
    silent INTEGER NOT NULL DEFAULT 0,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    acknowledged_at TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    progress INTEGER,
    actions TEXT NOT NULL DEFAULT '[]',
    bypass_quiet_hours INTEGER NOT NULL DEFAULT 0,
    auto_close_seconds INTEGER,
    expires_at TEXT,
    rule_name TEXT NOT NULL DEFAULT '',
    channel_types TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX idx_notifications_received ON notifications(received_at DESC);
CREATE INDEX idx_notifications_dedupe ON notifications(dedupe_key);
CREATE INDEX idx_notifications_status ON notifications(status);
"""


def make_notification(index: int, **overrides) -> Notification:
    values = {
        "id": f"id{index:04d}",
        "title": f"任务 {index}",
        "status": "succeeded",
        "summary": "已完成",
        "duration": "1m",
    }
    values.update(overrides)
    return Notification(**values)


def open_storage(tmp_path) -> NotificationStorage:
    return NotificationStorage(
        tmp_path / "history.db", logging.getLogger("agentbell.tests")
    )


def make_event(run_id: str, kind: str, occurred_at: datetime, **overrides) -> RunEvent:
    values = {"run_id": run_id, "kind": kind, "occurred_at": occurred_at}
    values.update(overrides)
    return RunEvent(**values)


def test_round_trip_preserves_all_fields(tmp_path):
    storage = open_storage(tmp_path)
    try:
        received = datetime.now().astimezone()
        notification = make_notification(
            1,
            status="failed",
            error="HTTP 403",
            link="https://example.com/logs",
            priority="critical",
            source="deploy-bot",
            dedupe_key="deploy-1",
            require_ack=True,
            silent=True,
            acknowledged=True,
            acknowledged_at=received,
            occurrence_count=3,
            progress=80,
            actions=(
                NotificationAction(kind="open", label="日志", value="https://x.test/a"),
                NotificationAction(kind="retry", label="重试", value="http://127.0.0.1:9/r"),
                NotificationAction(
                    kind="focus",
                    label="回到终端",
                    value='{"pid":4321,"working_dir":"E:\\\\work"}',
                ),
            ),
            bypass_quiet_hours=True,
            auto_close_seconds=0,
            expires_at=received + timedelta(minutes=5),
            rule_name="部署规则",
            channel_types=("webhook", "ntfy"),
            received_at=received,
        )
        storage.save(notification)
        loaded = storage.load_recent(10)
        assert [item.id for item in loaded] == ["id0001"]
        item = loaded[0]
        assert item.title == "任务 1"
        assert item.status == "failed"
        assert item.error == "HTTP 403"
        assert item.priority == "critical"
        assert item.source == "deploy-bot"
        assert item.dedupe_key == "deploy-1"
        assert item.require_ack is True
        assert item.silent is True
        assert item.acknowledged is True
        assert item.occurrence_count == 3
        assert item.progress == 80
        assert [action.kind for action in item.actions] == ["open", "retry", "focus"]
        assert item.bypass_quiet_hours is True
        assert item.auto_close_seconds == 0
        assert item.expires_at is not None
        assert item.rule_name == "部署规则"
        assert item.channel_types == ("webhook", "ntfy")
        assert abs(item.received_at.timestamp() - received.timestamp()) < 0.001
    finally:
        storage.close()


def test_round_trip_preserves_read_only_actions(tmp_path):
    storage = open_storage(tmp_path)
    try:
        storage.save(
            make_notification(
                2,
                session_id="s-1",
                run_id="r-1",
                actions=(
                    NotificationAction(kind="session", label="查看记录"),
                    NotificationAction(kind="timeline", label="时间线"),
                ),
            )
        )
        loaded = storage.load_recent(10)
        assert [action.kind for action in loaded[0].actions] == [
            "session",
            "timeline",
        ]
        assert [action.label for action in loaded[0].actions] == [
            "查看记录",
            "时间线",
        ]
        assert all(action.value == "" for action in loaded[0].actions)
    finally:
        storage.close()


def test_round_trip_preserves_waiting_input_fields(tmp_path):
    storage = open_storage(tmp_path)
    try:
        storage.save(
            make_notification(
                5,
                status="running",
                needs_input=True,
                wait_reason="permission",
                wait_source="inferred",
                session_id="session-1",
                run_id="run-9",
            )
        )
        item = storage.load_recent(10)[0]
        assert item.needs_input is True
        assert item.wait_reason == "permission"
        assert item.wait_source == "inferred"
        assert item.session_id == "session-1"
        assert item.run_id == "run-9"
        assert item.is_waiting_input is True
    finally:
        storage.close()


def test_stats_count_waiting_input(tmp_path):
    storage = open_storage(tmp_path)
    try:
        storage.save(
            make_notification(
                1, status="running", needs_input=True, wait_reason="question"
            )
        )
        storage.save(make_notification(2, status="running"))
        storage.save(
            make_notification(
                3, status="succeeded", needs_input=True, wait_reason="question"
            )
        )
        stats = storage.stats(days=7)
        assert stats["running"] == 2
        assert stats["needs_input"] == 1
    finally:
        storage.close()


def test_migrates_legacy_database_without_wait_columns(tmp_path):
    path = tmp_path / "history.db"
    connection = sqlite3.connect(str(path))
    try:
        connection.executescript(_LEGACY_SCHEMA)
        connection.execute(
            "INSERT INTO notifications (id, title, status, received_at) "
            "VALUES ('legacy01', '旧记录', 'succeeded', '2026-01-01T10:00:00+08:00')"
        )
        connection.commit()
    finally:
        connection.close()

    storage = NotificationStorage(path, logging.getLogger("agentbell.tests"))
    try:
        legacy = storage.load_recent(5)
        assert [item.id for item in legacy] == ["legacy01"]
        assert legacy[0].needs_input is False
        assert legacy[0].wait_reason is None
        assert legacy[0].session_id is None

        storage.save(
            make_notification(
                2,
                status="running",
                needs_input=True,
                wait_reason="question",
                session_id="s-1",
            )
        )
        loaded = {item.id: item for item in storage.load_recent(5)}
        assert loaded["id0002"].needs_input is True
        assert loaded["id0002"].session_id == "s-1"
    finally:
        storage.close()

    with sqlite3.connect(str(path)) as check:
        columns = {
            row[1]
            for row in check.execute("PRAGMA table_info(notifications)").fetchall()
        }
        indexes = {
            row[1]
            for row in check.execute("PRAGMA index_list(notifications)").fetchall()
        }
        tables = {
            row[0]
            for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "needs_input",
        "wait_reason",
        "wait_source",
        "session_id",
        "run_id",
    } <= columns
    assert {"idx_notifications_needs_input", "idx_notifications_run"} <= indexes
    assert "run_events" in tables


def test_upsert_replaces_existing_row(tmp_path):
    storage = open_storage(tmp_path)
    try:
        storage.save(make_notification(1, status="running", progress=10))
        storage.save(
            make_notification(1, status="succeeded", progress=100, summary="完成")
        )
        items = storage.load_recent(10)
        assert len(items) == 1
        assert items[0].status == "succeeded"
        assert items[0].progress == 100
    finally:
        storage.close()


def test_search_and_stats(tmp_path):
    storage = open_storage(tmp_path)
    try:
        now = datetime.now().astimezone()
        storage.save(
            make_notification(
                1,
                title="生成周报",
                summary="竞品分析",
                status="succeeded",
                duration="1m30s",
                received_at=now,
            )
        )
        storage.save(
            make_notification(
                2,
                title="抓取网页",
                status="failed",
                source="crawler",
                error="HTTP 403",
                duration="30s",
                received_at=now,
            )
        )
        storage.save(
            make_notification(
                3,
                title="整素材",
                status="canceled",
                duration="",
                received_at=now - timedelta(days=2),
            )
        )
        storage.save(
            make_notification(
                4,
                title="旧记录",
                status="succeeded",
                duration="",
                received_at=now - timedelta(days=40),
            )
        )

        assert [item.id for item in storage.search("竞品")] == ["id0001"]
        assert [item.id for item in storage.search("crawler")] == ["id0002"]
        assert [item.id for item in storage.search("403")] == ["id0002"]

        stats = storage.stats(days=7)
        assert stats["total"] == 4
        assert stats["succeeded"] == 2
        assert stats["failed"] == 1
        assert stats["canceled"] == 1
        assert stats["success_rate"] == 0.5
        assert stats["duration_samples"] == 2
        assert stats["avg_duration_seconds"] == 60
        days = {row["day"]: row for row in stats["daily"]}
        assert days[now.strftime("%Y-%m-%d")]["total"] == 2
        assert days[now.strftime("%Y-%m-%d")]["failed"] == 1
        assert len(days) <= 7
        assert now.strftime("%Y-%m-%d") in days
    finally:
        storage.close()


def test_prune_keeps_newest(tmp_path):
    storage = open_storage(tmp_path)
    try:
        now = datetime.now().astimezone()
        for index in range(6):
            storage.save(
                make_notification(
                    index, received_at=now + timedelta(seconds=index)
                )
            )
        storage.prune(3)
        assert [item.id for item in storage.load_recent(10)] == [
            "id0005",
            "id0004",
            "id0003",
        ]
    finally:
        storage.close()


def test_store_merge_keeps_session_and_clears_waiting(tmp_path):
    storage = open_storage(tmp_path)
    store = NotificationStore(storage=storage, limit=50)
    try:
        first, _ = store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="wait:s1",
                needs_input=True,
                wait_reason="permission",
                wait_source="inferred",
            )
        )
        assert first.is_waiting_input is True

        resumed, updated = store.add(
            make_notification(
                2,
                status="running",
                dedupe_key="wait:s1",
                needs_input=False,
                session_id="session-1",
                run_id="run-1",
            )
        )
        assert updated is True
        assert resumed.id == first.id
        assert resumed.needs_input is False
        assert resumed.wait_reason is None
        assert resumed.session_id == "session-1"
        assert resumed.run_id == "run-1"
        assert len(store) == 1
        assert store.stats()["needs_input"] == 0
    finally:
        store.close()


def test_store_restores_history_and_dedupe_index(tmp_path):
    storage = open_storage(tmp_path)
    store = NotificationStore(storage=storage, limit=50)
    try:
        first, _ = store.add(
            make_notification(1, dedupe_key="build", status="running")
        )
        store.add(make_notification(2))
        store.close()

        reopened = NotificationStorage(
            tmp_path / "history.db", logging.getLogger("agentbell.tests")
        )
        restored = NotificationStore(storage=reopened, limit=50)
        try:
            assert len(restored) == 2
            merged, updated = restored.add(
                make_notification(9, dedupe_key="build", status="succeeded")
            )
            assert updated is True
            assert merged.id == first.id
            assert merged.occurrence_count == 2
            assert len(restored) == 2
        finally:
            restored.close()
    finally:
        store.close()


def test_run_events_append_and_read(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        events = [
            make_event(
                "run-1",
                "started",
                base,
                notification_id="id0001",
                session_id="s-1",
                agent="claude",
                project="demo",
                status="running",
                title="任务 1",
            ),
            make_event(
                "run-1",
                "waiting_input",
                base + timedelta(seconds=10),
                notification_id="id0001",
                status="running",
            ),
            make_event(
                "run-1",
                "resumed",
                base + timedelta(seconds=40),
                notification_id="id0001",
                status="running",
            ),
            make_event(
                "run-1",
                "finished",
                base + timedelta(seconds=60),
                notification_id="id0001",
                status="succeeded",
            ),
        ]
        for event in events:
            assert storage.append_run_event(event) is True
        loaded = storage.load_run_events("run-1")
        assert [event.kind for event in loaded] == [
            "started",
            "waiting_input",
            "resumed",
            "finished",
        ]
        assert loaded[0].kind_label == "开始"
        assert loaded[0].notification_id == "id0001"
        assert loaded[0].session_id == "s-1"
        assert loaded[0].agent == "claude"
        assert loaded[0].project == "demo"
        assert loaded[-1].status == "succeeded"
    finally:
        storage.close()


def test_run_events_merge_same_phase_within_five_seconds(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        assert storage.append_run_event(make_event("run-2", "progress", base)) is True
        assert (
            storage.append_run_event(
                make_event("run-2", "progress", base + timedelta(seconds=2))
            )
            is False
        )
        assert (
            storage.append_run_event(
                make_event("run-2", "progress", base + timedelta(seconds=6))
            )
            is True
        )
        assert (
            storage.append_run_event(
                make_event("run-2", "started", base + timedelta(seconds=6))
            )
            is True
        )
        assert [event.kind for event in storage.load_run_events("run-2")] == [
            "progress",
            "progress",
            "started",
        ]
    finally:
        storage.close()


def test_run_events_reject_invalid_input(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        assert (
            storage.append_run_event(make_event("", "started", base)) is False
        )
        assert (
            storage.append_run_event(
                make_event("run-3", "bogus", base)  # type: ignore[arg-type]
            )
            is False
        )
        assert storage.load_run_events("") == []
    finally:
        storage.close()


def test_run_stats_aggregate_durations_and_waiting(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        for index in range(3):
            start = base + timedelta(minutes=index * 10)
            duration = 60 * (index + 1)
            storage.append_run_event(make_event(f"run-{index}", "started", start))
            if index == 0:
                storage.append_run_event(
                    make_event("run-0", "waiting_input", start + timedelta(seconds=5))
                )
                storage.append_run_event(
                    make_event("run-0", "resumed", start + timedelta(seconds=35))
                )
            storage.append_run_event(
                make_event(
                    f"run-{index}",
                    "finished",
                    start + timedelta(seconds=duration),
                    status="succeeded" if index < 2 else "failed",
                )
            )
        stats = storage.stats(days=7)
        assert stats["runs"] == 3
        assert stats["run_success_rate"] == 2 / 3
        assert stats["run_duration_p50_seconds"] == 120
        assert stats["run_duration_p90_seconds"] == 180
        assert stats["waiting_seconds_total"] == 30
    finally:
        storage.close()


def test_delete_removes_only_orphan_run_events(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        storage.save(make_notification(1, run_id="run-shared"))
        storage.save(make_notification(2, run_id="run-shared"))
        storage.append_run_event(make_event("run-shared", "started", base))
        storage.delete("id0001")
        assert [event.kind for event in storage.load_run_events("run-shared")] == [
            "started"
        ]
        storage.delete("id0002")
        assert storage.load_run_events("run-shared") == []
    finally:
        storage.close()


def test_prune_and_clear_remove_orphan_run_events(tmp_path):
    storage = open_storage(tmp_path)
    try:
        now = datetime.now().astimezone()
        storage.save(
            make_notification(1, run_id="run-old", received_at=now)
        )
        storage.save(
            make_notification(
                2, run_id="run-new", received_at=now + timedelta(seconds=10)
            )
        )
        storage.append_run_event(make_event("run-old", "started", now))
        storage.append_run_event(
            make_event("run-new", "started", now + timedelta(seconds=10))
        )
        storage.prune(1)
        assert storage.load_run_events("run-old") == []
        assert len(storage.load_run_events("run-new")) == 1

        storage.clear()
        assert storage.load_run_events("run-new") == []
    finally:
        storage.close()


def test_load_session_run_events_returns_latest_run(tmp_path):
    storage = open_storage(tmp_path)
    try:
        base = datetime.now().astimezone()
        storage.append_run_event(
            make_event("run-a", "started", base, session_id="s-1")
        )
        storage.append_run_event(
            make_event(
                "run-a", "finished", base + timedelta(seconds=10), session_id="s-1"
            )
        )
        storage.append_run_event(
            make_event(
                "run-b",
                "started",
                base + timedelta(minutes=5),
                session_id="s-1",
            )
        )
        storage.append_run_event(
            make_event(
                "run-b",
                "waiting_input",
                base + timedelta(minutes=6),
                session_id="s-1",
            )
        )
        events = storage.load_session_run_events("s-1")
        assert [event.run_id for event in events] == ["run-b", "run-b"]
        assert [event.kind for event in events] == ["started", "waiting_input"]
        assert storage.load_session_run_events("missing") == []
    finally:
        storage.close()
