from __future__ import annotations

from agentbell.models import Notification
from agentbell.store import NotificationStore


def make_notification(index: int) -> Notification:
    return Notification(id=f"id{index}", title=f"任务 {index}", status="succeeded")


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
