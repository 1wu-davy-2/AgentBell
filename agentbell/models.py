from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal, Mapping
from urllib.parse import urlsplit

Status = Literal["succeeded", "failed", "canceled", "running"]
Priority = Literal["low", "normal", "high", "critical"]
ActionKind = Literal["open", "copy", "retry", "path", "center", "focus"]
PopupMode = Literal["corner", "center", "overlay"]
PopupSkin = Literal["midnight", "light", "ocean", "amber"]
OverlayAnchor = Literal[
    "center",
    "top",
    "bottom",
    "left",
    "right",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
]

STATUSES: tuple[Status, ...] = ("succeeded", "failed", "canceled", "running")
PRIORITIES: tuple[Priority, ...] = ("low", "normal", "high", "critical")
POPUP_MODES: tuple[PopupMode, ...] = ("corner", "center", "overlay")
POPUP_SKINS: tuple[PopupSkin, ...] = ("midnight", "light", "ocean", "amber")
OVERLAY_ANCHORS: tuple[OverlayAnchor, ...] = (
    "center",
    "top",
    "bottom",
    "left",
    "right",
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
)
OVERLAY_CARD_WIDTH_MIN = 240
OVERLAY_CARD_WIDTH_DEFAULT = 540
OVERLAY_CARD_WIDTH_MAX = 1600
OVERLAY_MARGIN_DEFAULT = 32
OVERLAY_MARGIN_MAX = 600
OVERLAY_OFFSET_LIMIT = 2000


def overlay_effective_margin(
    margin: int, screen_width: int, screen_height: int
) -> int:
    return max(
        0,
        min(
            margin,
            max(0, (screen_width - OVERLAY_CARD_WIDTH_MIN) // 2),
            max(0, (screen_height - 160) // 2),
        ),
    )


def overlay_anchor_origin(
    anchor: str,
    screen_width: int,
    screen_height: int,
    card_width: int,
    card_height: int,
    margin: int,
) -> tuple[int, int]:
    if anchor in {"left", "top_left", "bottom_left"}:
        x = margin
    elif anchor in {"right", "top_right", "bottom_right"}:
        x = screen_width - margin - card_width
    else:
        x = (screen_width - card_width) // 2
    if anchor in {"top", "top_left", "top_right"}:
        y = margin
    elif anchor in {"bottom", "bottom_left", "bottom_right"}:
        y = screen_height - margin - card_height
    else:
        y = (screen_height - card_height) // 2
    return x, y


def overlay_anchor_for_rect(
    screen_width: int,
    screen_height: int,
    card_x: int,
    card_y: int,
    card_width: int,
    card_height: int,
    margin: int,
    current_anchor: str | None = None,
) -> tuple[str, int, int]:
    """Map a free-form card position back to an anchor plus fine offsets."""
    max_x = max(0, screen_width - card_width)
    max_y = max(0, screen_height - card_height)
    x = max(0, min(card_x, max_x))
    y = max(0, min(card_y, max_y))
    best_anchor = "center"
    best_origin = (0, 0)
    best_score = float("inf")
    for anchor in OVERLAY_ANCHORS:
        origin = overlay_anchor_origin(
            anchor,
            screen_width,
            screen_height,
            card_width,
            card_height,
            margin,
        )
        score = abs(x - origin[0]) + abs(y - origin[1])
        if anchor == current_anchor:
            score -= 0.5
        if score < best_score:
            best_score = score
            best_anchor = anchor
            best_origin = origin
    offset_x = max(-OVERLAY_OFFSET_LIMIT, min(x - best_origin[0], OVERLAY_OFFSET_LIMIT))
    offset_y = max(-OVERLAY_OFFSET_LIMIT, min(y - best_origin[1], OVERLAY_OFFSET_LIMIT))
    return best_anchor, offset_x, offset_y

STATUS_LABELS: dict[str, str] = {
    "succeeded": "已完成",
    "failed": "失败",
    "canceled": "已取消",
    "running": "进行中",
}

PRIORITY_LABELS: dict[str, str] = {
    "low": "低",
    "normal": "普通",
    "high": "高",
    "critical": "紧急",
}

PRIORITY_RANK: dict[str, int] = {
    "low": 0,
    "normal": 1,
    "high": 2,
    "critical": 3,
}

POPUP_MODE_LABELS: dict[str, str] = {
    "corner": "右侧卡片",
    "center": "居中确认",
    "overlay": "全屏遮挡",
}

POPUP_SKIN_LABELS: dict[str, str] = {
    "midnight": "午夜蓝",
    "light": "晨光白",
    "ocean": "深海青",
    "amber": "琥珀暖",
}

OVERLAY_ANCHOR_LABELS: dict[str, str] = {
    "center": "居中",
    "top": "上方居中",
    "bottom": "下方居中",
    "left": "左侧居中",
    "right": "右侧居中",
    "top_left": "左上角",
    "top_right": "右上角",
    "bottom_left": "左下角",
    "bottom_right": "右下角",
}

DEFAULT_TEMPLATES: dict[str, str] = {
    "succeeded": "上一轮【{title}】已完成，请查看",
    "failed": "上一轮【{title}】执行失败",
    "canceled": "上一轮【{title}】已取消",
    "running": "上一轮【{title}】进行中",
}

_DURATION_PATTERN = re.compile(
    r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)s)?$"
)


def safe_http_url(value: str | None) -> str | None:
    """Return a trimmed http(s) URL, or None for anything else."""
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > 2048:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def safe_callback_url(value: str | None) -> str | None:
    """Only loopback callbacks are accepted for retry actions."""
    url = safe_http_url(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    if parsed.username or parsed.password:
        return None
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return None
    return url


def safe_local_path(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > 1024:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    return value


def duration_to_seconds(value: str) -> float | None:
    """Parse compact durations such as 8m30s, 90s or 1h2m into seconds."""
    text = (value or "").strip().lower()
    if not text:
        return None
    match = _DURATION_PATTERN.fullmatch(text)
    if match is None:
        return None
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else None


def default_priority(status: str) -> Priority:
    if status == "failed":
        return "high"
    if status == "running":
        return "low"
    return "normal"


@dataclass(frozen=True, slots=True)
class NotificationAction:
    kind: ActionKind
    label: str
    value: str = ""


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    title: str
    status: Status
    summary: str = ""
    duration: str = ""
    link: str | None = None
    error: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime | None = None
    priority: Priority = "normal"
    source: str = ""
    dedupe_key: str | None = None
    require_ack: bool = False
    silent: bool = False
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    occurrence_count: int = 1
    progress: int | None = None
    actions: tuple[NotificationAction, ...] = ()
    bypass_quiet_hours: bool = False
    auto_close_seconds: int | None = None
    expires_at: datetime | None = None
    rule_name: str = ""
    channel_types: tuple[str, ...] = ()
    popup_mode: PopupMode | None = None
    popup_skin: PopupSkin | None = None

    @property
    def effective_updated_at(self) -> datetime:
        return self.updated_at or self.received_at

    def headline_text(self, templates: Mapping[str, str] | None = None) -> str:
        source = templates or DEFAULT_TEMPLATES
        template = source.get(self.status) or DEFAULT_TEMPLATES.get(
            self.status, DEFAULT_TEMPLATES["succeeded"]
        )
        try:
            return template.format(title=self.title)
        except (KeyError, IndexError, ValueError):
            fallback = DEFAULT_TEMPLATES.get(
                self.status, DEFAULT_TEMPLATES["succeeded"]
            )
            return fallback.format(title=self.title)

    @property
    def headline(self) -> str:
        return self.headline_text()

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    @property
    def priority_label(self) -> str:
        return PRIORITY_LABELS.get(self.priority, self.priority)

    @property
    def needs_ack(self) -> bool:
        return self.require_ack and not self.acknowledged

    def is_expired(self, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or datetime.now().astimezone()
        return current >= self.expires_at.astimezone()

    def acknowledge(self, now: datetime | None = None) -> Notification:
        if self.acknowledged:
            return self
        current = now or datetime.now().astimezone()
        return replace(
            self,
            acknowledged=True,
            acknowledged_at=current,
            updated_at=current,
        )
