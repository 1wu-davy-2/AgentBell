from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_PORT = 8765
DEFAULT_AUTO_CLOSE_SECONDS = 30
MAX_AUTO_CLOSE_SECONDS = 3600


class ConfigError(RuntimeError):
    """Raised when config.json cannot be read or contains invalid values."""


@dataclass(frozen=True, slots=True)
class AppConfig:
    port: int = DEFAULT_PORT
    token: str = ""
    auto_close_seconds: int = DEFAULT_AUTO_CLOSE_SECONDS
    autostart: bool = False

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


def _read_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    raw = data.get(key, default)
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
        return raw.strip().lower() == "true"
    raise ConfigError(f'"{key}" 必须是 true 或 false')


def _read_token(data: dict[str, Any]) -> str:
    raw = data.get("token", "")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ConfigError('"token" 必须是字符串')
    return raw


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
    )


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
