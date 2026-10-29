from __future__ import annotations

import logging
import os
import plistlib
import shlex
import subprocess
import sys
from pathlib import Path

from .paths import app_dir, entry_script

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
ENTRY_NAME = "AgentBell"
MAC_LABEL = "com.agentbell.app"


def _launch_args() -> list[str]:
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]

    python = Path(sys.executable)
    if os.name == "nt":
        pythonw = python.with_name("pythonw.exe")
        if pythonw.exists():
            python = pythonw
    return [str(python), str(entry_script())]


def _apply_windows(enabled: bool, args: list[str], logger: logging.Logger) -> None:
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            value = subprocess.list2cmdline(args)
            try:
                current, _ = winreg.QueryValueEx(key, ENTRY_NAME)
            except FileNotFoundError:
                current = None
            if current != value:
                winreg.SetValueEx(key, ENTRY_NAME, 0, winreg.REG_SZ, value)
                logger.info("已启用开机自启：%s", value)
        else:
            try:
                winreg.DeleteValue(key, ENTRY_NAME)
                logger.info("已关闭开机自启")
            except FileNotFoundError:
                pass


def _apply_macos(enabled: bool, args: list[str], logger: logging.Logger) -> None:
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{MAC_LABEL}.plist"
    if not enabled:
        if plist_path.exists():
            plist_path.unlink()
            logger.info("已关闭开机自启")
        return

    plist_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "Label": MAC_LABEL,
        "ProgramArguments": args,
        "WorkingDirectory": str(app_dir()),
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle)
    logger.info("已启用开机自启：%s", plist_path)


def _apply_linux(enabled: bool, args: list[str], logger: logging.Logger) -> None:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    desktop_path = config_home / "autostart" / "agentbell.desktop"
    if not enabled:
        if desktop_path.exists():
            desktop_path.unlink()
            logger.info("已关闭开机自启")
        return

    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(shlex.quote(arg) for arg in args)
    content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=AgentBell\n"
        "Comment=Local AI agent task notifications\n"
        f"Exec={exec_line}\n"
        f"Path={app_dir()}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
    )
    desktop_path.write_text(content, encoding="utf-8")
    logger.info("已启用开机自启：%s", desktop_path)


def configure_autostart(enabled: bool, logger: logging.Logger) -> bool:
    """Enable/disable login autostart for the current user. Never fatal."""
    args = _launch_args()
    try:
        if os.name == "nt":
            _apply_windows(enabled, args, logger)
        elif sys.platform == "darwin":
            _apply_macos(enabled, args, logger)
        else:
            _apply_linux(enabled, args, logger)
        return True
    except Exception as exc:  # pragma: no cover - platform specific failures
        logger.warning("配置开机自启失败：%s", exc)
        return False
