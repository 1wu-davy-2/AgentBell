from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timedelta

from .agent_sessions import AgentSession

DEFAULT_LINK_WINDOW = timedelta(minutes=30)

_AGENT_ALIASES = {
    "claude": "claude",
    "claudecode": "claude",
    "qoder": "qoder",
    "codex": "codex",
    "gemini": "gemini",
    "geminicli": "gemini",
    "grok": "grok",
    "opencode": "opencode",
    "deepseek": "deepseek",
}


def normalize_agent(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "", (value or "").lower())
    return _AGENT_ALIASES.get(key, "")


def normalize_path(value: str) -> str:
    text = (value or "").strip().strip('"').strip("'")
    if not text:
        return ""
    try:
        text = os.path.abspath(os.path.expanduser(text))
    except (OSError, ValueError):
        return ""
    text = os.path.normcase(os.path.normpath(text))
    return text.rstrip("\\/") or text


def _paths_overlap(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    separator = os.sep
    return left.startswith(right + separator) or right.startswith(left + separator)


class SessionLinker:
    """Links a notification to one active session without guessing.

    A link is produced only when the sender's agent matches, the project
    directory and the sender's working directory overlap, the session was
    updated inside the freshness window, and exactly one session matches all
    of the above.
    """

    def __init__(
        self,
        logger: logging.Logger | None = None,
        *,
        window: timedelta = DEFAULT_LINK_WINDOW,
    ) -> None:
        self._logger = logger or logging.getLogger("agentbell.session_link")
        self._window = window
        self._sessions: tuple[AgentSession, ...] = ()
        self._lock = threading.RLock()

    def update(self, sessions: list[AgentSession]) -> None:
        unique: dict[tuple[str, str], AgentSession] = {}
        for session in sessions:
            key = (session.agent, session.session_id)
            if not session.session_id:
                continue
            existing = unique.get(key)
            if existing is None or existing.updated_at <= session.updated_at:
                unique[key] = session
        with self._lock:
            self._sessions = tuple(unique.values())

    def snapshot(self) -> tuple[AgentSession, ...]:
        with self._lock:
            return self._sessions

    def resolve(
        self,
        source: str,
        working_dir: str,
        now: datetime | None = None,
    ) -> AgentSession | None:
        agent = normalize_agent(source)
        target = normalize_path(working_dir)
        if not agent or not target:
            return None
        current = now or datetime.now().astimezone()
        if current.tzinfo is None:
            current = current.astimezone()
        cutoff = current - self._window
        candidates: list[AgentSession] = []
        for session in self.snapshot():
            if normalize_agent(session.agent) != agent:
                continue
            project_path = normalize_path(session.project_path)
            if not _paths_overlap(target, project_path):
                continue
            updated = session.updated_at
            if updated.tzinfo is None:
                updated = updated.astimezone()
            if updated < cutoff:
                continue
            candidates.append(session)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            self._logger.info(
                "会话自动关联跳过：%s 在 %s 内有 %d 个候选会话",
                agent,
                working_dir,
                len(candidates),
            )
        return None
