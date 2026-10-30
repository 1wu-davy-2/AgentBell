from __future__ import annotations

import sys
from pathlib import Path


def app_dir() -> Path:
    """Directory that owns config.json and logs/ (portable, beside the exe)."""
    if getattr(sys, "frozen", False):
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


def runtime_dir() -> Path:
    """Portable toolchain (Node, npm agents, cc-switch) beside config.json."""
    return app_dir() / "runtime"


def entry_script() -> Path:
    return app_dir() / "run.py"
