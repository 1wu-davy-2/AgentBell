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
from urllib.parse import unquote

from PySide6.QtCore import QObject, Signal

from .agent_sessions import (
    _any_text,
    _gemini_entries,
    _parse_tool_input,
    _prompt_text,
    _text_blocks,
    default_claude_root,
    default_codex_root,
    default_gemini_root,
    default_grok_root,
    default_qoder_root,
)
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


def _wait_codex_entry(entry: dict) -> dict | None:
    if entry.get("type") != "response_item":
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    kind = payload.get("type")
    identifier = payload.get("id") or entry.get("ordinal")
    if kind == "message":
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            return None
        blocks = _text_blocks(payload.get("content"))
        if role == "user":
            normalized: list[dict] = []
            for block in blocks:
                if block.get("type") == "text":
                    text = _prompt_text(block.get("text") or "")
                    if text:
                        normalized.append({"type": "text", "text": text})
                else:
                    normalized.append(block)
            blocks = normalized
        if not blocks:
            return None
        return {
            "type": role,
            "uuid": identifier,
            "message": {"content": blocks},
        }
    if kind in {"function_call", "custom_tool_call"}:
        name = payload.get("name")
        name = name if isinstance(name, str) and name else "工具"
        call_id = payload.get("call_id") or payload.get("id")
        raw = payload.get("arguments")
        if kind == "custom_tool_call":
            raw = payload.get("input")
        return {
            "type": "assistant",
            "uuid": call_id or identifier,
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": call_id,
                        "name": name,
                        "input": _parse_tool_input(raw),
                    }
                ]
            },
        }
    if kind in {"function_call_output", "custom_tool_call_output"}:
        return {
            "type": "user",
            "uuid": payload.get("call_id") or identifier,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": payload.get("call_id"),
                        "content": _any_text(payload.get("output")),
                        "is_error": str(payload.get("status") or "").lower()
                        in {"error", "failed"},
                    }
                ]
            },
        }
    return None


def _wait_grok_entries(entry: dict) -> dict | None:
    kind = entry.get("type")
    identifier = entry.get("id") or entry.get("ordinal")
    if kind == "user":
        blocks: list[dict] = []
        for block in _text_blocks(entry.get("content")):
            if block.get("type") == "text":
                text = _prompt_text(block.get("text") or "")
                if text:
                    blocks.append({"type": "text", "text": text})
            else:
                blocks.append(block)
        if not blocks:
            return None
        return {
            "type": "user",
            "uuid": identifier,
            "message": {"content": blocks},
        }
    if kind == "assistant":
        blocks = _text_blocks(entry.get("content"))
        calls = entry.get("tool_calls")
        if isinstance(calls, list):
            for call in calls:
                if not isinstance(call, dict):
                    continue
                name = call.get("name")
                name = name if isinstance(name, str) and name else "工具"
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.get("id"),
                        "name": name,
                        "input": _parse_tool_input(call.get("arguments")),
                    }
                )
        if not blocks:
            return None
        return {
            "type": "assistant",
            "uuid": identifier,
            "message": {"content": blocks},
        }
    if kind == "tool_result":
        return {
            "type": "user",
            "uuid": identifier,
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": entry.get("tool_call_id"),
                        "content": _any_text(entry.get("content")),
                    }
                ]
            },
        }
    return None


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


def _read_full(
    path: Path, cache: _TailCache, loader
) -> tuple[list[dict], bool]:
    try:
        stat = path.stat()
    except OSError:
        return cache.entries, False
    if stat.st_mtime_ns == cache.mtime_ns and stat.st_size == cache.offset:
        return cache.entries, False
    try:
        entries = list(loader(path))
    except (OSError, ValueError):
        return cache.entries, False
    cache.entries = entries[-_MAX_ENTRIES:]
    cache.offset = stat.st_size
    cache.mtime_ns = stat.st_mtime_ns
    return cache.entries, True


def _read_agent_entries(
    agent: str, path: Path, cache: _TailCache
) -> tuple[list[dict], bool]:
    if agent == "gemini":
        return _read_full(path, cache, _gemini_entries)
    entries, changed = _read_tail(path, cache)
    if agent not in {"codex", "grok"}:
        return entries, changed
    normalizer = _wait_codex_entry if agent == "codex" else _wait_grok_entries
    normalized = [
        item for item in (normalizer(entry) for entry in entries) if item is not None
    ]
    return normalized, changed


_AGENT_GLOBS = {
    "codex": "*/*/*/rollout-*.jsonl",
    "gemini": "*/chats/session-*.json*",
    "grok": "*/*/chat_history.jsonl",
}


def _candidate_paths(agent: str, root: Path) -> list[Path]:
    pattern = _AGENT_GLOBS.get(agent, "*/*.jsonl")
    try:
        iterator = root.rglob(pattern) if agent == "codex" else root.glob(pattern)
        return [path for path in iterator if path.is_file()]
    except OSError:
        return []


def _session_id(agent: str, path: Path) -> str:
    if agent == "grok":
        return path.parent.name
    return path.stem


def _project_label(agent: str, path: Path) -> str:
    if agent in {"claude", "qoder"}:
        folder = path.parent.name.strip()
        if len(folder) >= 3 and folder[1:3] == "--" and folder[0].isalpha():
            rest = folder[3:].replace("-", "\\")
            parts = [part for part in re.split(r"[\\/]+", rest) if part]
            if parts:
                return parts[-1]
        return folder
    if agent == "grok":
        encoded = path.parents[1].name if len(path.parents) > 1 else ""
        decoded = unquote(encoded)
        parts = [part for part in re.split(r"[\\/]+", decoded) if part]
        return parts[-1] if parts else decoded
    if agent == "gemini":
        return path.parents[1].name if len(path.parents) > 1 else ""
    return ""


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
        codex_root: Path | None = None,
        gemini_root: Path | None = None,
        grok_root: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._logger = logger
        self._claude_root = claude_root or default_claude_root()
        self._qoder_root = qoder_root or default_qoder_root()
        self._codex_root = codex_root or default_codex_root()
        self._gemini_root = gemini_root or default_gemini_root()
        self._grok_root = grok_root or default_grok_root()
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
        roots = (
            ("claude", self._claude_root),
            ("qoder", self._qoder_root),
            ("codex", self._codex_root),
            ("gemini", self._gemini_root),
            ("grok", self._grok_root),
        )
        for agent, root in roots:
            if agent not in config.agents:
                continue
            for path in _candidate_paths(agent, root):
                key = str(path)
                seen.add(key)
                state = self._states.get(key)
                if state is None:
                    state = _SessionState()
                    self._states[key] = state
                session_id = _session_id(agent, path)
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

                entries, changed = _read_agent_entries(agent, path, state.cache)
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
                        project=_project_label(agent, path),
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
