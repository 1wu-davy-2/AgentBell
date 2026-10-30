from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime
from typing import Any

from .models import PRIORITY_RANK, Notification, duration_to_seconds
from .storage import NotificationStorage

DEFAULT_HISTORY_LIMIT = 1000


class NotificationStore:
    """Thread-safe notification history shared by the HTTP API and the UI."""

    def __init__(
        self,
        limit: int = DEFAULT_HISTORY_LIMIT,
        storage: NotificationStorage | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._limit = max(1, int(limit))
        self._items: deque[Notification] = deque(maxlen=self._limit)
        self._by_id: dict[str, Notification] = {}
        self._dedupe_index: dict[str, str] = {}
        self._lock = threading.RLock()
        self._storage = storage
        self._logger = logger or logging.getLogger("agentbell.store")
        if storage is not None:
            for notification in storage.load_recent(self._limit):
                self._insert_locked(notification)

    # ---------- writes ----------

    def add(self, notification: Notification) -> tuple[Notification, bool]:
        """Insert or update a notification.

        Returns (stored_notification, was_updated). A notification carrying a
        dedupe_key replaces the previous card instead of stacking a new one.
        """
        now = datetime.now().astimezone()
        with self._lock:
            existing = None
            if notification.dedupe_key:
                existing_id = self._dedupe_index.get(notification.dedupe_key)
                if existing_id is not None:
                    existing = self._by_id.get(existing_id)
            if existing is not None:
                merged = self._merge(existing, notification, now)
                self._remove_locked(existing)
                self._insert_locked(merged)
                self._persist_locked(merged)
                self._logger.info(
                    "通知去重更新 id=%s key=%s 次数=%d 进度=%s",
                    merged.id,
                    self._clip(merged.dedupe_key or ""),
                    merged.occurrence_count,
                    merged.progress,
                )
                return merged, True

            self._insert_locked(notification)
            self._persist_locked(notification)
            return notification, False

    def replace_notification(self, notification: Notification) -> Notification:
        """Replace by id without touching dedupe counters or acknowledgement."""
        with self._lock:
            existing = self._by_id.get(notification.id)
            if existing is None:
                self._insert_locked(notification)
            else:
                if existing.dedupe_key and existing.dedupe_key != notification.dedupe_key:
                    self._dedupe_index.pop(existing.dedupe_key, None)
                items = list(self._items)
                for index, item in enumerate(items):
                    if item is existing:
                        items[index] = notification
                        break
                self._items = deque(items, maxlen=self._limit)
                self._by_id[notification.id] = notification
                if notification.dedupe_key:
                    self._dedupe_index[notification.dedupe_key] = notification.id
            self._persist_locked(notification)
            return notification

    def acknowledge(self, notification_id: str, now: datetime | None = None) -> Notification | None:
        with self._lock:
            existing = self._by_id.get(notification_id)
            if existing is None or existing.acknowledged:
                return existing
            updated = existing.acknowledge(now)
            self._by_id[notification_id] = updated
            items = list(self._items)
            try:
                index = items.index(existing)
            except ValueError:
                items.insert(0, updated)
            else:
                items[index] = updated
            self._items = deque(items, maxlen=self._limit)
            self._persist_locked(updated)
            return updated

    def delete(self, notification_id: str) -> None:
        with self._lock:
            existing = self._by_id.get(notification_id)
            if existing is not None:
                self._remove_locked(existing)
            if self._storage is not None:
                self._storage.delete(notification_id)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._by_id.clear()
            self._dedupe_index.clear()
            if self._storage is not None:
                self._storage.clear()

    def close(self) -> None:
        with self._lock:
            if self._storage is not None:
                self._storage.close()
                self._storage = None

    # ---------- reads ----------

    def snapshot(self) -> list[Notification]:
        with self._lock:
            return list(self._items)

    def find(self, notification_id: str) -> Notification | None:
        with self._lock:
            return self._by_id.get(notification_id)

    def find_by_dedupe(self, dedupe_key: str) -> Notification | None:
        if not dedupe_key:
            return None
        with self._lock:
            existing_id = self._dedupe_index.get(dedupe_key)
            return self._by_id.get(existing_id) if existing_id else None

    def search(self, query: str, limit: int = 200) -> list[Notification]:
        text = (query or "").strip()
        with self._lock:
            if not text:
                return list(self._items)[:limit]
            if self._storage is not None:
                return self._storage.search(text, limit)
            lowered = text.lower()
            found = [
                item
                for item in self._items
                if lowered in item.title.lower()
                or lowered in item.summary.lower()
                or lowered in (item.error or "").lower()
                or lowered in item.source.lower()
            ]
            return found[:limit]

    def stats(self, days: int = 7) -> dict[str, Any]:
        with self._lock:
            if self._storage is not None:
                return self._storage.stats(days)
            return self._memory_stats_locked()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def persistent(self) -> bool:
        with self._lock:
            return self._storage is not None

    # ---------- internals ----------

    def _merge(
        self, existing: Notification, incoming: Notification, now: datetime
    ) -> Notification:
        priority = incoming.priority
        if PRIORITY_RANK.get(existing.priority, 1) > PRIORITY_RANK.get(priority, 1):
            priority = existing.priority
        progress = incoming.progress if incoming.status == "running" else None
        if progress is None and incoming.status == "running":
            progress = existing.progress
        return replace(
            incoming,
            id=existing.id,
            received_at=existing.received_at,
            updated_at=now,
            priority=priority,
            summary=incoming.summary or existing.summary,
            duration=incoming.duration or existing.duration,
            link=incoming.link or existing.link,
            error=incoming.error or existing.error,
            source=incoming.source or existing.source,
            actions=incoming.actions or existing.actions,
            progress=progress,
            require_ack=incoming.require_ack or existing.require_ack,
            bypass_quiet_hours=incoming.bypass_quiet_hours or existing.bypass_quiet_hours,
            auto_close_seconds=(
                incoming.auto_close_seconds
                if incoming.auto_close_seconds is not None
                else existing.auto_close_seconds
            ),
            expires_at=incoming.expires_at or existing.expires_at,
            rule_name=incoming.rule_name or existing.rule_name,
            channel_types=incoming.channel_types or existing.channel_types,
            popup_mode=incoming.popup_mode or existing.popup_mode,
            popup_skin=incoming.popup_skin or existing.popup_skin,
            acknowledged=False,
            acknowledged_at=None,
            occurrence_count=existing.occurrence_count + 1,
        )

    def _insert_locked(self, notification: Notification) -> None:
        if len(self._items) >= self._limit:
            evicted = self._items[-1]
            self._forget_locked(evicted)
        self._items.appendleft(notification)
        self._by_id[notification.id] = notification
        if notification.dedupe_key:
            self._dedupe_index[notification.dedupe_key] = notification.id

    def _remove_locked(self, notification: Notification) -> None:
        try:
            self._items.remove(notification)
        except ValueError:
            pass
        self._forget_locked(notification)

    def _forget_locked(self, notification: Notification) -> None:
        current = self._by_id.get(notification.id)
        if current is notification or current is None:
            self._by_id.pop(notification.id, None)
        if notification.dedupe_key and self._dedupe_index.get(
            notification.dedupe_key
        ) == notification.id:
            self._dedupe_index.pop(notification.dedupe_key, None)

    def _persist_locked(self, notification: Notification) -> None:
        if self._storage is None:
            return
        self._storage.save(notification)
        self._storage.prune(self._limit)

    def _memory_stats_locked(self) -> dict[str, Any]:
        counts = {"succeeded": 0, "failed": 0, "canceled": 0, "running": 0}
        awaiting = 0
        durations: list[float] = []

        for item in self._items:
            counts[item.status] = counts.get(item.status, 0) + 1
            if item.require_ack and not item.acknowledged:
                awaiting += 1
            seconds = duration_to_seconds(item.duration)
            if seconds is not None and item.status != "running":
                durations.append(seconds)
        completed = counts["succeeded"] + counts["failed"] + counts["canceled"]
        return {
            "total": len(self._items),
            "succeeded": counts["succeeded"],
            "failed": counts["failed"],
            "canceled": counts["canceled"],
            "running": counts["running"],
            "awaiting_ack": awaiting,
            "success_rate": (
                counts["succeeded"] / completed if completed > 0 else None
            ),
            "avg_duration_seconds": (
                sum(durations) / len(durations) if durations else None
            ),
            "duration_samples": len(durations),
            "daily": [],
        }

    @staticmethod
    def _clip(text: str, limit: int = 60) -> str:
        text = " ".join(text.split())
        return text if len(text) <= limit else text[: limit - 1] + "…"
