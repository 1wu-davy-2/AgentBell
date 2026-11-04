from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QObject, Signal

from .agent_sessions import default_claude_root, default_qoder_root
from .config import AttentionConfig
from .models import ATTENTION_AGENT_LABELS, WAIT_REASON_LABELS, WaitReason

_TAIL_BYTES = 256 * 1024
_MAX_ENTRIES = 120
_ACTIVE_WINDOW_SECONDS = 600
_CONFIRM_SCANS = 2
_SESSION_COOLDOWN_SECONDS = 120.0
_QUESTION_TAIL_CHARS = 240

_RATE_LIMIT_HINTS = (
    "rate limit",
    "rate-limit",
    "too many requests",
    "quota exceeded",
    "usage limit",
    "429 too many",
    "速率限制",
    "请求过于频繁",
    "请求过多",
    "配额已用尽",
    "额度已用尽",
    "触发限流",
)
_CONTEXT_LIMIT_HINTS = (
    "context length",
    "context window",
    "maximum context",
    "context limit",
    "token limit",
    "too many tokens",
    "prompt is too long",
    "上下文长度",
    "上下文窗口",
    "上下文超出",
    "超出上下文",
    "token 超限",
    "token 数量超出",
)
_QUESTION_HINTS = (
    "would you like",
    "shall i",
    "should i",
    "do you want",
    "may i",
    "can i proceed",
    "是否",
    "要不要",
    "需要我",
    "可以吗",
    "继续吗",
    "确认吗",
)
_QUESTION_END = re.compile(r"[?？]\s*$")


@dataclass(frozen=True, slots=True)
class WaitSignal:
    reason: WaitReason
    fingerprint: str


@dataclass(frozen=True, slots=True)
class WaitDetection:
    agent: str
    session_id: str
    session_path: str
    project: str
    reason: WaitReason
    fingerprint: str
    idle_seconds: int

    @property
    def dedupe_key(self) -> str:
        return _dedupe_key(self.agent, self.session_id, self.fingerprint)

    @property
    def title(self) -> str:
        label = ATTENTION_AGENT_LABELS.get(self.agent, self.agent)
        return f"{label} {WAIT_REASON_LABELS.get(self.reason, '等待输入')}"

    @property
    def summary(self) -> str:
        place = self.project or f"会话 {self.session_id[:8]}"
        return f"{place} 的会话已闲置 {self.idle_seconds} 秒，等待你继续处理。"


@dataclass(frozen=True, slots=True)
class WaitResolution:
    agent: str
    session_id: str
    dedupe_key: str


def _dedupe_key(agent: str, session_id: str, fingerprint: str) -> str:
    return f"wait:{agent}:{session_id}:{fingerprint}"


def _blocks(entry: dict) -> list[dict]:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return []


def _assistant_text(entry: dict) -> str:
    parts: list[str] = []
    for block in _blocks(entry):
        if block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
    return "\n".join(parts)


def _user_advanced(entry: dict) -> bool:
    if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
        return False
    for block in _blocks(entry):
        kind = block.get("type")
        if kind == "tool_result":
            return True
        if kind == "text":
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return True
    return False


def _has_hint(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(hint in lowered for hint in hints)


def _looks_like_question(text: str) -> bool:
    tail = " ".join(text.strip().split())
    if not tail:
        return False
    tail = tail[-_QUESTION_TAIL_CHARS:]
    if _QUESTION_END.search(tail):
        return True
    lowered = tail.casefold()
    for hint in _QUESTION_HINTS:
        index = lowered.rfind(hint)
        if index >= 0 and len(lowered) - (index + len(hint)) <= 40:
            return True
    return False


def _fingerprint(entry: dict) -> str:
    uuid = entry.get("uuid")
    if isinstance(uuid, str) and uuid.strip():
        return uuid.strip()[:24]
    raw = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def detect_wait(entries: Sequence[dict]) -> WaitSignal | None:
    """Infer a waiting-input episode from the tail of a session transcript."""
    conversation = [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("type") in {"user", "assistant"}
    ]
    last_assistant = -1
    for index, entry in enumerate(conversation):
        if entry.get("type") == "assistant" and not entry.get("isSidechain"):
            last_assistant = index
    if last_assistant < 0:
        return None

    assistant = conversation[last_assistant]
    for entry in conversation[last_assistant + 1 :]:
        if entry.get("type") == "user" and _user_advanced(entry):
            return None

    text = _assistant_text(assistant)
    error_text = " ".join(
        value
        for value in (assistant.get("error"), assistant.get("errorMessage"))
        if isinstance(value, str)
    )
    haystack = f"{text}\n{error_text}".strip()
    if haystack:
        if _has_hint(haystack, _CONTEXT_LIMIT_HINTS):
            return WaitSignal("context_limit", _fingerprint(assistant))
        if _has_hint(haystack, _RATE_LIMIT_HINTS):
            return WaitSignal("rate_limit", _fingerprint(assistant))

    has_tool_use = any(
        block.get("type") == "tool_use" for block in _blocks(assistant)
    )
    if has_tool_use:
        return WaitSignal("permission", _fingerprint(assistant))
    if _looks_like_question(text):
        return WaitSignal("question", _fingerprint(assistant))
    return None


@dataclass
class _TailCache:
    offset: int = 0
    mtime_ns: int = -1
    pending: bytes = b""
    entries: list[dict] = field(default_factory=list)


@dataclass
class _SessionState:
    cache: _TailCache = field(default_factory=_TailCache)
    candidate_reason: str = ""
    candidate_fingerprint: str = ""
    candidate_count: int = 0
    active_key: str = ""
    last_emit_at: float = 0.0


def _read_tail(path: Path, cache: _TailCache) -> tuple[list[dict], bool]:
    """Read only appended bytes, keeping at most the last 256 KB of entries."""
    try:
        stat = path.stat()
    except OSError:
        return cache.entries, False
    size = stat.st_size
    if size < cache.offset:
        cache.offset = 0
        cache.pending = b""
        cache.entries.clear()
    if size == cache.offset:
        cache.mtime_ns = stat.st_mtime_ns
        return cache.entries, False

    try:
        with path.open("rb") as handle:
            if cache.offset == 0 and size > _TAIL_BYTES:
                handle.seek(size - _TAIL_BYTES)
                chunk = handle.read(_TAIL_BYTES)
                newline = chunk.find(b"\n")
                chunk = chunk[newline + 1 :] if newline >= 0 else b""
                cache.offset = size
            else:
                handle.seek(cache.offset)
                chunk = handle.read(size - cache.offset)
                cache.offset += len(chunk)
    except OSError:
        return cache.entries, False

    data = cache.pending + chunk
    lines = data.split(b"\n")
    cache.pending = lines.pop() if lines else b""
    added = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            cache.entries.append(entry)
            added += 1
    if added:
        cache.entries = cache.entries[-_MAX_ENTRIES:]
    cache.mtime_ns = stat.st_mtime_ns
    return cache.entries, bool(chunk)


def _candidate_paths(root: Path) -> list[Path]:
    try:
        return list(root.glob("*/*.jsonl"))
    except OSError:
        return []


def _project_label(session_path: Path) -> str:
    folder = session_path.parent.name.strip()
    if len(folder) >= 3 and folder[1:3] == "--" and folder[0].isalpha():
        rest = folder[3:].replace("-", "\\")
        name = Path(rest).name
        return name or folder
    return folder


class AttentionScanner(QObject):
    """Polls recent Claude Code / Qoder transcripts for waiting-input episodes."""

    detected = Signal(object)
    resolved = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        config: AttentionConfig,
        logger: logging.Logger,
        parent: QObject | None = None,
        claude_root: Path | None = None,
        qoder_root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._logger = logger
        self._claude_root = claude_root or default_claude_root()
        self._qoder_root = qoder_root or default_qoder_root()
        self._states: dict[str, _SessionState] = {}
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="agent-attention", daemon=True
        )
        self._thread.start()

    def apply_config(self, config: AttentionConfig) -> None:
        self._config = config
        self._wake_event.set()

    def refresh(self) -> None:
        self._wake_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            config = self._config
            if config.enabled and config.infer:
                try:
                    detections, resolutions = self.scan_once()
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning("等待输入推断失败：%s", exc)
                    self.failed.emit(str(exc))
                else:
                    for item in resolutions:
                        self.resolved.emit(item)
                    for item in detections:
                        self._logger.info(
                            "推断到等待输入：agent=%s session=%s reason=%s idle=%ss",
                            item.agent,
                            item.session_id[:8],
                            item.reason,
                            item.idle_seconds,
                        )
                        self.detected.emit(item)
            self._wake_event.wait(max(2, int(config.poll_interval_seconds)))
            self._wake_event.clear()

    def scan_once(
        self, now_monotonic: float | None = None
    ) -> tuple[list[WaitDetection], list[WaitResolution]]:
        config = self._config
        if not config.enabled or not config.infer:
            return [], []

        mono = time.monotonic() if now_monotonic is None else now_monotonic
        wall = datetime.now().astimezone().timestamp()
        detections: list[WaitDetection] = []
        resolutions: list[WaitResolution] = []
        seen: set[str] = set()
        roots = (("claude", self._claude_root), ("qoder", self._qoder_root))
        for agent, root in roots:
            if agent not in config.agents:
                continue
            for path in _candidate_paths(root):
                key = str(path)
                seen.add(key)
                state = self._states.get(key)
                if state is None:
                    state = _SessionState()
                    self._states[key] = state
                session_id = path.stem
                try:
                    age = wall - path.stat().st_mtime
                except OSError:
                    continue
                if age > _ACTIVE_WINDOW_SECONDS:
                    if state.active_key:
                        resolutions.append(
                            WaitResolution(agent, session_id, state.active_key)
                        )
                        state.active_key = ""
                    state.candidate_reason = ""
                    state.candidate_fingerprint = ""
                    state.candidate_count = 0
                    continue

                entries, changed = _read_tail(path, state.cache)
                if changed:
                    state.candidate_reason = ""
                    state.candidate_fingerprint = ""
                    state.candidate_count = 0
                signal = detect_wait(entries)
                if signal is None:
                    if state.active_key:
                        resolutions.append(
                            WaitResolution(agent, session_id, state.active_key)
                        )
                        state.active_key = ""
                    continue

                dedupe_key = _dedupe_key(agent, session_id, signal.fingerprint)
                if (
                    signal.fingerprint == state.candidate_fingerprint
                    and signal.reason == state.candidate_reason
                ):
                    state.candidate_count += 1
                else:
                    state.candidate_fingerprint = signal.fingerprint
                    state.candidate_reason = signal.reason
                    state.candidate_count = 1

                if state.active_key and state.active_key != dedupe_key:
                    resolutions.append(
                        WaitResolution(agent, session_id, state.active_key)
                    )
                    state.active_key = ""
                if state.active_key == dedupe_key:
                    continue
                idle_seconds = max(0, int(age))
                if idle_seconds < config.idle_seconds:
                    continue
                if state.candidate_count < _CONFIRM_SCANS:
                    continue
                if (
                    state.last_emit_at
                    and mono - state.last_emit_at < _SESSION_COOLDOWN_SECONDS
                ):
                    continue

                state.active_key = dedupe_key
                state.last_emit_at = mono
                detections.append(
                    WaitDetection(
                        agent=agent,
                        session_id=session_id,
                        session_path=key,
                        project=_project_label(path),
                        reason=signal.reason,
                        fingerprint=signal.fingerprint,
                        idle_seconds=idle_seconds,
                    )
                )

        for key in list(self._states):
            if key not in seen:
                self._states.pop(key, None)
        return detections, resolutions

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self._config.infer
