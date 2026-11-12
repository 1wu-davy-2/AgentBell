from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory that owns config.json and logs/."""
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            # The bundle in /Applications is read-only for config and updates.
            return Path.home() / "Library" / "Application Support" / "AgentBell"
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_file() -> Path:
    return app_dir() / "config.json"


def logs_dir() -> Path:
    return app_dir() / "logs"


def chat_dir() -> Path:
    """Default project folder for Agent launches (created beside config.json)."""
    return app_dir() / "chat"


def ensure_chat_dir() -> Path:
    path = chat_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_project_dir() -> Path:
    """chat/ when it exists, otherwise the install directory itself."""
    path = chat_dir()
    return path if path.is_dir() else app_dir()


def updates_dir() -> Path:
    return app_dir() / "updates"


def usage_db(config_path: Path | None = None) -> Path:
    """Persistent ledger for usage reported over HTTP/MCP."""
    base = config_path.parent if config_path is not None else app_dir()
    return base / "usage.sqlite3"


def runtime_dir() -> Path:
    """Portable Node and npm agents beside config.json."""
    return app_dir() / "runtime"


def entry_script() -> Path:
    return app_dir() / "run.py"
