from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta

from agentbell.models import IntegrationProfile, Notification
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


def test_search_supports_field_filters():
    store = NotificationStore()
    first, _ = store.add(
        make_notification(
            1,
            status="failed",
            source="claude",
            priority="high",
            session_id="sess-abc",
            run_id="run-1",
        )
    )
    store.add(
        make_notification(
            2,
            status="succeeded",
            source="qoder",
            priority="normal",
            session_id="sess-xyz",
            run_id="run-2",
        )
    )
    store.acknowledge(first.id)

    assert [item.id for item in store.search("status:failed")] == ["id1"]
    assert [item.id for item in store.search("status:失败")] == ["id1"]
    assert [item.id for item in store.search("source:CLAUDE")] == ["id1"]
    assert [item.id for item in store.search("priority:high")] == ["id1"]
    assert [item.id for item in store.search("session:abc")] == ["id1"]
    assert [item.id for item in store.search("run:run-2")] == ["id2"]
    assert [item.id for item in store.search("ack:yes")] == ["id1"]
    assert [item.id for item in store.search("ack:no")] == ["id2"]
    assert [item.id for item in store.search("status:failed status:succeeded")] == [
        "id2",
        "id1",
    ]
    assert [item.id for item in store.search("source:qoder 任务")] == ["id2"]


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


def test_session_notifications_returns_oldest_first(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        base = datetime.now().astimezone()
        for index in range(3):
            store.add(
                make_notification(
                    index + 1,
                    session_id="s-1",
                    received_at=base + timedelta(minutes=index),
                )
            )
        store.add(make_notification(9, session_id="other"))
        items = store.session_notifications("s-1")
        assert [item.id for item in items] == ["id1", "id2", "id3"]
        assert [item.id for item in store.session_notifications("s-1", limit=2)] == [
            "id2",
            "id3",
        ]
        assert store.session_notifications("missing") == []
        assert store.session_notifications(None) == []
    finally:
        store.close()


def test_session_notifications_memory_fallback():
    store = NotificationStore()
    base = datetime.now().astimezone()
    store.add(make_notification(1, session_id="s-1", received_at=base))
    store.add(
        make_notification(
            2, session_id="s-1", received_at=base + timedelta(minutes=1)
        )
    )
    store.add(make_notification(3, session_id="s-2"))
    items = store.session_notifications("s-1")
    assert [item.id for item in items] == ["id1", "id2"]


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


def test_silent_start_and_final_update_share_one_card_and_timeline(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        start, start_updated = store.add(
            make_notification(
                1,
                status="running",
                dedupe_key="round-1",
                run_id="round-1",
                silent=True,
            ),
            phase="started",
        )
        final, final_updated = store.add(
            make_notification(
                2,
                status="succeeded",
                dedupe_key="round-1",
                run_id="round-1",
                title="任务完成",
            ),
            phase="finished",
        )

        assert start_updated is False
        assert final_updated is True
        assert final.id == start.id
        assert len(store) == 1
        assert [event.kind for event in store.run_events("round-1")] == [
            "started",
            "finished",
        ]
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


def test_archive_updates_memory_and_persists(tmp_path):
    store = open_persistent_store(tmp_path)
    try:
        first, _ = store.add(make_notification(1))
        second, _ = store.add(make_notification(2))

        assert store.archive([first.id]) == 1
        archived = store.find(first.id)
        assert archived is not None and archived.archived is True
        assert archived.archived_at is not None
        assert store.find(second.id).archived is False
        assert store.archive([first.id]) == 0

        assert store.archive([first.id], archived=False) == 1
        restored = store.find(first.id)
        assert restored is not None and restored.archived is False
        assert restored.archived_at is None
    finally:
        store.close()

    reopened = open_persistent_store(tmp_path)
    try:
        persisted = reopened.find(first.id)
        assert persisted is not None and persisted.archived is False
    finally:
        reopened.close()


def test_integration_profiles_memory_and_persistent(tmp_path):
    now = datetime.now().astimezone()
    store = NotificationStore()
    profile = IntegrationProfile(
        agent="Qoder",
        mode="finish_only",
        source="manual",
        updated_at=now,
    )
    assert store.record_integration_profile(profile) is True
    assert store.record_integration_profile(profile) is False
    assert [item.agent for item in store.integration_profiles()] == ["Qoder"]

    storage = NotificationStorage(
        tmp_path / "history.db", logging.getLogger("agentbell.tests")
    )
    persistent = NotificationStore(storage=storage)
    try:
        persistent.record_integration_profile(
            IntegrationProfile(
                agent="Claude Code",
                mode="start_finish",
                updated_at=now + timedelta(minutes=1),
            )
        )
        profiles = persistent.integration_profiles()
        assert [item.agent for item in profiles] == ["Claude Code"]
        assert profiles[0].mode == "start_finish"
    finally:
        persistent.close()
