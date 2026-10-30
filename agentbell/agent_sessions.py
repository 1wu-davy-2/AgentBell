from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .config import AgentSessionsConfig

_MAX_META_BYTES = 64 * 1024
_MAX_COUNT_BYTES = 8 * 1024 * 1024
_MAX_STATE_BYTES = 4 * 1024 * 1024


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

    @property
    def agent_label(self) -> str:
        return {"claude": "Claude Code", "qoder": "Qoder"}.get(
            self.agent, self.agent
        )

    @property
    def folder(self) -> str:
        path = Path(self.path)
        return str(path.parent if path.is_file() else path)


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


def _read_claude_meta(path: Path) -> tuple[str, datetime | None]:
    cwd = ""
    created: datetime | None = None
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for _ in range(80):
                line = handle.readline(_MAX_META_BYTES)
                if not line:
                    break
                if '"cwd"' not in line and '"timestamp"' not in line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(entry, dict):
                    continue
                candidate = entry.get("cwd")
                if not cwd and isinstance(candidate, str) and candidate.strip():
                    cwd = candidate.strip()
                if created is None:
                    created = _parse_time(entry.get("timestamp"))
                if cwd and created is not None:
                    break
    except OSError:
        pass
    return cwd, created


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
        cwd, created = _read_claude_meta(path)
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


def _qoder_sessions(root: Path, now: datetime) -> list[AgentSession]:
    if not root.is_dir():
        return []
    sessions: list[AgentSession] = []
    for path in root.glob("*/*/state.json"):
        try:
            stat = path.stat()
        except OSError:
            continue
        state = _load_json(path) or {}
        session_dir = path.parent
        updated = _parse_time(state.get("updatedAt")) or _local(stat.st_mtime) or now
        created = _parse_time(state.get("createdAt"))
        session_id = state.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            session_id = session_dir.name
        folder = session_dir.parent.name
        project_path = ""
        for key in ("cwd", "workspacePath", "projectPath"):
            value = state.get(key)
            if isinstance(value, str) and value.strip():
                project_path = value.strip()
                break
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
