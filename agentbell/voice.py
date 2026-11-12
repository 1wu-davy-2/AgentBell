from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .models import PRIORITY_RANK, STATUS_LABELS, Notification

_FALLBACK_TEMPLATE = "{title}，{status_label}"
_SUMMARY_SEPARATOR = "。"
_SENTENCE_END = "，。！？；：、,.!?;:"
_RATE_MIN = -10
_RATE_MAX = 10
_WINDOWS_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Rate={rate}; "
    "$s.Speak([IO.File]::ReadAllText($args[0]))"
)
_CREATION_FLAGS = (
    getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
)


@dataclass(frozen=True, slots=True)
class VoiceSettings:
    enabled: bool = False
    min_priority: str = "normal"
    rate: int = 0
    include_summary: bool = True
    max_chars: int = 120
    template: str = "{title}，{status_label}"


def _clamp_rate(rate: int) -> int:
    try:
        value = int(rate)
    except (TypeError, ValueError):
        return 0
    return max(_RATE_MIN, min(value, _RATE_MAX))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> str:
    if limit <= 0 or len(text) <= limit:
        return text
    if limit == 1:
        return "…"
    return f"{text[: limit - 1].rstrip()}…"


def _append_summary(text: str, summary: str) -> str:
    if not text:
        return summary
    separator = "" if text[-1] in _SENTENCE_END else _SUMMARY_SEPARATOR
    return f"{text}{separator}{summary}"


def format_voice_text(
    notification: Notification, settings: VoiceSettings
) -> str:
    fields = {
        "title": notification.title,
        "status_label": STATUS_LABELS.get(notification.status, notification.status),
        "duration": notification.duration,
        "source": notification.source,
        "summary": notification.summary,
    }
    template = settings.template or _FALLBACK_TEMPLATE
    try:
        text = template.format_map(fields)
    except (KeyError, IndexError, ValueError, TypeError, AttributeError):
        template = _FALLBACK_TEMPLATE
        text = _FALLBACK_TEMPLATE.format_map(fields)

    summary = (notification.summary or "").strip()
    if settings.include_summary and summary and "{summary}" not in template:
        text = _append_summary(text, summary)

    return _truncate(_normalize(text), settings.max_chars)


def _resolve_platform(platform_name: str | None) -> str:
    if not platform_name:
        if os.name == "nt":
            return "windows"
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform == "darwin":
            return "macos"
        return sys.platform
    name = platform_name.strip().lower()
    if name.startswith("win"):
        return "windows"
    if name.startswith("linux"):
        return "linux"
    if name in {"darwin", "macos", "mac", "osx"}:
        return "macos"
    return name


def _write_text(text: str) -> Path | None:
    try:
        descriptor, raw_path = tempfile.mkstemp(
            prefix="agentbell-voice-", suffix=".txt"
        )
    except OSError:
        return None
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError:
        _unlink(path)
        return None
    return path


def _unlink(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def build_command(
    text: str,
    settings: VoiceSettings,
    platform_name: str | None = None,
    which: Callable[[str], str | None] | None = None,
) -> tuple[list[str], Path] | None:
    body = _normalize(text or "")
    if not body:
        return None
    finder = which or shutil.which
    platform = _resolve_platform(platform_name)
    rate = _clamp_rate(settings.rate)

    if platform == "windows":
        engine = finder("powershell") or finder("pwsh")
        if not engine:
            return None
        command = [
            engine,
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            _WINDOWS_SCRIPT.format(rate=rate),
        ]
    elif platform == "macos":
        engine = finder("say")
        if not engine:
            return None
        command = [engine, "-r", str(200 + rate * 15), "-f"]
    else:
        engine = finder("spd-say")
        if engine:
            command = [engine, "-r", str(rate * 10), "-f"]
        else:
            engine = finder("espeak-ng") or finder("espeak")
            if not engine:
                return None
            command = [engine, "-s", str(175 + rate * 10), "-f"]

    path = _write_text(body)
    if path is None:
        return None
    return [*command, str(path)], path


def _should_skip(notification: Notification, settings: VoiceSettings) -> bool:
    if not settings.enabled:
        return True
    if notification.silent and not notification.needs_ack:
        return True
    minimum = PRIORITY_RANK.get(settings.min_priority, PRIORITY_RANK["normal"])
    if PRIORITY_RANK.get(notification.priority, PRIORITY_RANK["normal"]) < minimum:
        return True
    if notification.status == "running" and not notification.needs_input:
        return True
    return False


def _terminate(process: subprocess.Popen[bytes] | None) -> None:
    if process is None:
        return
    try:
        process.terminate()
    except (OSError, subprocess.SubprocessError):
        pass


class VoicePlayer:
    def __init__(
        self,
        settings_provider: Callable[[], VoiceSettings],
        logger: logging.Logger,
        *,
        popen: Callable[..., subprocess.Popen[bytes]] | None = None,
        platform_name: str | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> None:
        self._settings_provider = settings_provider
        self._logger = logger
        self._popen = popen
        self._platform_name = platform_name
        self._which = which
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._thread: threading.Thread | None = None

    def speak(self, notification: Notification) -> bool:
        try:
            settings = self._settings_provider()
        except Exception as exc:
            self._logger.warning("读取语音播报设置失败：%s", exc)
            return False
        if _should_skip(notification, settings):
            return False
        try:
            text = format_voice_text(notification, settings)
            built = build_command(
                text, settings, platform_name=self._platform_name, which=self._which
            )
        except Exception as exc:
            self._logger.warning("准备语音播报失败：%s", exc)
            return False
        if built is None:
            self._logger.warning("未找到可用的本地语音引擎，已跳过播报")
            return False
        command, path = built

        with self._lock:
            previous = self._process
            self._process = None
            self._thread = None
        _terminate(previous)

        try:
            process = (self._popen or subprocess.Popen)(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=_CREATION_FLAGS,
            )
        except (OSError, ValueError) as exc:
            self._logger.warning("启动语音播报失败：%s", exc)
            _unlink(path)
            return False

        thread = threading.Thread(
            target=self._reap,
            args=(process, path),
            name="AgentBellVoice",
            daemon=True,
        )
        with self._lock:
            self._process = process
            self._thread = thread
        thread.start()
        return True

    def stop(self) -> None:
        with self._lock:
            process = self._process
            self._process = None
        _terminate(process)

    def _reap(self, process: subprocess.Popen[bytes], path: Path) -> None:
        try:
            process.wait()
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            _unlink(path)
        with self._lock:
            if self._process is process:
                self._process = None
            if self._thread is threading.current_thread():
                self._thread = None
