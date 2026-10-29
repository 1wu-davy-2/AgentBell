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


def entry_script() -> Path:
    return app_dir() / "run.py"
