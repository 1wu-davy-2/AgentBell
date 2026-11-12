from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from .models import (
    PRIORITY_RANK,
    Notification,
    RunEvent,
    RunEventKind,
    duration_to_seconds,
)
from .search_query import SearchQuery, parse_search
from .storage import NotificationStorage

DEFAULT_HISTORY_LIMIT = 1000


class NotificationStore:
    """Thread-safe notification history shared by the HTTP API and the UI."""

    def __init__(
        self,
        limit: int = DEFAULT_HISTORY_LIMIT,
        storage: NotificationStorage | None = None,
        logger: logging.Logger | None = None,
        retention_days: int = 0,
    ) -> None:
        self._limit = max(1, int(limit))
        self._retention_days = max(0, int(retention_days))
        self._items: deque[Notification] = deque(maxlen=self._limit)
        self._by_id: dict[str, Notification] = {}
        self._dedupe_index: dict[str, str] = {}
        self._lock = threading.RLock()
        self._storage = storage
        self._logger = logger or logging.getLogger("agentbell.store")
        if storage is not None:
            storage.prune(self._limit, self._retention_days)
            for notification in storage.load_recent(self._limit):
                self._insert_locked(notification)

    # ---------- writes ----------

    def add(
        self,
        notification: Notification,
        *,
        phase: RunEventKind | None = None,
        project: str = "",
    ) -> tuple[Notification, bool]:
        """Insert or update a notification.

        Returns (stored_notification, was_updated). A notification carrying a
        dedupe_key replaces the previous card instead of stacking a new one.
        Run events are appended for explicit phases or inferred transitions.
        """
        now = datetime.now().astimezone()
        with self._lock:
            existing = None
            if notification.dedupe_key:
                existing_id = self._dedupe_index.get(notification.dedupe_key)
                if existing_id is not None:
                    existing = self._by_id.get(existing_id)
            if not notification.run_id:
                notification = replace(
                    notification,
                    run_id=(
                        existing.run_id
                        if existing is not None and existing.run_id
                        else self._run_id_for(notification)
                    ),
                )
            if existing is not None:
                merged = self._merge(existing, notification, now)
                self._remove_locked(existing)
                self._insert_locked(merged)
                self._persist_locked(merged)
                self._clear_session_waits_locked(
                    merged.session_id, merged.id, now
                )
                self._record_transition_locked(
                    merged, existing, now, phase, project
                )
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
            self._clear_session_waits_locked(
                notification.session_id, notification.id, now
            )
            self._record_transition_locked(
                notification, None, now, phase, project
            )
            return notification, False

    def replace_notification(
        self,
        notification: Notification,
        *,
        event_kind: RunEventKind | None = None,
    ) -> Notification:
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
            if event_kind is not None:
                self._append_run_event_locked(
                    notification,
                    event_kind,
                    datetime.now().astimezone(),
                    "",
                )
            return notification

    def run_events(self, run_id: str | None, limit: int = 200) -> list[RunEvent]:
        with self._lock:
            if self._storage is None or not run_id:
                return []
            return self._storage.load_run_events(run_id, limit)

    def session_run_events(
        self, session_id: str | None, limit: int = 200
    ) -> list[RunEvent]:
        with self._lock:
            if self._storage is None or not session_id:
                return []
            return self._storage.load_session_run_events(session_id, limit)

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

    def archive(
        self, notification_ids: list[str], archived: bool = True
    ) -> int:
        """Archive or restore notifications without deleting their history."""
        target = {item for item in notification_ids if item}
        if not target:
            return 0
        now = datetime.now().astimezone()
        with self._lock:
            changed = 0
            items = list(self._items)
            for index, item in enumerate(items):
                if item.id not in target or item.archived == archived:
                    continue
                updated = replace(
                    item,
                    archived=archived,
                    archived_at=now if archived else None,
                )
                items[index] = updated
                self._by_id[item.id] = updated
                changed += 1
            if changed:
                self._items = deque(items, maxlen=self._limit)
            if self._storage is not None:
                rows = self._storage.set_archived(list(target), archived)
                return rows or changed
            return changed

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

    def search(
        self, query: str | SearchQuery, limit: int = 200
    ) -> list[Notification]:
        spec = query if isinstance(query, SearchQuery) else parse_search(query)
        with self._lock:
            if not spec.has_filters:
                return list(self._items)[:limit]
            if self._storage is not None:
                return self._storage.search(spec, limit)
            return [item for item in self._items if spec.matches(item)][:limit]

    def stats(self, days: int = 7) -> dict[str, Any]:
        with self._lock:
            if self._storage is not None:
                return self._storage.stats(days)
            return self._memory_stats_locked()

    def export(self, days: int = 7) -> list[Notification]:
        with self._lock:
            if self._storage is not None:
                return self._storage.export_notifications(days)
            cutoff = datetime.now().astimezone() - timedelta(days=max(1, days))
            return [item for item in self._items if item.received_at >= cutoff]

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def persistent(self) -> bool:
        with self._lock:
            return self._storage is not None

    def apply_history(self, limit: int, retention_days: int) -> None:
        with self._lock:
            new_limit = max(1, int(limit))
            self._retention_days = max(0, int(retention_days))
            cutoff = (
                datetime.now().astimezone()
                - timedelta(days=self._retention_days)
                if self._retention_days > 0
                else None
            )
            kept_items = [
                item
                for item in self._items
                if cutoff is None or item.received_at >= cutoff
            ][:new_limit]
            if new_limit != self._limit or len(kept_items) != len(self._items):
                self._limit = new_limit
                kept = deque(kept_items, maxlen=new_limit)
                self._items = kept
                self._by_id = {item.id: item for item in kept}
                self._dedupe_index = {
                    item.dedupe_key: item.id
                    for item in kept
                    if item.dedupe_key
                }
            if self._storage is not None:
                self._storage.prune(self._limit, self._retention_days)

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
            session_id=incoming.session_id or existing.session_id,
            run_id=incoming.run_id or existing.run_id,
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
            metadata={**existing.metadata, **incoming.metadata},
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

    @staticmethod
    def _run_id_for(notification: Notification) -> str:
        if notification.session_id:
            return f"session:{notification.session_id}"
        if notification.dedupe_key:
            return f"notify:{notification.dedupe_key}"
        return f"single:{notification.id}"

    def _has_running_locked(self, notification: Notification) -> bool:
        return any(
            item.id != notification.id
            and item.run_id == notification.run_id
            and item.status == "running"
            for item in self._items
        )

    def _record_transition_locked(
        self,
        notification: Notification,
        previous: Notification | None,
        now: datetime,
        phase: RunEventKind | None,
        project: str,
    ) -> None:
        if self._storage is None:
            return
        kinds: list[RunEventKind] = []
        if phase is not None:
            kinds.append(phase)
        elif notification.status == "running":
            if previous is None:
                if not self._has_running_locked(notification):
                    kinds.append("started")
            elif previous.status != "running":
                kinds.append("started")
            if notification.needs_input and (
                previous is None or not previous.needs_input
            ):
                kinds.append("waiting_input")
            elif (
                previous is not None
                and previous.is_waiting_input
                and not notification.needs_input
            ):
                kinds.append("resumed")
        else:
            if previous is not None and previous.is_waiting_input:
                kinds.append("resumed")
            if previous is None or previous.status != notification.status:
                kinds.append("finished")
        for kind in kinds:
            self._append_run_event_locked(notification, kind, now, project)

    def _append_run_event_locked(
        self,
        notification: Notification,
        kind: RunEventKind,
        now: datetime,
        project: str,
    ) -> None:
        if self._storage is None or not notification.run_id:
            return
        self._storage.append_run_event(
            RunEvent(
                run_id=notification.run_id,
                kind=kind,
                occurred_at=now,
                notification_id=notification.id,
                session_id=notification.session_id,
                agent=notification.source,
                project=project,
                status=notification.status,
                title=notification.title,
                detail=notification.summary,
            )
        )

    def _clear_session_waits_locked(
        self, session_id: str | None, keep_id: str, now: datetime
    ) -> None:
        """A newer event for the same session ends any previous waiting episode."""
        if not session_id:
            return
        replacements: list[Notification] = []
        updated: list[Notification] = []
        for item in self._items:
            if (
                item.is_waiting_input
                and item.session_id == session_id
                and item.id != keep_id
            ):
                replacement = replace(
                    item,
                    needs_input=False,
                    wait_reason=None,
                    wait_source=None,
                    updated_at=now,
                )
                self._by_id[item.id] = replacement
                replacements.append(replacement)
                updated.append(replacement)
            else:
                updated.append(item)
        if replacements:
            self._items = deque(updated, maxlen=self._limit)
            for replacement in replacements:
                self._persist_locked(replacement)
                self._append_run_event_locked(replacement, "resumed", now, "")

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
        self._storage.prune(self._limit, self._retention_days)

    def _memory_stats_locked(self) -> dict[str, Any]:
        counts = {"succeeded": 0, "failed": 0, "canceled": 0, "running": 0}
        awaiting = 0
        needs_input = 0
        durations: list[float] = []

        for item in self._items:
            counts[item.status] = counts.get(item.status, 0) + 1
            if item.require_ack and not item.acknowledged:
                awaiting += 1
            if item.is_waiting_input:
                needs_input += 1
            seconds = duration_to_seconds(item.duration)
            if seconds is not None and item.status != "running":
                durations.append(seconds)
        completed = counts["succeeded"] + counts["failed"] + counts["canceled"]
        return {
            "runs": 0,
            "run_success_rate": None,
            "run_duration_p50_seconds": None,
            "run_duration_p90_seconds": None,
            "waiting_seconds_total": 0.0,
            "total": len(self._items),
            "succeeded": counts["succeeded"],
            "failed": counts["failed"],
            "canceled": counts["canceled"],
            "running": counts["running"],
            "awaiting_ack": awaiting,
            "needs_input": needs_input,
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
