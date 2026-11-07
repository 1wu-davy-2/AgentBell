from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import urllib.parse
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
_CONTEXT_TAG = re.compile(
    r"<(environment_context|session_context|user_info|git_status|rules|"
    r"project_context|skills_instructions|user_instructions)>.*?</\1>",
    re.DOTALL,
)
_USER_QUERY = re.compile(r"<user_query>(.*?)</user_query>", re.DOTALL)
_CONTEXT_PREFIXES = (
    "<environment_context>",
    "<session_context>",
    "<user_info>",
    "<git_status>",
    "<rules>",
    "<project_context>",
    "<skills_instructions>",
    "<user_instructions>",
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
        return {
            "claude": "Claude Code",
            "qoder": "Qoder",
            "codex": "Codex",
            "gemini": "Gemini CLI",
            "grok": "Grok",
            "opencode": "OpenCode",
        }.get(self.agent, self.agent)

    @property
    def folder(self) -> str:
        if not self.path:
            return self.project_path
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
            if kind in {"text", "input_text", "output_text", "summary_text"} or (
                kind is None and isinstance(block.get("text"), str)
            ):
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


def _any_text(value: object) -> str:
    text = _content_text(value)
    if text:
        return text
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return ""
    if isinstance(value, (int, float)):
        return str(value)
    return ""


def _prompt_text(text: str) -> str:
    cleaned = _clean_text(text)
    query = _USER_QUERY.search(cleaned)
    if query:
        cleaned = query.group(1)
    else:
        cleaned = _CONTEXT_TAG.sub("", cleaned)
    lines = [
        line
        for line in cleaned.splitlines()
        if not line.strip().startswith(_CONTEXT_PREFIXES)
    ]
    return "\n".join(lines).strip()


def _text_blocks(content: object) -> list[dict]:
    blocks: list[dict] = []
    raw = content if isinstance(content, list) else [content]
    for block in raw:
        if isinstance(block, str):
            if block.strip():
                blocks.append({"type": "text", "text": block})
            continue
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "image":
            blocks.append({"type": "image"})
            continue
        if kind in {None, "text", "input_text", "output_text"}:
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                blocks.append({"type": "text", "text": text})
    return blocks


def _iter_jsonl(path: Path):
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
                if isinstance(entry, dict):
                    yield entry
    except OSError:
        return


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


def _path_name(value: str) -> str:
    parts = [part for part in re.split(r"[\\/]+", value) if part]
    return parts[-1] if parts else ""


def _project_name(folder: str, project_path: str) -> str:
    if project_path:
        name = _path_name(project_path)
        if name:
            return name
    decoded = _decode_project(folder)
    name = _path_name(decoded)
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


def default_codex_root() -> Path:
    return Path.home() / ".codex" / "sessions"


def default_gemini_root() -> Path:
    return Path.home() / ".gemini" / "tmp"


def default_grok_root() -> Path:
    return Path.home() / ".grok" / "sessions"


def default_opencode_db() -> Path:
    return Path.home() / ".local" / "share" / "opencode" / "opencode.db"


def _first_prompt(messages: object) -> str:
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") not in {"user", "human"}:
            continue
        text = _prompt_text(_content_text(message.get("content")))
        for line in text.splitlines():
            collapsed = " ".join(line.split())
            if not collapsed:
                continue
            return _title_from_text(collapsed)
    return ""


def _codex_meta(path: Path) -> tuple[str, str, datetime | None, str]:
    session_id = ""
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
                payload = entry.get("payload")
                if not isinstance(payload, dict):
                    continue
                if entry.get("type") == "session_meta":
                    candidate = payload.get("session_id") or payload.get("id")
                    if isinstance(candidate, str) and candidate.strip():
                        session_id = candidate.strip()
                    value = payload.get("cwd")
                    if isinstance(value, str) and value.strip():
                        cwd = value.strip()
                    created = created or _parse_time(payload.get("timestamp"))
                elif payload.get("type") == "message" and not title:
                    role = payload.get("role")
                    if role == "user":
                        title = _first_prompt(
                            [{"type": "user", "content": payload.get("content")}]
                        )
                if session_id and cwd and title and created is not None:
                    break
    except OSError:
        pass
    return session_id, cwd, created, title


def _codex_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    sessions: list[AgentSession] = []
    for path in root.rglob("rollout-*.jsonl"):
        try:
            stat = path.stat()
        except OSError:
            continue
        session_id, cwd, created, title = _codex_meta(path)
        sessions.append(
            AgentSession(
                agent="codex",
                session_id=session_id or path.stem,
                project=_project_name(path.parent.name, cwd),
                project_path=cwd,
                path=str(path),
                updated_at=_local(stat.st_mtime) or now,
                created_at=created,
                message_count=0,
                size_bytes=int(stat.st_size),
                title=title,
            )
        )
    return sessions


def _gemini_project_map(root: Path) -> dict[str, str]:
    data = _load_json(root.parent / "projects.json") or {}
    projects = data.get("projects")
    if not isinstance(projects, dict):
        return {}
    return {
        str(slug): str(path)
        for path, slug in projects.items()
        if isinstance(path, str) and isinstance(slug, str)
    }


def _gemini_messages(path: Path) -> tuple[dict, list[dict]]:
    meta: dict = {}
    messages: list[dict] = []
    if path.suffix == ".json":
        data = _load_json(path) or {}
        meta = data
        raw = data.get("messages")
        if isinstance(raw, list):
            messages = [item for item in raw if isinstance(item, dict)]
        return meta, messages
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for index, line in enumerate(handle):
                if index > _TITLE_READ_LINES * 20:
                    break
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                if index == 0:
                    meta = entry
                patch = entry.get("$set")
                if isinstance(patch, dict) and isinstance(patch.get("messages"), list):
                    messages = [
                        item for item in patch["messages"] if isinstance(item, dict)
                    ]
                elif entry.get("type") in {"user", "gemini", "error", "info"}:
                    messages.append(entry)
    except OSError:
        pass
    return meta, messages


def _gemini_file_meta(
    path: Path,
) -> tuple[str, datetime | None, datetime | None, int, str]:
    session_id = path.stem
    meta, messages = _gemini_messages(path)
    value = meta.get("sessionId")
    if isinstance(value, str) and value.strip():
        session_id = value.strip()
    created = _parse_time(meta.get("startTime"))
    updated = _parse_time(meta.get("lastUpdated"))
    for message in messages:
        stamp = _parse_time(message.get("timestamp"))
        if stamp is not None and (updated is None or stamp > updated):
            updated = stamp
    title = _first_prompt(messages)
    return session_id, created, updated, len(messages), title


def _gemini_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    projects = _gemini_project_map(root)
    sessions: list[AgentSession] = []
    for path in root.glob("*/chats/session-*"):
        if path.suffix not in {".json", ".jsonl"}:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        session_id, created, updated, count, title = _gemini_file_meta(path)
        folder = path.parent.parent.name
        project_path = projects.get(folder, "")
        sessions.append(
            AgentSession(
                agent="gemini",
                session_id=session_id,
                project=_project_name(folder, project_path),
                project_path=project_path or folder,
                path=str(path),
                updated_at=updated or _local(stat.st_mtime) or now,
                created_at=created,
                message_count=count,
                size_bytes=int(stat.st_size),
                title=title,
            )
        )
    return sessions


def _grok_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    sessions: list[AgentSession] = []
    for path in root.glob("*/*/summary.json"):
        data = _load_json(path)
        if data is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        session_dir = path.parent
        folder = session_dir.parent.name
        decoded = urllib.parse.unquote(folder)
        project_path = data.get("git_root_dir")
        if not isinstance(project_path, str) or not project_path.strip():
            project_path = decoded
        title = data.get("generated_title")
        if not isinstance(title, str):
            title = ""
        try:
            count = int(data.get("num_chat_messages") or 0)
        except (TypeError, ValueError):
            count = 0
        sessions.append(
            AgentSession(
                agent="grok",
                session_id=session_dir.name,
                project=_project_name(folder, project_path),
                project_path=project_path,
                path=str(session_dir),
                updated_at=(
                    _parse_time(data.get("last_active_at"))
                    or _parse_time(data.get("updated_at"))
                    or _local(stat.st_mtime)
                    or now
                ),
                created_at=_parse_time(data.get("created_at")),
                message_count=count,
                size_bytes=int(stat.st_size),
                title=_title_from_text(title),
            )
        )
    return sessions


def _opencode_sessions(db: Path, now: datetime) -> list[AgentSession]:
    if not db.is_file():
        return []
    sessions: list[AgentSession] = []
    try:
        connection = sqlite3.connect(
            f"file:{db.as_posix()}?mode=ro", uri=True, timeout=1.0
        )
    except sqlite3.Error:
        return []
    try:
        rows = connection.execute(
            "SELECT id, directory, title, time_created, time_updated "
            "FROM session WHERE IFNULL(time_archived, 0) = 0 "
            "ORDER BY time_updated DESC LIMIT 300"
        ).fetchall()
    except sqlite3.Error:
        rows = []
    finally:
        connection.close()
    for session_id, directory, title, created, updated in rows:
        project_path = directory if isinstance(directory, str) else ""
        sessions.append(
            AgentSession(
                agent="opencode",
                session_id=str(session_id),
                project=_project_name("", project_path),
                project_path=project_path,
                path="",
                updated_at=_parse_time(updated) or now,
                created_at=_parse_time(created),
                title=_title_from_text(title if isinstance(title, str) else ""),
            )
        )
    return sessions


def scan_sessions(
    claude_root: Path | None = None,
    qoder_root: Path | None = None,
    max_sessions: int = 80,
    now: datetime | None = None,
    *,
    codex_root: Path | None = None,
    gemini_root: Path | None = None,
    grok_root: Path | None = None,
    opencode_db: Path | None = None,
) -> list[AgentSession]:
    current = now or datetime.now().astimezone()
    sessions = _claude_sessions(claude_root or default_claude_root(), current)
    sessions.extend(_qoder_sessions(qoder_root or default_qoder_root(), current))
    if codex_root is not None:
        sessions.extend(_codex_sessions(codex_root, current))
    if gemini_root is not None:
        sessions.extend(_gemini_sessions(gemini_root, current))
    if grok_root is not None:
        sessions.extend(_grok_sessions(grok_root, current))
    if opencode_db is not None:
        sessions.extend(_opencode_sessions(opencode_db, current))
    sessions.sort(key=lambda item: item.updated_at, reverse=True)
    return sessions[: max(1, int(max_sessions))]


def _resolve_transcript_path(session: AgentSession) -> Path | None:
    if session.agent == "opencode":
        return None
    path = Path(session.path)
    if path.is_file():
        return path
    if path.is_dir():
        if session.agent == "grok":
            history = path / "chat_history.jsonl"
            if history.is_file():
                return history
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


def _parse_tool_input(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    if isinstance(value, str) and value.strip():
        return {"input": value.strip()}
    return {}


def _codex_entries(path: Path):
    for entry in _iter_jsonl(path):
        if entry.get("type") != "response_item":
            continue
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        kind = payload.get("type")
        timestamp = entry.get("timestamp")
        if kind == "message":
            role = payload.get("role")
            if role not in {"user", "assistant"}:
                continue
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
            if blocks:
                yield {
                    "type": role,
                    "timestamp": timestamp,
                    "message": {"content": blocks},
                }
        elif kind in {"function_call", "custom_tool_call"}:
            name = payload.get("name")
            name = name if isinstance(name, str) and name else "工具"
            call_id = payload.get("call_id") or payload.get("id")
            raw = payload.get("arguments")
            if kind == "custom_tool_call":
                raw = payload.get("input")
            yield {
                "type": "assistant",
                "timestamp": timestamp,
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
        elif kind in {"function_call_output", "custom_tool_call_output"}:
            text, truncated = _clip(
                _any_text(payload.get("output")), _MAX_ITEM_CHARS
            )
            yield {
                "type": "user",
                "timestamp": timestamp,
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": payload.get("call_id"),
                            "content": text,
                            "is_error": str(payload.get("status") or "").lower()
                            in {"error", "failed"},
                            "truncated": truncated,
                        }
                    ]
                },
            }
        elif kind == "reasoning":
            text = _content_text(payload.get("summary"))
            if text.strip():
                yield {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "message": {
                        "content": [{"type": "thinking", "thinking": text}]
                    },
                }


def _gemini_entries(path: Path):
    _, messages = _gemini_messages(path)
    for message in messages:
        kind = message.get("type")
        timestamp = message.get("timestamp")
        content = message.get("content")
        calls = message.get("toolCalls")
        if kind == "user":
            blocks: list[dict] = []
            for block in _text_blocks(content):
                if block.get("type") == "text":
                    text = _prompt_text(block.get("text") or "")
                    if text:
                        blocks.append({"type": "text", "text": text})
                else:
                    blocks.append(block)
            if blocks:
                yield {
                    "type": "user",
                    "timestamp": timestamp,
                    "message": {"content": blocks},
                }
        elif kind == "gemini":
            blocks = _text_blocks(content)
            results: list[dict] = []
            if isinstance(calls, list):
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    name = call.get("name")
                    name = name if isinstance(name, str) and name else "工具"
                    call_id = call.get("id")
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": name,
                            "input": _parse_tool_input(call.get("args")),
                        }
                    )
                    result = call.get("result")
                    if result is not None:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call_id,
                                "content": _any_text(result),
                                "is_error": str(call.get("status") or "").lower()
                                in {"error", "failed"},
                            }
                        )
            if blocks:
                yield {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "message": {"content": blocks},
                }
            if results:
                yield {
                    "type": "user",
                    "timestamp": timestamp,
                    "message": {"content": results},
                }
        elif kind == "error":
            text = _any_text(content).strip()
            if text:
                yield {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "message": {
                        "content": [{"type": "text", "text": f"[错误] {text}"}]
                    },
                }


def _grok_entries(path: Path):
    for entry in _iter_jsonl(path):
        kind = entry.get("type")
        timestamp = entry.get("ts") or entry.get("timestamp")
        if kind == "user":
            blocks: list[dict] = []
            for block in _text_blocks(entry.get("content")):
                if block.get("type") == "text":
                    text = _prompt_text(block.get("text") or "")
                    if text:
                        blocks.append({"type": "text", "text": text})
                else:
                    blocks.append(block)
            if blocks:
                yield {
                    "type": "user",
                    "timestamp": timestamp,
                    "message": {"content": blocks},
                }
        elif kind == "assistant":
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
            if blocks:
                yield {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "message": {"content": blocks},
                }
        elif kind == "reasoning":
            text = _content_text(entry.get("summary"))
            if text.strip():
                yield {
                    "type": "assistant",
                    "timestamp": timestamp,
                    "message": {
                        "content": [{"type": "thinking", "thinking": text}]
                    },
                }
        elif kind == "tool_result":
            yield {
                "type": "user",
                "timestamp": timestamp,
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


def _iter_entries(session: AgentSession, path: Path):
    if session.agent == "codex":
        yield from _codex_entries(path)
    elif session.agent == "gemini":
        yield from _gemini_entries(path)
    elif session.agent == "grok":
        yield from _grok_entries(path)
    else:
        yield from _iter_jsonl(path)


def parse_session_transcript(
    session: AgentSession, max_turns: int = _MAX_TURNS
) -> SessionTranscript:
    path = _resolve_transcript_path(session)
    if path is None:
        if session.agent == "opencode":
            return SessionTranscript(
                session=session,
                note="OpenCode 会话内容存放在本地数据库中，当前仅支持查看元数据。",
            )
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
    for entry in _iter_entries(session, path):
        kind = entry.get("type")
        if kind == "user":
            updated = _handle_user_entry(entry, turn, tool_names)
            if updated is not turn:
                drafts.append(turn)
                turn = updated
        elif kind == "assistant":
            _handle_assistant_entry(entry, turn, tool_names)
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
        codex_root: Path | None = None,
        gemini_root: Path | None = None,
        grok_root: Path | None = None,
        opencode_db: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._logger = logger
        self._claude_root = claude_root or default_claude_root()
        self._qoder_root = qoder_root or default_qoder_root()
        self._codex_root = codex_root or default_codex_root()
        self._gemini_root = gemini_root or default_gemini_root()
        self._grok_root = grok_root or default_grok_root()
        self._opencode_db = opencode_db or default_opencode_db()
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
                        codex_root=self._codex_root,
                        gemini_root=self._gemini_root,
                        grok_root=self._grok_root,
                        opencode_db=self._opencode_db,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    self._logger.warning("扫描 Agent 会话失败：%s", exc)
                    self.failed.emit(str(exc))
                else:
                    self.scanned.emit(sessions)
                    counts = {
                        agent: sum(1 for item in sessions if item.agent == agent)
                        for agent in (
                            "claude",
                            "qoder",
                            "codex",
                            "gemini",
                            "grok",
                            "opencode",
                        )
                    }
                    self._logger.info(
                        "已扫描 Agent 会话：%d 个（Claude=%d Qoder=%d "
                        "Codex=%d Gemini=%d Grok=%d OpenCode=%d）",
                        len(sessions),
                        counts["claude"],
                        counts["qoder"],
                        counts["codex"],
                        counts["gemini"],
                        counts["grok"],
                        counts["opencode"],
                    )
            interval = max(30, int(config.scan_interval_seconds))
            self._wake_event.wait(interval)
            self._wake_event.clear()

    @property
    def enabled(self) -> bool:
        return self._config.enabled
