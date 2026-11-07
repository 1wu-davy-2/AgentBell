from __future__ import annotations

import re
from dataclasses import dataclass

from .models import PRIORITIES, PRIORITY_LABELS, STATUSES, STATUS_LABELS

_FIELD_ALIASES = {
    "status": "status",
    "状态": "status",
    "source": "source",
    "来源": "source",
    "priority": "priority",
    "优先级": "priority",
    "session": "session",
    "session_id": "session",
    "会话": "session",
    "run": "run",
    "run_id": "run",
    "运行": "run",
    "ack": "ack",
    "acknowledged": "ack",
    "确认": "ack",
}
_STATUS_ALIASES = {
    **{status: status for status in STATUSES},
    **{label.casefold(): status for status, label in STATUS_LABELS.items()},
}
_PRIORITY_ALIASES = {
    **{priority: priority for priority in PRIORITIES},
    **{label.casefold(): priority for priority, label in PRIORITY_LABELS.items()},
}
_ACK_TRUE = {"yes", "true", "1", "y", "on", "确认", "已确认"}
_ACK_FALSE = {"no", "false", "0", "n", "off", "未确认", "待确认"}
_TOKEN = re.compile(r'(?:[^\s"]+|"[^"]*")+')


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str = ""
    status: tuple[str, ...] = ()
    source: tuple[str, ...] = ()
    priority: tuple[str, ...] = ()
    session: tuple[str, ...] = ()
    run: tuple[str, ...] = ()
    acknowledged: bool | None = None

    @property
    def has_filters(self) -> bool:
        return bool(
            self.text
            or self.status
            or self.source
            or self.priority
            or self.session
            or self.run
            or self.acknowledged is not None
        )

    def matches(self, item: object) -> bool:
        if self.status and getattr(item, "status", "") not in self.status:
            return False
        if self.priority and getattr(item, "priority", "") not in self.priority:
            return False
        if self.acknowledged is not None and (
            bool(getattr(item, "acknowledged", False)) != self.acknowledged
        ):
            return False
        if self.source:
            value = str(getattr(item, "source", "") or "").casefold()
            if not any(part in value for part in self.source):
                return False
        if self.session:
            value = str(getattr(item, "session_id", "") or "").casefold()
            if not any(part in value for part in self.session):
                return False
        if self.run:
            value = str(getattr(item, "run_id", "") or "").casefold()
            if not any(part in value for part in self.run):
                return False
        if self.text:
            needle = self.text.casefold()
            haystack = (
                str(getattr(item, "title", "") or ""),
                str(getattr(item, "summary", "") or ""),
                str(getattr(item, "error", "") or ""),
                str(getattr(item, "source", "") or ""),
            )
            if not any(needle in field.casefold() for field in haystack):
                return False
        return True


def parse_search(value: str) -> SearchQuery:
    raw = (value or "").strip()
    if not raw:
        return SearchQuery()
    free: list[str] = []
    buckets: dict[str, list[str]] = {
        "status": [],
        "source": [],
        "priority": [],
        "session": [],
        "run": [],
    }
    acknowledged: bool | None = None
    for token in _TOKEN.findall(raw):
        if token.startswith('"') and token.endswith('"') and len(token) >= 2:
            free.append(token[1:-1])
            continue
        field, separator, value = token.partition(":")
        key = _FIELD_ALIASES.get(field.casefold())
        normalized = value.strip().strip('"').strip("'").casefold()
        if not separator or not normalized or key is None:
            free.append(token)
            continue
        if key == "status":
            status = _STATUS_ALIASES.get(normalized)
            if status is None:
                free.append(token)
                continue
            _append(buckets["status"], status)
        elif key == "priority":
            priority = _PRIORITY_ALIASES.get(normalized)
            if priority is None:
                free.append(token)
                continue
            _append(buckets["priority"], priority)
        elif key == "ack":
            if normalized in _ACK_TRUE:
                acknowledged = True
            elif normalized in _ACK_FALSE:
                acknowledged = False
            else:
                free.append(token)
        else:
            _append(buckets[key], normalized)
    return SearchQuery(
        text=" ".join(free).strip(),
        status=tuple(buckets["status"]),
        source=tuple(buckets["source"]),
        priority=tuple(buckets["priority"]),
        session=tuple(buckets["session"]),
        run=tuple(buckets["run"]),
        acknowledged=acknowledged,
    )


def _append(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)