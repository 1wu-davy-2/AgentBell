from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime

from agentbell.models import Notification
from agentbell.storage import NotificationStorage
from agentbell.store import NotificationStore


def make_notification(index: int, **overrides) -> Notification:
    values = {
        "id": f"id{index}",
        "title": f"任务 {index}",
        "status": "succeeded",
    }
    values.update(overrides)
    return Notification(**values)


def test_keeps_newest_first():
    store = NotificationStore()
    for index in range(3):
        store.add(make_notification(index))

    assert len(store) == 3
    assert [item.title for item in store.snapshot()] == ["任务 2", "任务 1", "任务 0"]


def test_limit_evicts_oldest():
    store = NotificationStore(limit=2)
    for index in range(4):
        store.add(make_notification(index))

    assert len(store) == 2
    assert [item.id for item in store.snapshot()] == ["id3", "id2"]


def test_snapshot_is_a_copy():
    store = NotificationStore()
    store.add(make_notification(1))

    snapshot = store.snapshot()
    snapshot.clear()

    assert len(store) == 1


def test_dedupe_updates_existing_card():
    store = NotificationStore()
    first, updated = store.add(
        make_notification(
            1,
            status="running",
            progress=10,
            dedupe_key="long-task",
            summary="第一步",
            priority="normal",
            popup_mode="center",
            popup_skin="amber",
        )
    )
    assert updated is False

    stored = store.acknowledge(first.id)
    assert stored is not None and stored.acknowledged is True

    second, updated = store.add(
        make_notification(
            2,
            status="failed",
            dedupe_key="long-task",
            error="boom",
            priority="high",
        )
    )
    assert updated is True
    assert second.id == first.id
    assert second.received_at == first.received_at
    assert second.occurrence_count == 2
    assert second.status == "failed"
    assert second.acknowledged is False
    assert second.priority == "high"
    assert second.summary == "第一步"
    assert second.error == "boom"
    assert second.progress is None
    assert second.popup_mode == "center"
    assert second.popup_skin == "amber"
    assert len(store) == 1
    assert store.find_by_dedupe("long-task").id == first.id


def test_same_dedupe_key_keeps_highest_priority():
    store = NotificationStore()
    store.add(
        make_notification(1, dedupe_key="k", priority="critical")
    )
    merged, _ = store.add(
        make_notification(2, dedupe_key="k", priority="low")
    )
    assert merged.priority == "critical"


def test_replace_notification_keeps_counters():
    store = NotificationStore()
    notification, _ = store.add(
        make_notification(1, dedupe_key="k", require_ack=False)
    )
    resolved = replace(
        notification,
        require_ack=True,
        auto_close_seconds=0,
    )
    stored = store.replace_notification(resolved)
    assert stored.require_ack is True
    assert stored.occurrence_count == 1
    assert store.find(notification.id).auto_close_seconds == 0


def test_acknowledge_marks_and_is_idempotent():
    store = NotificationStore()
    notification, _ = store.add(
        make_notification(1, require_ack=True)
    )
    now = datetime.now().astimezone()
    acked = store.acknowledge(notification.id, now=now)
    assert acked.acknowledged is True
    assert acked.acknowledged_at == now
    assert acked.needs_ack is False

    again = store.acknowledge(notification.id)
    assert again.acknowledged_at == now
    assert store.acknowledge("missing") is None


def test_search_matches_title_summary_source_and_error():
    store = NotificationStore()
    store.add(make_notification(1, title="生成周报", summary="含竞品分析"))
    store.add(
        make_notification(
            2, title="抓取网页", source="crawler", error="HTTP 403"
        )
    )
    store.add(make_notification(3, title="整理素材"))

    assert [item.id for item in store.search("竞品")] == ["id1"]
    assert [item.id for item in store.search("crawler")] == ["id2"]
    assert [item.id for item in store.search("403")] == ["id2"]
    assert len(store.search("")) == 3
    assert store.search("不存在") == []


def test_memory_stats():
    store = NotificationStore()
    store.add(
        make_notification(
            1, status="succeeded", duration="1m", require_ack=True
        )
    )
    store.add(make_notification(2, status="failed", duration="30s"))
    store.add(make_notification(3, status="canceled"))
    store.add(make_notification(4, status="running", duration="5m"))

    stats = store.stats()
    assert stats["total"] == 4
    assert stats["succeeded"] == 1
    assert stats["failed"] == 1
    assert stats["canceled"] == 1
    assert stats["running"] == 1
    assert stats["awaiting_ack"] == 1
    assert stats["success_rate"] == 1 / 3
    assert stats["duration_samples"] == 2
    assert stats["avg_duration_seconds"] == 45
    assert stats["daily"] == []
    assert stats["runs"] == 0


def open_persistent_store(tmp_path) -> NotificationStore:
    storage = NotificationStorage(
        tmp_path / "history.db", logging.getLogger("agentbell.tests")
    )
    return NotificationStore(storage=storage, limit=50)


def test_run_id_prefers_session_then_dedupe_then_single(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        by_session, _ = store.add(make_notification(1, session_id="s-1"))
        by_dedupe, _ = store.add(make_notification(2, dedupe_key="build"))
        by_single, _ = store.add(make_notification(3))
        explicit, _ = store.add(make_notification(4, run_id="client-run"))

        assert by_session.run_id == "session:s-1"
        assert by_dedupe.run_id == "notify:build"
        assert by_single.run_id == "single:id3"
        assert explicit.run_id == "client-run"

        updated, _ = store.add(
            make_notification(5, dedupe_key="build", status="running")
        )
        assert updated.run_id == "notify:build"
    finally:
        store.close()


def test_store_infers_started_waiting_resumed_finished(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        first, _ = store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="task",
                session_id="s-1",
                title="任务 1",
            )
        )
        run_id = first.run_id
        assert [event.kind for event in store.run_events(run_id)] == ["started"]

        store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="task",
                needs_input=True,
                wait_reason="question",
                title="任务 1",
            )
        )
        assert [event.kind for event in store.run_events(run_id)] == [
            "started",
            "waiting_input",
        ]

        store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="task",
                needs_input=False,
                title="任务 1",
            )
        )
        store.add(
            make_notification(
                1,
                status="succeeded",
                dedupe_key="task",
                title="任务 1",
            )
        )
        assert [event.kind for event in store.run_events(run_id)] == [
            "started",
            "waiting_input",
            "resumed",
            "finished",
        ]
        assert store.run_events(run_id)[-1].status == "succeeded"
    finally:
        store.close()


def test_explicit_phase_appends_single_event(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        stored, _ = store.add(
            make_notification(1, status="running"),
            phase="progress",
            project="demo",
        )
        events = store.run_events(stored.run_id)
        assert [event.kind for event in events] == ["progress"]
        assert events[0].project == "demo"
    finally:
        store.close()


def test_new_session_event_resumes_previous_wait(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        waiting, _ = store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="wait:s-1",
                session_id="s-1",
                needs_input=True,
            )
        )
        store.add(
            make_notification(
                2,
                status="running",
                dedupe_key="progress:s-1",
                session_id="s-1",
            )
        )
        assert store.find(waiting.id).needs_input is False
        assert [event.kind for event in store.run_events("session:s-1")] == [
            "started",
            "waiting_input",
            "resumed",
        ]
    finally:
        store.close()


def test_same_phase_within_five_seconds_appends_once(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        store.add(
            make_notification(1, status="running", run_id="run-x"),
            phase="progress",
        )
        store.add(
            make_notification(2, status="running", run_id="run-x"),
            phase="progress",
        )
        assert [event.kind for event in store.run_events("run-x")] == ["progress"]
    finally:
        store.close()
