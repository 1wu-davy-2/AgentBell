from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta

from .config import AppConfig, QuietHoursConfig, RuleConfig
from .models import PRIORITY_RANK, Notification


@dataclass(frozen=True, slots=True)
class Presence:
    away: bool = False
    fullscreen: bool = False
    meeting_process: str = ""
    idle_seconds: float = 0.0
    locked: bool = False

    @property
    def suppression_reason(self) -> str:
        if self.locked:
            return "locked"
        if self.fullscreen:
            return "fullscreen"
        if self.meeting_process:
            return "meeting"
        return ""


@dataclass(frozen=True, slots=True)
class Decision:
    notification: Notification
    popup: bool
    defer_reason: str = ""
    channel_types: tuple[str, ...] = ()


def _matches(notification: Notification, rule: RuleConfig) -> bool:
    pattern = (rule.source or "*").lower()
    if pattern not in {"", "*"} and not fnmatch.fnmatchcase(
        (notification.source or "").lower(), pattern
    ):
        return False
    if rule.title_contains and rule.title_contains.lower() not in (
        notification.title.lower()
    ):
        return False
    if rule.status and rule.status != notification.status:
        return False
    return True


def apply_rules(
    notification: Notification, rules: tuple[RuleConfig, ...]
) -> Notification:
    """Apply every matching rule in order; later rules win on scalar fields."""
    if not rules:
        return notification
    matched: list[str] = []
    priority = notification.priority
    silent = notification.silent
    require_ack = notification.require_ack
    auto_close = notification.auto_close_seconds
    bypass = notification.bypass_quiet_hours
    channels = list(notification.channel_types)
    popup_mode = notification.popup_mode
    popup_skin = notification.popup_skin
    for rule in rules:
        if not _matches(notification, rule):
            continue
        matched.append(rule.name or "未命名规则")
        if rule.priority is not None:
            priority = rule.priority
        if rule.silent is not None:
            silent = rule.silent
        if rule.require_ack is not None:
            require_ack = rule.require_ack
        if rule.auto_close_seconds is not None:
            auto_close = rule.auto_close_seconds
        if rule.bypass_quiet_hours:
            bypass = True
        if rule.popup_mode is not None:
            popup_mode = rule.popup_mode
        if rule.popup_skin is not None:
            popup_skin = rule.popup_skin
        for channel_type in rule.channels:
            if channel_type not in channels:
                channels.append(channel_type)
    if not matched:
        return notification
    return replace(
        notification,
        priority=priority,
        silent=silent,
        require_ack=require_ack,
        auto_close_seconds=auto_close,
        bypass_quiet_hours=bypass,
        channel_types=tuple(channels),
        rule_name=", ".join(matched),
        popup_mode=popup_mode,
        popup_skin=popup_skin,
    )


def parse_hhmm(value: str, fallback: str = "00:00") -> time:
    for candidate in (value, fallback):
        try:
            hours, minutes = (int(part) for part in candidate.split(":", 1))
            return time(hour=hours, minute=minutes)
        except (ValueError, TypeError):
            continue
    return time(0, 0)


def in_quiet_hours(quiet: QuietHoursConfig, now: datetime | None = None) -> bool:
    if not quiet.enabled:
        return False
    current = (now or datetime.now().astimezone()).time()
    start = parse_hhmm(quiet.start, "22:00")
    end = parse_hhmm(quiet.end, "08:00")
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def quiet_hours_end(quiet: QuietHoursConfig, now: datetime | None = None) -> datetime:
    current = now or datetime.now().astimezone()
    if not quiet.enabled:
        return current
    end = parse_hhmm(quiet.end, "08:00")
    candidate = current.replace(
        hour=end.hour, minute=end.minute, second=0, microsecond=0
    )
    if candidate <= current:
        candidate += timedelta(days=1)
    return candidate


def _should_popup(notification: Notification, config: AppConfig) -> bool:
    if notification.silent:
        return False
    priority = notification.priority
    if notification.status == "running":
        return priority in {"high", "critical"}
    if notification.status == "succeeded":
        return config.success_popup or priority in {"high", "critical"}
    if notification.status == "canceled":
        return priority != "low" or notification.require_ack
    return True


def resolve_channels(
    notification: Notification,
    config: AppConfig,
    presence: Presence,
) -> tuple[str, ...]:
    allowed = (
        set(notification.channel_types) if notification.channel_types else None
    )
    selected: list[str] = []
    for channel in config.channels:
        if not channel.enabled:
            continue
        if allowed is not None and channel.type not in allowed:
            continue
        if PRIORITY_RANK.get(notification.priority, 1) < PRIORITY_RANK.get(
            channel.min_priority, 2
        ):
            continue
        if channel.when_away and not presence.away:
            continue
        selected.append(channel.type)
    return tuple(selected)


def decide(
    notification: Notification,
    config: AppConfig,
    presence: Presence | None = None,
    now: datetime | None = None,
) -> Decision:
    current = now or datetime.now().astimezone()
    presence = presence or Presence()
    popup = _should_popup(notification, config)
    defer_reason = ""

    if popup and not notification.bypass_quiet_hours:
        if in_quiet_hours(config.quiet_hours, current) and not (
            config.quiet_hours.allow_critical
            and notification.priority == "critical"
        ):
            defer_reason = "quiet_hours"
        elif config.hold_when_locked and presence.locked:
            defer_reason = "locked"
        elif config.suppress_fullscreen and presence.fullscreen:
            defer_reason = "fullscreen"
        elif presence.meeting_process:
            defer_reason = "meeting"

    if defer_reason:
        popup = False

    popup_mode = notification.popup_mode or config.popup_mode
    popup_skin = notification.popup_skin or config.popup_skin

    require_ack = notification.require_ack or (
        config.require_ack_by_default and popup
    )
    if notification.priority == "critical":
        require_ack = True
    if popup and popup_mode == "center":
        require_ack = True

    auto_close = notification.auto_close_seconds
    if auto_close is None:
        auto_close = config.auto_close_seconds
    if require_ack or notification.status == "running":
        auto_close = 0
    elif popup_mode in {"center", "overlay"}:
        auto_close = 0

    resolved = replace(
        notification,
        require_ack=require_ack,
        auto_close_seconds=auto_close,
        popup_mode=popup_mode,
        popup_skin=popup_skin,
    )
    return Decision(
        notification=resolved,
        popup=popup,
        defer_reason=defer_reason,
        channel_types=resolve_channels(resolved, config, presence),
    )
