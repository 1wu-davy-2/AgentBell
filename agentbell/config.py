from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import (
    DEFAULT_TEMPLATES,
    OVERLAY_ANCHORS,
    OVERLAY_CARD_WIDTH_MAX,
    OVERLAY_CARD_WIDTH_MIN,
    OVERLAY_MARGIN_DEFAULT,
    OVERLAY_MARGIN_MAX,
    OVERLAY_OFFSET_LIMIT,
    POPUP_MODES,
    POPUP_SKINS,
    PRIORITIES,
    STATUSES,
    OverlayAnchor,
    PopupMode,
    PopupSkin,
    Priority,
    Status,
    safe_http_url,
)
from .updater import normalize_repo

DEFAULT_PORT = 8765
DEFAULT_AUTO_CLOSE_SECONDS = 30
MAX_AUTO_CLOSE_SECONDS = 3600
DEFAULT_HISTORY_LIMIT = 1000
DEFAULT_MEETING_PROCESSES = (
    "zoom.exe",
    "teams.exe",
    "wemeetapp.exe",
    "webexmta.exe",
)

_TIME_PATTERN = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9._-]{0,40}$")
_CHANNEL_TYPES = {"webhook", "ntfy", "bark", "telegram", "feishu", "wecom"}


class ConfigError(RuntimeError):
    """Raised when config.json cannot be read or contains invalid values."""


@dataclass(frozen=True, slots=True)
class QuietHoursConfig:
    enabled: bool = False
    start: str = "22:00"
    end: str = "08:00"
    allow_critical: bool = True


@dataclass(frozen=True, slots=True)
class HistoryConfig:
    enabled: bool = True
    limit: int = DEFAULT_HISTORY_LIMIT
    path: str = ""


@dataclass(frozen=True, slots=True)
class DigestConfig:
    enabled: bool = True
    threshold: int = 4
    window_seconds: int = 60


@dataclass(frozen=True, slots=True)
class EscalationConfig:
    unread_seconds: int = 0
    max_times: int = 2
    flash_tray: bool = True
    sound: bool = True


@dataclass(frozen=True, slots=True)
class AgentSessionsConfig:
    enabled: bool = True
    scan_interval_seconds: int = 120
    max_sessions: int = 80


@dataclass(frozen=True, slots=True)
class AgentLauncherConfig:
    recent_projects: tuple[str, ...] = ()
    last_agent: str = ""


@dataclass(frozen=True, slots=True)
class ToolchainConfig:
    npm_registry: str = "https://registry.npmjs.org"
    deepseek_key: str = ""


@dataclass(frozen=True, slots=True)
class UpdateConfig:
    enabled: bool = True
    repo: str = ""
    check_on_start: bool = True


@dataclass(frozen=True, slots=True)
class OverlayAreaConfig:
    anchor: OverlayAnchor = "center"
    width: int = 0
    offset_x: int = 0
    offset_y: int = 0
    margin: int = OVERLAY_MARGIN_DEFAULT


@dataclass(frozen=True, slots=True)
class RuleConfig:
    name: str = ""
    source: str = "*"
    title_contains: str | None = None
    status: Status | None = None
    priority: Priority | None = None
    silent: bool | None = None
    require_ack: bool | None = None
    auto_close_seconds: int | None = None
    bypass_quiet_hours: bool = False
    channels: tuple[str, ...] = ()
    popup_mode: PopupMode | None = None
    popup_skin: PopupSkin | None = None


@dataclass(frozen=True, slots=True)
class ChannelConfig:
    type: str = "webhook"
    enabled: bool = True
    when_away: bool = True
    min_priority: Priority = "high"
    url: str = ""
    topic: str = ""
    token: str = ""
    chat_id: str = ""
    device_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppConfig:
    port: int = DEFAULT_PORT
    token: str = ""
    auto_close_seconds: int = DEFAULT_AUTO_CLOSE_SECONDS
    autostart: bool = False
    open_center_on_start: bool = True
    onboarding_seen: bool = False
    instance_name: str = ""
    history: HistoryConfig = field(default_factory=HistoryConfig)
    quiet_hours: QuietHoursConfig = field(default_factory=QuietHoursConfig)
    suppress_fullscreen: bool = True
    meeting_processes: tuple[str, ...] = DEFAULT_MEETING_PROCESSES
    success_popup: bool = True
    require_ack_by_default: bool = False
    popup_cooldown_seconds: int = 15
    digest: DigestConfig = field(default_factory=DigestConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    hotkey: str = "Ctrl+Alt+A"
    sounds: dict[str, str] = field(
        default_factory=lambda: {
            "succeeded": "",
            "failed": "",
            "canceled": "",
            "running": "",
            "critical": "",
        }
    )
    templates: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_TEMPLATES)
    )
    rules: tuple[RuleConfig, ...] = ()
    channels: tuple[ChannelConfig, ...] = ()
    away_idle_seconds: int = 300
    allow_local_paths: bool = False
    presence_poll_seconds: int = 5
    popup_mode: PopupMode = "corner"
    popup_skin: PopupSkin = "midnight"
    overlay_image: str = ""
    overlay_area: OverlayAreaConfig = field(default_factory=OverlayAreaConfig)
    hold_when_locked: bool = True
    agent_sessions: AgentSessionsConfig = field(
        default_factory=AgentSessionsConfig
    )
    agent_launcher: AgentLauncherConfig = field(
        default_factory=AgentLauncherConfig
    )
    toolchain: ToolchainConfig = field(default_factory=ToolchainConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)

    @property
    def auth_enabled(self) -> bool:
        return bool(self.token)


def _read_int(data: dict[str, Any], key: str, default: int, minimum: int, maximum: int) -> int:
    raw = data.get(key, default)
    if isinstance(raw, bool):
        raise ConfigError(f'"{key}" 必须是整数，不能是布尔值')
    if isinstance(raw, str):
        try:
            raw = int(raw.strip())
        except ValueError as exc:
            raise ConfigError(f'"{key}" 必须是整数') from exc
    if not isinstance(raw, int):
        raise ConfigError(f'"{key}" 必须是整数')
    if not minimum <= raw <= maximum:
        raise ConfigError(f'"{key}" 必须在 {minimum} 到 {maximum} 之间')
    return raw


def _read_optional_int(
    data: dict[str, Any], key: str, minimum: int, maximum: int
) -> int | None:
    if data.get(key) is None:
        return None
    return _read_int(data, key, minimum, minimum, maximum)


def _read_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    raw = data.get(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
        return raw.strip().lower() == "true"
    raise ConfigError(f'"{key}" 必须是 true 或 false')


def _read_optional_bool(data: dict[str, Any], key: str) -> bool | None:
    if data.get(key) is None:
        return None
    return _read_bool(data, key, False)


def _read_str(
    data: dict[str, Any],
    key: str,
    default: str = "",
    maximum: int = 200,
    *,
    strip: bool = True,
) -> str:
    raw = data.get(key, default)
    if raw is None:
        return default
    if not isinstance(raw, str):
        raise ConfigError(f'"{key}" 必须是字符串')
    value = raw.strip() if strip else raw
    if len(value) > maximum:
        raise ConfigError(f'"{key}" 不能超过 {maximum} 个字符')
    return value


def _read_optional_str(
    data: dict[str, Any], key: str, maximum: int = 200
) -> str | None:
    if data.get(key) is None:
        return None
    value = _read_str(data, key, "", maximum)
    return value or None


def _read_token(data: dict[str, Any]) -> str:
    raw = data.get("token", "")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ConfigError('"token" 必须是字符串')
    return raw


def _read_time(data: dict[str, Any], key: str, default: str) -> str:
    value = _read_str(data, key, default, 5)
    if not _TIME_PATTERN.fullmatch(value):
        raise ConfigError(f'"{key}" 必须是 HH:MM 格式，例如 22:00')
    return value


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    raw = data.get(key, {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f'"{key}" 必须是 JSON 对象')
    return raw


def _read_str_list(
    data: dict[str, Any],
    key: str,
    default: tuple[str, ...],
    *,
    maximum_items: int = 20,
    maximum_length: int = 80,
) -> tuple[str, ...]:
    raw = data.get(key, list(default))
    if raw is None:
        return default
    if not isinstance(raw, (list, tuple)):
        raise ConfigError(f'"{key}" 必须是字符串数组')
    if len(raw) > maximum_items:
        raise ConfigError(f'"{key}" 最多包含 {maximum_items} 项')
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ConfigError(f'"{key}" 必须是字符串数组')
        value = item.strip()
        if not value:
            continue
        if len(value) > maximum_length:
            raise ConfigError(
                f'"{key}" 的每一项不能超过 {maximum_length} 个字符'
            )
        values.append(value)
    return tuple(values)


def _read_priority(data: dict[str, Any], key: str, default: str = "high") -> Priority:
    value = _read_str(data, key, default, 20).lower()
    if value not in PRIORITIES:
        raise ConfigError(f'"{key}" 必须是 {" / ".join(PRIORITIES)}')
    return value  # type: ignore[return-value]


def _read_optional_priority(data: dict[str, Any], key: str) -> Priority | None:
    if data.get(key) is None:
        return None
    return _read_priority(data, key)


def _read_optional_status(data: dict[str, Any], key: str) -> Status | None:
    if data.get(key) is None:
        return None
    value = _read_str(data, key, "", 20).lower()
    if value not in STATUSES:
        raise ConfigError(f'"{key}" 必须是 {" / ".join(STATUSES)}')
    return value  # type: ignore[return-value]


def _read_popup_mode(
    data: dict[str, Any], key: str, default: str = "corner"
) -> PopupMode:
    value = _read_str(data, key, default, 20).lower()
    if value not in POPUP_MODES:
        raise ConfigError(f'"{key}" 必须是 {" / ".join(POPUP_MODES)}')
    return value  # type: ignore[return-value]


def _read_optional_popup_mode(
    data: dict[str, Any], key: str
) -> PopupMode | None:
    if data.get(key) is None:
        return None
    return _read_popup_mode(data, key)


def _read_popup_skin(
    data: dict[str, Any], key: str, default: str = "midnight"
) -> PopupSkin:
    value = _read_str(data, key, default, 20).lower()
    if value not in POPUP_SKINS:
        raise ConfigError(f'"{key}" 必须是 {" / ".join(POPUP_SKINS)}')
    return value  # type: ignore[return-value]


def _read_optional_popup_skin(
    data: dict[str, Any], key: str
) -> PopupSkin | None:
    if data.get(key) is None:
        return None
    return _read_popup_skin(data, key)


def _read_overlay_area(data: dict[str, Any]) -> OverlayAreaConfig:
    section = _section(data, "overlay_area")
    anchor = _read_str(section, "anchor", "center", 20).lower()
    if anchor not in OVERLAY_ANCHORS:
        raise ConfigError(
            f'"overlay_area.anchor" 必须是 {" / ".join(OVERLAY_ANCHORS)}'
        )

    def _int(key: str, default: int, minimum: int, maximum: int) -> int:
        raw = section.get(key, default)
        if isinstance(raw, bool):
            raise ConfigError(f'"overlay_area.{key}" 必须是整数')
        if isinstance(raw, str):
            try:
                raw = int(raw.strip())
            except ValueError as exc:
                raise ConfigError(f'"overlay_area.{key}" 必须是整数') from exc
        if not isinstance(raw, int):
            raise ConfigError(f'"overlay_area.{key}" 必须是整数')
        if not minimum <= raw <= maximum:
            raise ConfigError(
                f'"overlay_area.{key}" 必须在 {minimum} 到 {maximum} 之间'
            )
        return raw

    width = _int("width", 0, 0, OVERLAY_CARD_WIDTH_MAX)
    if width and width < OVERLAY_CARD_WIDTH_MIN:
        raise ConfigError(
            f'"overlay_area.width" 必须为 0（默认）或 '
            f"{OVERLAY_CARD_WIDTH_MIN} 到 {OVERLAY_CARD_WIDTH_MAX}"
        )
    return OverlayAreaConfig(
        anchor=anchor,  # type: ignore[arg-type]
        width=width,
        offset_x=_int("offset_x", 0, -OVERLAY_OFFSET_LIMIT, OVERLAY_OFFSET_LIMIT),
        offset_y=_int("offset_y", 0, -OVERLAY_OFFSET_LIMIT, OVERLAY_OFFSET_LIMIT),
        margin=_int("margin", OVERLAY_MARGIN_DEFAULT, 0, OVERLAY_MARGIN_MAX),
    )


def _read_agent_sessions(data: dict[str, Any]) -> AgentSessionsConfig:
    section = _section(data, "agent_sessions")
    return AgentSessionsConfig(
        enabled=_read_bool(section, "enabled", True),
        scan_interval_seconds=_read_int(
            section, "scan_interval_seconds", 120, 30, 3600
        ),
        max_sessions=_read_int(section, "max_sessions", 80, 10, 500),
    )


def _read_agent_launcher(data: dict[str, Any]) -> AgentLauncherConfig:
    section = _section(data, "agent_launcher")
    return AgentLauncherConfig(
        recent_projects=_read_str_list(
            section,
            "recent_projects",
            (),
            maximum_items=6,
            maximum_length=260,
        ),
        last_agent=_read_str(section, "last_agent", "", 60),
    )


def _read_toolchain(data: dict[str, Any]) -> ToolchainConfig:
    section = _section(data, "toolchain")
    registry = _read_str(
        section, "npm_registry", "https://registry.npmjs.org", 200
    ).rstrip("/")
    if registry and not registry.startswith("https://"):
        raise ConfigError('"toolchain.npm_registry" 必须是 HTTPS 地址')
    return ToolchainConfig(
        npm_registry=registry or "https://registry.npmjs.org",
        deepseek_key=_read_str(section, "deepseek_key", "", 2048),
    )


def _read_update(data: dict[str, Any]) -> UpdateConfig:
    section = _section(data, "update")
    repo_text = _read_str(section, "repo", "", 120)
    repo = normalize_repo(repo_text)
    if repo_text and not repo:
        raise ConfigError(
            '"update.repo" 必须是 GitHub 仓库，例如 owner/AgentBell'
        )
    return UpdateConfig(
        enabled=_read_bool(section, "enabled", True),
        repo=repo,
        check_on_start=_read_bool(section, "check_on_start", True),
    )


def _read_history(data: dict[str, Any]) -> HistoryConfig:
    section = _section(data, "history")
    return HistoryConfig(
        enabled=_read_bool(section, "enabled", True),
        limit=_read_int(section, "limit", DEFAULT_HISTORY_LIMIT, 50, 10000),
        path=_read_str(section, "path", "", 260),
    )


def _read_quiet_hours(data: dict[str, Any]) -> QuietHoursConfig:
    section = _section(data, "quiet_hours")
    return QuietHoursConfig(
        enabled=_read_bool(section, "enabled", False),
        start=_read_time(section, "start", "22:00"),
        end=_read_time(section, "end", "08:00"),
        allow_critical=_read_bool(section, "allow_critical", True),
    )


def _read_digest(data: dict[str, Any]) -> DigestConfig:
    section = _section(data, "digest")
    return DigestConfig(
        enabled=_read_bool(section, "enabled", True),
        threshold=_read_int(section, "threshold", 4, 2, 50),
        window_seconds=_read_int(section, "window_seconds", 60, 5, 3600),
    )


def _read_escalation(data: dict[str, Any]) -> EscalationConfig:
    section = _section(data, "escalation")
    return EscalationConfig(
        unread_seconds=_read_int(section, "unread_seconds", 0, 0, 86400),
        max_times=_read_int(section, "max_times", 2, 0, 20),
        flash_tray=_read_bool(section, "flash_tray", True),
        sound=_read_bool(section, "sound", True),
    )


def _read_sounds(data: dict[str, Any]) -> dict[str, str]:
    section = _section(data, "sounds")
    sounds = {
        "succeeded": "",
        "failed": "",
        "canceled": "",
        "running": "",
        "critical": "",
    }
    for key in sounds:
        if key in section:
            sounds[key] = _read_str(section, key, "", 260)
    return sounds


def _read_templates(data: dict[str, Any]) -> dict[str, str]:
    section = _section(data, "templates")
    templates = dict(DEFAULT_TEMPLATES)
    for key in templates:
        if key not in section:
            continue
        value = _read_str(section, key, templates[key], 300)
        if "{title}" not in value:
            raise ConfigError(f'"templates.{key}" 必须包含 {{title}} 占位符')
        try:
            value.format(title="示例")
        except (KeyError, IndexError, ValueError) as exc:
            raise ConfigError(f'"templates.{key}" 格式无效：{exc}') from exc
        templates[key] = value
    return templates


def _read_rules(data: dict[str, Any]) -> tuple[RuleConfig, ...]:
    raw = data.get("rules", [])
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ConfigError('"rules" 必须是 JSON 数组')
    if len(raw) > 50:
        raise ConfigError('"rules" 最多包含 50 条规则')
    rules: list[RuleConfig] = []
    for index, item in enumerate(raw):
        label = f"rules[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f'"{label}" 必须是 JSON 对象')
        name = _read_str(item, "name", f"规则 {index + 1}", 80)
        source = _read_str(item, "source", "*", 100) or "*"
        title_contains = _read_optional_str(item, "title_contains", 100)
        status = _read_optional_status(item, "status")
        priority = _read_optional_priority(item, "priority")
        silent = _read_optional_bool(item, "silent")
        require_ack = _read_optional_bool(item, "require_ack")
        auto_close_seconds = _read_optional_int(
            item, "auto_close_seconds", 0, MAX_AUTO_CLOSE_SECONDS
        )
        bypass = _read_bool(item, "bypass_quiet_hours", False)
        popup_mode = _read_optional_popup_mode(item, "popup_mode")
        popup_skin = _read_optional_popup_skin(item, "popup_skin")
        channel_types = _read_str_list(
            item,
            "channels",
            (),
            maximum_items=10,
            maximum_length=20,
        )
        for channel_type in channel_types:
            if channel_type not in _CHANNEL_TYPES:
                raise ConfigError(
                    f'"{label}.channels" 包含未知渠道：{channel_type}'
                )
        rules.append(
            RuleConfig(
                name=name,
                source=source,
                title_contains=title_contains,
                status=status,
                priority=priority,
                silent=silent,
                require_ack=require_ack,
                auto_close_seconds=auto_close_seconds,
                bypass_quiet_hours=bypass,
                channels=channel_types,
                popup_mode=popup_mode,
                popup_skin=popup_skin,
            )
        )
    return tuple(rules)


def _validate_headers(raw: Any, label: str) -> dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(f'"{label}.headers" 必须是 JSON 对象')
    headers: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ConfigError(f'"{label}.headers" 的键和值必须是字符串')
        if any(char in key + value for char in "\r\n\0"):
            raise ConfigError(f'"{label}.headers" 不能包含换行或空字符')
        if len(key) > 100 or len(value) > 500:
            raise ConfigError(f'"{label}.headers" 过长')
        headers[key] = value
    return headers


def _read_channels(data: dict[str, Any]) -> tuple[ChannelConfig, ...]:
    raw = data.get("channels", [])
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ConfigError('"channels" 必须是 JSON 数组')
    if len(raw) > 20:
        raise ConfigError('"channels" 最多包含 20 个渠道')
    channels: list[ChannelConfig] = []
    for index, item in enumerate(raw):
        label = f"channels[{index}]"
        if not isinstance(item, dict):
            raise ConfigError(f'"{label}" 必须是 JSON 对象')
        channel_type = _read_str(item, "type", "", 20).lower()
        if channel_type not in _CHANNEL_TYPES:
            raise ConfigError(
                f'"{label}.type" 必须是 {" / ".join(sorted(_CHANNEL_TYPES))}'
            )
        url = _read_str(item, "url", "", 2048)
        topic = _read_str(item, "topic", "", 200)
        token = _read_str(item, "token", "", 500, strip=False)
        chat_id = _read_str(item, "chat_id", "", 100)
        device_key = _read_str(item, "device_key", "", 200)
        headers = _validate_headers(item.get("headers"), label)

        if channel_type in {"webhook", "feishu", "wecom"} and not safe_http_url(url):
            raise ConfigError(f'"{label}.url" 必须是 http/https 链接')
        if channel_type == "ntfy":
            topic = topic or _read_str(item, "topic", "", 200)
            if not topic:
                raise ConfigError(f'"{label}.topic" 不能为空')
            url = url or "https://ntfy.sh"
            if not safe_http_url(url):
                raise ConfigError(f'"{label}.url" 必须是 http/https 链接')
        if channel_type == "bark":
            if not device_key:
                raise ConfigError(f'"{label}.device_key" 不能为空')
            url = url or "https://api.day.app"
            if not safe_http_url(url):
                raise ConfigError(f'"{label}.url" 必须是 http/https 链接')
        if channel_type == "telegram":
            if not token or not chat_id:
                raise ConfigError(
                    f'"{label}" 配置 Telegram 时必须提供 bot token 和 chat_id'
                )

        channels.append(
            ChannelConfig(
                type=channel_type,
                enabled=_read_bool(item, "enabled", True),
                when_away=_read_bool(item, "when_away", True),
                min_priority=_read_priority(item, "min_priority", "high"),
                url=url,
                topic=topic,
                token=token,
                chat_id=chat_id,
                device_key=device_key,
                headers=headers,
            )
        )
    return tuple(channels)


def _read_instance_name(data: dict[str, Any]) -> str:
    name = _read_str(data, "instance_name", "", 40)
    if not _INSTANCE_PATTERN.fullmatch(name):
        raise ConfigError(
            '"instance_name" 只能包含字母、数字、点、下划线和短横线'
        )
    return name


def _parse_config(data: dict[str, Any]) -> AppConfig:
    return AppConfig(
        port=_read_int(data, "port", DEFAULT_PORT, 1, 65535),
        token=_read_token(data),
        auto_close_seconds=_read_int(
            data,
            "auto_close_seconds",
            DEFAULT_AUTO_CLOSE_SECONDS,
            0,
            MAX_AUTO_CLOSE_SECONDS,
        ),
        autostart=_read_bool(data, "autostart", False),
        open_center_on_start=_read_bool(data, "open_center_on_start", True),
        onboarding_seen=_read_bool(data, "onboarding_seen", False),
        instance_name=_read_instance_name(data),
        history=_read_history(data),
        quiet_hours=_read_quiet_hours(data),
        suppress_fullscreen=_read_bool(data, "suppress_fullscreen", True),
        meeting_processes=_read_str_list(
            data,
            "meeting_processes",
            DEFAULT_MEETING_PROCESSES,
            maximum_items=20,
            maximum_length=80,
        ),
        success_popup=_read_bool(data, "success_popup", True),
        require_ack_by_default=_read_bool(data, "require_ack_by_default", False),
        popup_cooldown_seconds=_read_int(
            data, "popup_cooldown_seconds", 15, 0, 3600
        ),
        digest=_read_digest(data),
        escalation=_read_escalation(data),
        hotkey=_read_str(data, "hotkey", "Ctrl+Alt+A", 50),
        sounds=_read_sounds(data),
        templates=_read_templates(data),
        rules=_read_rules(data),
        channels=_read_channels(data),
        away_idle_seconds=_read_int(data, "away_idle_seconds", 300, 0, 86400),
        allow_local_paths=_read_bool(data, "allow_local_paths", False),
        presence_poll_seconds=_read_int(
            data, "presence_poll_seconds", 5, 1, 60
        ),
        popup_mode=_read_popup_mode(data, "popup_mode", "corner"),
        popup_skin=_read_popup_skin(data, "popup_skin", "midnight"),
        overlay_image=_read_str(data, "overlay_image", "", 1024),
        overlay_area=_read_overlay_area(data),
        hold_when_locked=_read_bool(data, "hold_when_locked", True),
        agent_sessions=_read_agent_sessions(data),
        agent_launcher=_read_agent_launcher(data),
        toolchain=_read_toolchain(data),
        update=_read_update(data),
    )


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    """Validate a JSON config mapping without touching disk."""
    if not isinstance(data, dict):
        raise ConfigError("配置的顶层必须是 JSON 对象")
    return _parse_config(data)


def config_to_dict(config: AppConfig) -> dict[str, Any]:
    return asdict(config)


def save_config(path: Path, config: AppConfig) -> None:
    payload = json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.tmp")
        temp_path.write_text(payload, encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        raise ConfigError(f"无法写入配置文件 {path}：{exc}") from exc


def load_config(path: Path) -> tuple[AppConfig, bool]:
    """Load config.json, creating it with defaults on first run.

    Returns (config, was_created). Invalid configuration raises ConfigError so the
    app fails closed instead of silently running without the expected token.
    """
    if not path.exists():
        config = AppConfig()
        save_config(path, config)
        return config, True

    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}：{exc}") from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"config.json 格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}"
        ) from exc

    if not isinstance(data, dict):
        raise ConfigError("config.json 的顶层必须是 JSON 对象")

    return _parse_config(data), False
