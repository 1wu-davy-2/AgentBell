from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path

from .models import (
    RUN_EVENT_KINDS,
    Notification,
    NotificationAction,
    RunEvent,
    duration_to_seconds,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
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
    needs_input INTEGER NOT NULL DEFAULT 0,
    wait_reason TEXT NOT NULL DEFAULT '',
    wait_source TEXT NOT NULL DEFAULT '',
    session_id TEXT,
    run_id TEXT,
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
CREATE INDEX IF NOT EXISTS idx_notifications_received
    ON notifications(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_notifications_dedupe
    ON notifications(dedupe_key);
CREATE INDEX IF NOT EXISTS idx_notifications_status
    ON notifications(status);
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    notification_id TEXT,
    session_id TEXT,
    agent TEXT NOT NULL DEFAULT '',
    project TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_run
    ON run_events(run_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_run_events_session
    ON run_events(session_id);
"""

_EXTRA_COLUMNS = (
    ("needs_input", "INTEGER NOT NULL DEFAULT 0"),
    ("wait_reason", "TEXT NOT NULL DEFAULT ''"),
    ("wait_source", "TEXT NOT NULL DEFAULT ''"),
    ("session_id", "TEXT"),
    ("run_id", "TEXT"),
)

_EXTRA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_notifications_needs_input
    ON notifications(needs_input);
CREATE INDEX IF NOT EXISTS idx_notifications_run
    ON notifications(run_id);
"""

_COLUMNS = (
    "id, title, status, summary, duration, duration_seconds, link, error, "
    "received_at, updated_at, priority, source, dedupe_key, needs_input, "
    "wait_reason, wait_source, session_id, run_id, require_ack, "
    "silent, acknowledged, acknowledged_at, occurrence_count, progress, "
    "actions, bypass_quiet_hours, auto_close_seconds, expires_at, rule_name, "
    "channel_types"
)

_UPSERT = f"""
INSERT INTO notifications ({_COLUMNS})
VALUES ({", ".join("?" for _ in range(30))})
ON CONFLICT(id) DO UPDATE SET
    title = excluded.title,
    status = excluded.status,
    summary = excluded.summary,
    duration = excluded.duration,
    duration_seconds = excluded.duration_seconds,
    link = excluded.link,
    error = excluded.error,
    received_at = excluded.received_at,
    updated_at = excluded.updated_at,
    priority = excluded.priority,
    source = excluded.source,
    dedupe_key = excluded.dedupe_key,
    needs_input = excluded.needs_input,
    wait_reason = excluded.wait_reason,
    wait_source = excluded.wait_source,
    session_id = excluded.session_id,
    run_id = excluded.run_id,
    require_ack = excluded.require_ack,
    silent = excluded.silent,
    acknowledged = excluded.acknowledged,
    acknowledged_at = excluded.acknowledged_at,
    occurrence_count = excluded.occurrence_count,
    progress = excluded.progress,
    actions = excluded.actions,
    bypass_quiet_hours = excluded.bypass_quiet_hours,
    auto_close_seconds = excluded.auto_close_seconds,
    expires_at = excluded.expires_at,
    rule_name = excluded.rule_name,
    channel_types = excluded.channel_types
"""


class StorageError(RuntimeError):
    """Raised when the SQLite history store cannot be opened."""


def _ensure_columns(connection: sqlite3.Connection) -> None:
    existing = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(notifications)").fetchall()
    }
    for name, definition in _EXTRA_COLUMNS:
        if name not in existing:
            connection.execute(
                f"ALTER TABLE notifications ADD COLUMN {name} {definition}"
            )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="milliseconds") if value is not None else None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _actions_to_json(actions: tuple[NotificationAction, ...]) -> str:
    return json.dumps(
        [{"kind": a.kind, "label": a.label, "value": a.value} for a in actions],
        ensure_ascii=False,
    )


def _actions_from_json(raw: str | None) -> tuple[NotificationAction, ...]:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, list):
        return ()
    actions: list[NotificationAction] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        label = item.get("label")
        value = item.get("value", "")
        if kind not in {
            "open",
            "copy",
            "retry",
            "path",
            "center",
            "focus",
            "session",
            "timeline",
        }:
            continue
        if not isinstance(label, str) or not label:
            continue
        if not isinstance(value, str):
            value = ""
        actions.append(NotificationAction(kind=kind, label=label[:40], value=value[:2048]))
    return tuple(actions)


def _channels_from_json(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(item for item in data if isinstance(item, str))[:20]


def _row_values(notification: Notification) -> tuple[object, ...]:
    return (
        notification.id,
        notification.title,
        notification.status,
        notification.summary,
        notification.duration,
        duration_to_seconds(notification.duration),
        notification.link,
        notification.error,
        _iso(notification.received_at),
        _iso(notification.updated_at),
        notification.priority,
        notification.source,
        notification.dedupe_key,
        int(notification.needs_input),
        notification.wait_reason or "",
        notification.wait_source or "",
        notification.session_id,
        notification.run_id,
        int(notification.require_ack),
        int(notification.silent),
        int(notification.acknowledged),
        _iso(notification.acknowledged_at),
        notification.occurrence_count,
        notification.progress,
        _actions_to_json(notification.actions),
        int(notification.bypass_quiet_hours),
        notification.auto_close_seconds,
        _iso(notification.expires_at),
        notification.rule_name,
        json.dumps(list(notification.channel_types), ensure_ascii=False),
    )


def _row_to_run_event(row: sqlite3.Row) -> RunEvent:
    kind = row["kind"] if row["kind"] in RUN_EVENT_KINDS else "note"
    return RunEvent(
        id=int(row["id"]),
        run_id=row["run_id"],
        notification_id=row["notification_id"],
        session_id=row["session_id"],
        agent=row["agent"] or "",
        project=row["project"] or "",
        kind=kind,
        status=row["status"] or "",
        title=row["title"] or "",
        detail=row["detail"] or "",
        occurred_at=_parse_dt(row["occurred_at"]) or datetime.now().astimezone(),
    )


def _row_to_notification(row: sqlite3.Row) -> Notification:
    return Notification(
        id=row["id"],
        title=row["title"],
        status=row["status"],
        summary=row["summary"] or "",
        duration=row["duration"] or "",
        link=row["link"],
        error=row["error"],
        received_at=_parse_dt(row["received_at"]) or datetime.now().astimezone(),
        updated_at=_parse_dt(row["updated_at"]),
        priority=row["priority"] or "normal",
        source=row["source"] or "",
        dedupe_key=row["dedupe_key"],
        needs_input=bool(row["needs_input"]),
        wait_reason=row["wait_reason"] or None,
        wait_source=row["wait_source"] or None,
        session_id=row["session_id"],
        run_id=row["run_id"],
        require_ack=bool(row["require_ack"]),
        silent=bool(row["silent"]),
        acknowledged=bool(row["acknowledged"]),
        acknowledged_at=_parse_dt(row["acknowledged_at"]),
        occurrence_count=max(1, int(row["occurrence_count"] or 1)),
        progress=row["progress"],
        actions=_actions_from_json(row["actions"]),
        bypass_quiet_hours=bool(row["bypass_quiet_hours"]),
        auto_close_seconds=row["auto_close_seconds"],
        expires_at=_parse_dt(row["expires_at"]),
        rule_name=row["rule_name"] or "",
        channel_types=_channels_from_json(row["channel_types"]),
    )


class NotificationStorage:
    """SQLite-backed history with WAL enabled and a single serialized writer."""

    def __init__(self, path: Path, logger: logging.Logger | None = None) -> None:
        self.path = Path(path)
        self._logger = logger or logging.getLogger("agentbell.storage")
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._connection = sqlite3.connect(
                str(self.path), check_same_thread=False, timeout=5.0
            )
        except (OSError, sqlite3.Error) as exc:
            raise StorageError(f"无法打开历史数据库 {self.path}：{exc}") from exc
        self._connection.row_factory = sqlite3.Row
        try:
            with self._lock:
                self._connection.execute("PRAGMA journal_mode=WAL")
                self._connection.execute("PRAGMA synchronous=NORMAL")
                self._connection.executescript(_SCHEMA)
                _ensure_columns(self._connection)
                self._connection.executescript(_EXTRA_INDEXES)
                self._connection.commit()
        except sqlite3.Error as exc:
            self._connection.close()
            raise StorageError(f"无法初始化历史数据库 {self.path}：{exc}") from exc

    def save(self, notification: Notification) -> None:
        with self._lock:
            try:
                self._connection.execute(_UPSERT, _row_values(notification))
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.warning("写入通知历史失败 id=%s：%s", notification.id, exc)

    def load_recent(self, limit: int) -> list[Notification]:
        with self._lock:
            try:
                rows = self._connection.execute(
                    f"SELECT * FROM notifications "
                    f"ORDER BY received_at DESC, rowid DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning("读取通知历史失败：%s", exc)
                return []
        return [_row_to_notification(row) for row in rows]

    def append_run_event(self, event: RunEvent) -> bool:
        """Append one timeline event, merging same-phase reports within 5 seconds."""
        if event.kind not in RUN_EVENT_KINDS or not event.run_id:
            return False
        with self._lock:
            try:
                last = self._connection.execute(
                    "SELECT occurred_at FROM run_events "
                    "WHERE run_id = ? AND kind = ? "
                    "ORDER BY occurred_at DESC, id DESC LIMIT 1",
                    (event.run_id, event.kind),
                ).fetchone()
                if last is not None:
                    previous = _parse_dt(last["occurred_at"])
                    if previous is not None:
                        delta = abs(
                            (event.occurred_at - previous).total_seconds()
                        )
                        if delta < 5:
                            return False
                self._connection.execute(
                    "INSERT INTO run_events (run_id, notification_id, session_id, "
                    "agent, project, kind, status, title, detail, occurred_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event.run_id,
                        event.notification_id,
                        event.session_id,
                        event.agent,
                        event.project,
                        event.kind,
                        event.status,
                        event.title,
                        event.detail,
                        _iso(event.occurred_at),
                    ),
                )
                self._connection.commit()
                return True
            except sqlite3.Error as exc:
                self._logger.warning(
                    "写入运行事件失败 run=%s：%s", event.run_id, exc
                )
                return False

    def load_run_events(self, run_id: str, limit: int = 200) -> list[RunEvent]:
        if not run_id:
            return []
        with self._lock:
            try:
                rows = self._connection.execute(
                    "SELECT * FROM run_events WHERE run_id = ? "
                    "ORDER BY occurred_at ASC, id ASC LIMIT ?",
                    (run_id, int(limit)),
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning(
                    "读取运行时间线失败 run=%s：%s", run_id, exc
                )
                return []
        return [_row_to_run_event(row) for row in rows]

    def load_session_run_events(
        self, session_id: str, limit: int = 200
    ) -> list[RunEvent]:
        """Return the events of the newest run recorded for one session."""
        if not session_id:
            return []
        with self._lock:
            try:
                rows = self._connection.execute(
                    "SELECT * FROM run_events WHERE session_id = ? "
                    "ORDER BY occurred_at DESC, id DESC LIMIT ?",
                    (session_id, int(limit)),
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning(
                    "读取会话运行时间线失败 session=%s：%s", session_id, exc
                )
                return []
        if not rows:
            return []
        latest_run = rows[0]["run_id"]
        events = [
            _row_to_run_event(row) for row in rows if row["run_id"] == latest_run
        ]
        events.reverse()
        return events

    def search(self, query: str, limit: int = 200) -> list[Notification]:
        text = (query or "").strip()
        if not text:
            return self.load_recent(limit)
        pattern = text.lower()
        with self._lock:
            try:
                rows = self._connection.execute(
                    "SELECT * FROM notifications WHERE "
                    "instr(lower(title), ?) > 0 OR instr(lower(summary), ?) > 0 "
                    "OR instr(lower(IFNULL(error, '')), ?) > 0 "
                    "OR instr(lower(source), ?) > 0 "
                    "ORDER BY received_at DESC, rowid DESC LIMIT ?",
                    (pattern, pattern, pattern, pattern, int(limit)),
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning("搜索通知历史失败：%s", exc)
                return []
        return [_row_to_notification(row) for row in rows]

    def stats(self, days: int = 7) -> dict[str, object]:
        with self._lock:
            try:
                counts = {
                    row["status"]: int(row["total"])
                    for row in self._connection.execute(
                        "SELECT status, COUNT(*) AS total FROM notifications "
                        "GROUP BY status"
                    ).fetchall()
                }
                awaiting = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM notifications "
                        "WHERE require_ack = 1 AND acknowledged = 0"
                    ).fetchone()[0]
                )
                needs_input = int(
                    self._connection.execute(
                        "SELECT COUNT(*) FROM notifications "
                        "WHERE needs_input = 1 AND status = 'running'"
                    ).fetchone()[0]
                )
                avg_row = self._connection.execute(
                    "SELECT AVG(duration_seconds), COUNT(duration_seconds) "
                    "FROM notifications WHERE duration_seconds IS NOT NULL "
                    "AND status IN ('succeeded', 'failed', 'canceled')"
                ).fetchone()
                since = (
                    datetime.now().astimezone() - timedelta(days=max(1, days))
                ).date().isoformat()
                daily_rows = self._connection.execute(
                    "SELECT substr(received_at, 1, 10) AS day, COUNT(*) AS total, "
                    "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed "
                    "FROM notifications WHERE substr(received_at, 1, 10) >= ? "
                    "GROUP BY day ORDER BY day ASC",
                    (since,),
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning("统计通知历史失败：%s", exc)
                return _empty_stats()

        total = sum(counts.values())
        completed = (
            counts.get("succeeded", 0)
            + counts.get("failed", 0)
            + counts.get("canceled", 0)
        )
        success_rate = (
            counts.get("succeeded", 0) / completed if completed > 0 else None
        )
        avg = avg_row[0] if avg_row else None
        run_stats = self._run_stats_locked()
        return {
            **run_stats,
            "total": total,
            "succeeded": counts.get("succeeded", 0),
            "failed": counts.get("failed", 0),
            "canceled": counts.get("canceled", 0),
            "running": counts.get("running", 0),
            "awaiting_ack": awaiting,
            "needs_input": needs_input,
            "success_rate": success_rate,
            "avg_duration_seconds": float(avg) if avg is not None else None,
            "duration_samples": int(avg_row[1]) if avg_row else 0,
            "daily": [
                {
                    "day": row["day"],
                    "total": int(row["total"]),
                    "failed": int(row["failed"] or 0),
                }
                for row in daily_rows
            ],
        }

    def delete(self, notification_id: str) -> None:
        with self._lock:
            try:
                row = self._connection.execute(
                    "SELECT run_id FROM notifications WHERE id = ?",
                    (notification_id,),
                ).fetchone()
                self._connection.execute(
                    "DELETE FROM notifications WHERE id = ?", (notification_id,)
                )
                if row is not None and row["run_id"]:
                    still_used = self._connection.execute(
                        "SELECT 1 FROM notifications WHERE run_id = ? LIMIT 1",
                        (row["run_id"],),
                    ).fetchone()
                    if still_used is None:
                        self._connection.execute(
                            "DELETE FROM run_events WHERE run_id = ?",
                            (row["run_id"],),
                        )
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.warning("删除通知历史失败 id=%s：%s", notification_id, exc)

    def prune(self, limit: int) -> None:
        with self._lock:
            try:
                self._connection.execute(
                    "DELETE FROM notifications WHERE id NOT IN "
                    "(SELECT id FROM notifications "
                    "ORDER BY received_at DESC, rowid DESC LIMIT ?)",
                    (int(limit),),
                )
                self._connection.execute(
                    "DELETE FROM run_events WHERE run_id NOT IN "
                    "(SELECT run_id FROM notifications "
                    "WHERE run_id IS NOT NULL AND run_id != '')"
                )
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.warning("清理通知历史失败：%s", exc)

    def clear(self) -> None:
        with self._lock:
            try:
                self._connection.execute("DELETE FROM notifications")
                self._connection.execute("DELETE FROM run_events")
                self._connection.commit()
            except sqlite3.Error as exc:
                self._logger.warning("清空通知历史失败：%s", exc)

    def _run_stats_locked(self) -> dict[str, object]:
        with self._lock:
            try:
                rows = self._connection.execute(
                    "SELECT run_id, kind, status, occurred_at FROM run_events "
                    "ORDER BY run_id ASC, occurred_at ASC, id ASC"
                ).fetchall()
            except sqlite3.Error as exc:
                self._logger.warning("统计运行时间线失败：%s", exc)
                return _empty_run_stats()

        grouped: dict[str, list[tuple[str, str, datetime]]] = {}
        for row in rows:
            occurred = _parse_dt(row["occurred_at"])
            if occurred is None:
                continue
            grouped.setdefault(row["run_id"], []).append(
                (row["kind"], row["status"] or "", occurred)
            )

        now = datetime.now().astimezone()
        durations: list[float] = []
        waiting_total = 0.0
        finished_runs = 0
        succeeded_runs = 0
        for events in grouped.values():
            start = next(
                (moment for kind, _, moment in events if kind == "started"),
                events[0][2],
            )
            finish = next(
                (
                    (status, moment)
                    for kind, status, moment in reversed(events)
                    if kind == "finished"
                ),
                None,
            )
            if finish is not None:
                finished_runs += 1
                durations.append(max(0.0, (finish[1] - start).total_seconds()))
                if finish[0] == "succeeded":
                    succeeded_runs += 1

            waiting_since: datetime | None = None
            for kind, _status, moment in events:
                if kind == "waiting_input":
                    if waiting_since is None:
                        waiting_since = moment
                elif kind in {"resumed", "finished"} and waiting_since is not None:
                    waiting_total += max(
                        0.0, (moment - waiting_since).total_seconds()
                    )
                    waiting_since = None
            if waiting_since is not None:
                waiting_total += max(0.0, (now - waiting_since).total_seconds())

        durations.sort()
        return {
            "runs": len(grouped),
            "run_success_rate": (
                succeeded_runs / finished_runs if finished_runs > 0 else None
            ),
            "run_duration_p50_seconds": _percentile(durations, 0.5),
            "run_duration_p90_seconds": _percentile(durations, 0.9),
            "waiting_seconds_total": waiting_total,
        }

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    index = max(
        0,
        min(len(values) - 1, int(fraction * len(values) + 0.999999) - 1),
    )
    return values[index]


def _empty_run_stats() -> dict[str, object]:
    return {
        "runs": 0,
        "run_success_rate": None,
        "run_duration_p50_seconds": None,
        "run_duration_p90_seconds": None,
        "waiting_seconds_total": 0.0,
    }


def _empty_stats() -> dict[str, object]:
    return {
        **_empty_run_stats(),
        "total": 0,
        "succeeded": 0,
        "failed": 0,
        "canceled": 0,
        "running": 0,
        "awaiting_ack": 0,
        "needs_input": 0,
        "success_rate": None,
        "avg_duration_seconds": None,
        "duration_samples": 0,
        "daily": [],
    }
