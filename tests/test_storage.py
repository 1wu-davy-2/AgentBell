from __future__ import annotations

import logging
from datetime import datetime, timedelta

from agentbell.models import Notification, NotificationAction
from agentbell.storage import NotificationStorage
from agentbell.store import NotificationStore


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
        assert [action.kind for action in item.actions] == ["open", "retry"]
        assert item.bypass_quiet_hours is True
        assert item.auto_close_seconds == 0
        assert item.expires_at is not None
        assert item.rule_name == "部署规则"
        assert item.channel_types == ("webhook", "ntfy")
        assert abs(item.received_at.timestamp() - received.timestamp()) < 0.001
    finally:
        storage.close()


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
