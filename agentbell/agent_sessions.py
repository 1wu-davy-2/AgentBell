from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import AgentSessionsConfig

_MAX_META_BYTES = 64 * 1024
_MAX_COUNT_BYTES = 8 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024
_MAX_TRANSCRIPT_BYTES = 128 * 1024 * 1024
_MAX_TITLE_CHARS = 80
_MAX_PROMPT_CHARS = 6000
_MAX_ITEM_CHARS = 3000
_MAX_TURNS = 300
_MAX_ITEMS_PER_TURN = 600
_TITLE_READ_LINES = 140

_SYSTEM_TAG = re.compile(
    r"<(system-reminder|local-command-caveat|local-command-stdout|"
    r"command-name|command-message|command-args)>.*?</\1>",
    re.DOTALL,
)
_FILE_TOOLS = {"Edit", "Write", "NotebookEdit", "MultiEdit", "ApplyPatch"}


@dataclass(frozen=True, slots=True)
class AgentSession:
    agent: str
    session_id: str
    project: str
    project_path: str
    path: str
    updated_at: datetime
    created_at: datetime | None = None
    message_count: int = 0
    size_bytes: int = 0
    title: str = ""

    @property
    def agent_label(self) -> str:
        return {"claude": "Claude Code", "qoder": "Qoder"}.get(
            self.agent, self.agent
        )

    @property
    def folder(self) -> str:
        path = Path(self.path)
        return str(path.parent if path.is_file() else path)

    @property
    def display_title(self) -> str:
        return self.title or f"会话 {self.session_id[:8]}"


@dataclass(frozen=True, slots=True)
class SessionItem:
    kind: str
    role: str
    text: str
    name: str = ""
    error: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SessionTurn:
    index: int
    prompt: str
    timestamp: datetime | None
    items: tuple[SessionItem, ...] = ()
    tool_calls: int = 0
    tool_failures: int = 0
    files: int = 0

    @property
    def preview(self) -> str:
        text = " ".join(self.prompt.split())
        if not text:
            return "（会话开始）"
        if len(text) <= 100:
            return text
        return text[:99].rstrip() + "…"


@dataclass(frozen=True, slots=True)
class SessionTranscript:
    session: AgentSession
    turns: tuple[SessionTurn, ...] = ()
    total_turns: int = 0
    total_items: int = 0
    note: str = ""
    truncated: bool = False


@dataclass
class _TurnDraft:
    prompt: str = ""
    timestamp: datetime | None = None
    items: list[SessionItem] = field(default_factory=list)
    files: set[str] = field(default_factory=set)
    dropped: int = 0


def _local(epoch: float | None) -> datetime | None:
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(epoch).astimezone()
    except (OSError, OverflowError, ValueError):
        return None


def _parse_time(value: object) -> datetime | None:
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000.0
        return _local(number)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.isdigit():
        return _parse_time(int(text))
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone()


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: limit - 1].rstrip() + "…", True


def _count_lines(path: Path) -> int:
    try:
        with path.open("rb") as handle:
            count = 0
            consumed = 0
            while consumed < _MAX_COUNT_BYTES:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                count += chunk.count(b"\n")
                consumed += len(chunk)
            return count
    except OSError:
        return 0


def _clean_text(text: str) -> str:
    cleaned = _SYSTEM_TAG.sub("", text or "")
    return cleaned.strip()


def _title_from_text(text: str) -> str:
    for line in text.splitlines():
        collapsed = " ".join(line.split())
        if collapsed:
            clipped, _ = _clip(collapsed, _MAX_TITLE_CHARS)
            return clipped
    return ""


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                value = block.get("text")
                if isinstance(value, str) and value:
                    parts.append(value)
            elif kind == "image":
                parts.append("[图片]")
        return "\n\n".join(parts)
    if isinstance(content, dict):
        for key in ("text", "content", "output"):
            value = content.get(key)
            if isinstance(value, str) and value:
                return value
    return ""


def _entry_text(entry: dict) -> str:
    return _clean_text(_content_text((entry.get("message") or {}).get("content")))


def _entry_user_text(entry: dict) -> str:
    if entry.get("isMeta") or entry.get("isSidechain"):
        return ""
    if entry.get("isCompactSummary"):
        return ""
    return _entry_text(entry)


def _read_transcript_meta(path: Path) -> tuple[str, datetime | None, str]:
    cwd = ""
    created: datetime | None = None
    title = ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for _ in range(_TITLE_READ_LINES):
                line = handle.readline(_MAX_META_BYTES)
                if not line:
                    break
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if not cwd:
                    candidate = entry.get("cwd")
                    if not isinstance(candidate, str) or not candidate.strip():
                        directories = entry.get("directories")
                        if (
                            isinstance(directories, list)
                            and directories
                            and isinstance(directories[0], str)
                        ):
                            candidate = directories[0]
                    if isinstance(candidate, str) and candidate.strip():
                        cwd = candidate.strip()
                if created is None:
                    created = _parse_time(entry.get("timestamp"))
                if created is None and entry.get("type") == "runtime-config":
                    created = _parse_time(entry.get("timestamp"))
                if not title and entry.get("type") == "user":
                    text = _entry_user_text(entry)
                    if text:
                        title = _title_from_text(text)
                if cwd and created is not None and title:
                    break
    except OSError:
        pass
    return cwd, created, title


def _decode_project(folder: str) -> str:
    text = folder.strip()
    if len(text) >= 3 and text[1:3] == "--" and text[0].isalpha():
        rest = text[3:].replace("-", "\\")
        return f"{text[0]}:\\{rest}" if rest else f"{text[0]}:\\"
    return text.replace("-", "\\")


def _project_name(folder: str, project_path: str) -> str:
    path = Path(project_path) if project_path else Path()
    if project_path:
        name = path.name
        if name:
            return name
    decoded = _decode_project(folder)
    name = Path(decoded).name if decoded else ""
    return name or folder


def _claude_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    sessions: list[AgentSession] = []
    for path in root.glob("*/*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        updated = _local(stat.st_mtime) or now
        cwd, created, title = _read_transcript_meta(path)
        folder = path.parent.name
        sessions.append(
            AgentSession(
                agent="claude",
                session_id=path.stem,
                project=_project_name(folder, cwd),
                project_path=cwd or _decode_project(folder),
                path=str(path),
                updated_at=updated,
                created_at=created,
                message_count=_count_lines(path),
                size_bytes=int(stat.st_size),
                title=title,
            )
        )
    return sessions


def _load_json(path: Path) -> dict | None:
    try:
        if path.stat().st_size > _MAX_STATE_BYTES:
            return None
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _qoder_state_values(
    state: dict, folder: str
) -> tuple[str, datetime | None, datetime | None, str]:
    session_id = state.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        session_id = folder
    created = _parse_time(state.get("createdAt"))
    updated = _parse_time(state.get("updatedAt"))
    project_path = ""
    for key in ("cwd", "workspacePath", "projectPath"):
        value = state.get(key)
        if isinstance(value, str) and value.strip():
            project_path = value.strip()
            break
    return session_id, created, updated, project_path


def _qoder_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    sessions: list[AgentSession] = []
    for path in root.glob("*/*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        state = _load_json(path.with_suffix("") / "state.json") or {}
        session_id, created, state_updated, project_path = _qoder_state_values(
            state, path.stem
        )
        cwd, file_created, title = _read_transcript_meta(path)
        updated = state_updated or _local(stat.st_mtime) or now
        folder = path.parent.name
        sessions.append(
            AgentSession(
                agent="qoder",
                session_id=session_id,
                project=_project_name(folder, project_path or cwd),
                project_path=project_path or cwd or _decode_project(folder),
                path=str(path),
                updated_at=updated,
                created_at=created or file_created,
                message_count=_count_lines(path),
                size_bytes=int(stat.st_size),
                title=title,
            )
        )
    jsonl_paths = {item for item in root.glob("*/*.jsonl")}
    for state_path in root.glob("*/*/state.json"):
        if state_path.parent.parent / f"{state_path.parent.name}.jsonl" in jsonl_paths:
            continue
        try:
            stat = state_path.stat()
        except OSError:
            continue
        state = _load_json(state_path) or {}
        session_dir = state_path.parent
        session_id, created, updated, project_path = _qoder_state_values(
            state, session_dir.name
        )
        folder = session_dir.parent.name
        updated = updated or _local(stat.st_mtime) or now
        sessions.append(
            AgentSession(
                agent="qoder",
                session_id=session_id,
                project=_project_name(folder, project_path),
                project_path=project_path or _decode_project(folder),
                path=str(session_dir),
                updated_at=updated,
                created_at=created,
                size_bytes=int(stat.st_size),
            )
        )
    return sessions


def default_claude_root() -> Path:
    return Path.home() / ".claude" / "projects"


def default_qoder_root() -> Path:
    return Path.home() / ".qoder" / "projects"


def scan_sessions(
    claude_root: Path | None = None,
    qoder_root: Path | None = None,
    max_sessions: int = 80,
    now: datetime | None = None,
) -> list[AgentSession]:
    current = now or datetime.now().astimezone()
    sessions = _claude_sessions(claude_root or default_claude_root(), current)
    sessions.extend(_qoder_sessions(qoder_root or default_qoder_root(), current))
    sessions.sort(key=lambda item: item.updated_at, reverse=True)
    return sessions[: max(1, int(max_sessions))]


def _resolve_transcript_path(session: AgentSession) -> Path | None:
    path = Path(session.path)
    if path.is_file():
        return path
    if path.is_dir():
        sibling = path.parent / f"{path.name}.jsonl"
        if sibling.is_file():
            return sibling
        candidates = sorted(
            path.glob("*.jsonl"),
            key=lambda item: item.stat().st_mtime if item.exists() else 0,
            reverse=True,
        )
        if candidates:
            return candidates[0]
    return None


def _tool_detail(payload: object) -> str:
    if isinstance(payload, dict):
        for key in (
            "command",
            "file_path",
            "path",
            "pattern",
            "query",
            "url",
            "description",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                detail, _ = _clip(" ".join(value.split()), 500)
                return detail
        try:
            detail, _ = _clip(
                json.dumps(payload, ensure_ascii=False), 500
            )
            return detail
        except (TypeError, ValueError):
            return ""
    if isinstance(payload, str):
        detail, _ = _clip(" ".join(payload.split()), 500)
        return detail
    return ""


def _is_error_result(entry: dict, block: dict) -> bool:
    if block.get("is_error"):
        return True
    result = entry.get("toolUseResult")
    if isinstance(result, dict):
        if result.get("is_error") or result.get("isError"):
            return True
        kind = result.get("kind")
        if isinstance(kind, str) and kind.lower() in {"error", "failed"}:
            return True
    return False


def _append_item(turn: _TurnDraft, item: SessionItem) -> None:
    if len(turn.items) >= _MAX_ITEMS_PER_TURN:
        turn.dropped += 1
        return
    turn.items.append(item)


def _handle_user_entry(
    entry: dict, turn: _TurnDraft, tool_names: dict[str, str]
) -> _TurnDraft:
    if entry.get("isSidechain") or entry.get("isCompactSummary"):
        return turn
    content = (entry.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    text_parts: list[str] = []
    timestamp = _parse_time(entry.get("timestamp"))
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            if entry.get("isMeta"):
                continue
            cleaned = _clean_text(block.get("text") or "")
            if cleaned:
                text_parts.append(cleaned)
        elif kind == "tool_result":
            raw = _content_text(block.get("content"))
            text, truncated = _clip(raw.strip(), _MAX_ITEM_CHARS)
            tool_id = block.get("tool_use_id")
            name = tool_names.get(tool_id, "") if isinstance(tool_id, str) else ""
            _append_item(
                turn,
                SessionItem(
                    kind="result",
                    role="user",
                    text=text,
                    name=name,
                    error=_is_error_result(entry, block),
                    truncated=truncated,
                ),
            )
        elif kind == "image":
            _append_item(
                turn,
                SessionItem(kind="image", role="user", text="[图片]"),
            )
    prompt = "\n\n".join(text_parts).strip()
    if prompt:
        if turn.prompt or turn.items:
            new_turn = _TurnDraft()
            new_turn.prompt = prompt
            new_turn.timestamp = timestamp
            return new_turn
        turn.prompt = prompt
        turn.timestamp = timestamp
    return turn


def _handle_assistant_entry(
    entry: dict,
    turn: _TurnDraft,
    tool_names: dict[str, str],
) -> None:
    if entry.get("isSidechain"):
        return
    content = (entry.get("message") or {}).get("content")
    blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            text = _clean_text(block.get("text") or "")
            if text:
                clipped, truncated = _clip(text, _MAX_ITEM_CHARS)
                _append_item(
                    turn,
                    SessionItem(
                        kind="text",
                        role="assistant",
                        text=clipped,
                        truncated=truncated,
                    ),
                )
        elif kind == "thinking":
            text = _clean_text(block.get("thinking") or block.get("text") or "")
            if text:
                clipped, truncated = _clip(text, _MAX_ITEM_CHARS)
                _append_item(
                    turn,
                    SessionItem(
                        kind="thinking",
                        role="assistant",
                        text=clipped,
                        truncated=truncated,
                    ),
                )
        elif kind == "tool_use":
            name = block.get("name")
            name = name if isinstance(name, str) and name else "工具"
            tool_id = block.get("id")
            if isinstance(tool_id, str):
                tool_names[tool_id] = name
            payload = block.get("input")
            if isinstance(payload, dict) and name in _FILE_TOOLS:
                path = payload.get("file_path") or payload.get("path")
                if isinstance(path, str) and path.strip():
                    turn.files.add(path.strip())
            _append_item(
                turn,
                SessionItem(
                    kind="tool",
                    role="assistant",
                    text=_tool_detail(payload),
                    name=name,
                ),
            )
        elif kind == "image":
            _append_item(
                turn,
                SessionItem(kind="image", role="assistant", text="[图片]"),
            )


def parse_session_transcript(
    session: AgentSession, max_turns: int = _MAX_TURNS
) -> SessionTranscript:
    path = _resolve_transcript_path(session)
    if path is None:
        return SessionTranscript(
            session=session, note="未找到该会话的记录文件，仅能查看元数据。"
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        return SessionTranscript(session=session, note=f"读取会话文件失败：{exc}")
    if size > _MAX_TRANSCRIPT_BYTES:
        return SessionTranscript(
            session=session,
            note="会话文件超过 128 MB，已跳过解析。",
            truncated=True,
        )

    drafts: list[_TurnDraft] = []
    turn = _TurnDraft()
    tool_names: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                kind = entry.get("type")
                if kind == "user":
                    updated = _handle_user_entry(entry, turn, tool_names)
                    if updated is not turn:
                        drafts.append(turn)
                        turn = updated
                elif kind == "assistant":
                    _handle_assistant_entry(entry, turn, tool_names)
    except OSError as exc:
        return SessionTranscript(session=session, note=f"读取会话文件失败：{exc}")
    if turn.prompt or turn.items:
        drafts.append(turn)

    total_turns = len(drafts)
    total_items = sum(len(item.items) for item in drafts)
    truncated = total_turns > max_turns or any(item.dropped for item in drafts)
    kept = drafts[-max_turns:] if total_turns > max_turns else drafts
    turns: list[SessionTurn] = []
    for index, draft in enumerate(kept, start=1):
        prompt, prompt_cut = _clip(draft.prompt.strip(), _MAX_PROMPT_CHARS)
        items = tuple(draft.items)
        if prompt_cut or draft.dropped:
            truncated = True
        turns.append(
            SessionTurn(
                index=index,
                prompt=prompt,
                timestamp=draft.timestamp,
                items=items,
                tool_calls=sum(1 for item in items if item.kind == "tool"),
                tool_failures=sum(
                    1 for item in items if item.kind == "result" and item.error
                ),
                files=len(draft.files),
            )
        )
    note = ""
    if not turns:
        note = "该会话没有可展示的对话内容。"
    elif total_turns > max_turns:
        note = f"会话较长，仅展示最近 {max_turns} 轮（共 {total_turns} 轮）。"
    elif truncated:
        note = "部分内容过长或过多，已截断。"
    return SessionTranscript(
        session=session,
        turns=tuple(turns),
        total_turns=total_turns,
        total_items=total_items,
        note=note,
        truncated=truncated,
    )


def transcript_to_markdown(transcript: SessionTranscript) -> str:
    session = transcript.session
    updated = session.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# {session.display_title}",
        "",
        f"- Agent：{session.agent_label}",
        f"- 项目：{session.project_path or session.folder}",
        f"- 会话 ID：{session.session_id}",
        f"- 更新时间：{updated}",
    ]
    if transcript.note:
        lines.append(f"- 说明：{transcript.note}")
    lines.append("")
    for turn in transcript.turns:
        stamp = (
            turn.timestamp.astimezone().strftime("%Y-%m-%d %H:%M")
            if turn.timestamp is not None
            else "时间未知"
        )
        lines.append(f"## {turn.index}. {turn.preview}")
        lines.append("")
        lines.append(f"**用户** · {stamp}")
        lines.append("")
        lines.append(turn.prompt or "（会话开始）")
        lines.append("")
        for item in turn.items:
            if item.kind == "text":
                lines.append(item.text)
                lines.append("")
            elif item.kind == "thinking":
                lines.append("> 思考")
                lines.append("")
                lines.append(
                    "\n".join(f"> {row}" for row in item.text.splitlines())
                )
                lines.append("")
            elif item.kind == "tool":
                lines.append(f"**工具 · {item.name}**")
                lines.append("")
                if item.text:
                    lines.append("```")
                    lines.append(item.text)
                    lines.append("```")
                    lines.append("")
            elif item.kind == "result":
                label = "工具结果 · 失败" if item.error else "工具结果"
                if item.name:
                    label += f" · {item.name}"
                lines.append(f"**{label}**")
                lines.append("")
                if item.text:
                    lines.append("```")
                    lines.append(item.text)
                    lines.append("```")
                    lines.append("")
            elif item.kind == "image":
                lines.append("_[图片]_")
                lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class AgentSessionScanner(QObject):
    """Reads session metadata on a background thread; never parses content."""

    scanned = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        config: AgentSessionsConfig,
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
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="agent-session-scan", daemon=True
        )
        self._thread.start()

    def apply_config(self, config: AgentSessionsConfig) -> None:
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
            if config.enabled:
                try:
                    sessions = scan_sessions(
                        self._claude_root,
                        self._qoder_root,
                        config.max_sessions,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning("扫描 Agent 会话失败：%s", exc)
                    self.failed.emit(str(exc))
                else:
                    self.scanned.emit(sessions)
                    self._logger.info(
                        "已扫描 Agent 会话：%d 个（Claude=%d Qoder=%d）",
                        len(sessions),
                        sum(1 for item in sessions if item.agent == "claude"),
                        sum(1 for item in sessions if item.agent == "qoder"),
                    )
            interval = max(30, int(config.scan_interval_seconds))
            self._wake_event.wait(interval)
            self._wake_event.clear()

    @property
    def enabled(self) -> bool:
        return self._config.enabled
