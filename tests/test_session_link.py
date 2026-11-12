from __future__ import annotations

from datetime import datetime, timedelta

from agentbell.agent_sessions import AgentSession
from agentbell.session_link import SessionLinker, normalize_agent, normalize_path


def make_session(
    path: str,
    *,
    session_id: str = "s-1",
    agent: str = "qoder",
    updated_at: datetime | None = None,
) -> AgentSession:
    return AgentSession(
        agent=agent,
        session_id=session_id,
        project="proj",
        project_path=path,
        path="",
        updated_at=updated_at or datetime.now().astimezone(),
    )


def test_normalize_agent_aliases():
    assert normalize_agent("Qoder") == "qoder"
    assert normalize_agent("Claude Code") == "claude"
    assert normalize_agent("claude-code") == "claude"
    assert normalize_agent("Gemini CLI") == "gemini"
    assert normalize_agent("OpenCode") == "opencode"
    assert normalize_agent("WorkBuddy") == ""


def test_normalize_path_is_stable(tmp_path):
    path = tmp_path / "Demo" / "Sub"
    assert normalize_path(str(path) + "\\") == normalize_path(str(path))
    assert normalize_path("") == ""
    assert normalize_path('"unused"') == normalize_path("unused")


def test_resolve_picks_unique_recent_session(tmp_path):
    project = tmp_path / "proj"
    session = make_session(str(project))
    linker = SessionLinker()
    linker.update([session])
    assert linker.resolve("Qoder", str(project)) is session
    assert linker.resolve("qoder", str(project / "pkg")) is session


def test_resolve_matches_parent_directory(tmp_path):
    project = tmp_path / "proj"
    session = make_session(str(project / "pkg"))
    linker = SessionLinker()
    linker.update([session])
    assert linker.resolve("Qoder", str(project)) is session


def test_resolve_requires_exactly_one_candidate(tmp_path):
    project = tmp_path / "proj"
    linker = SessionLinker()
    linker.update(
        [
            make_session(str(project), session_id="s-1"),
            make_session(str(project), session_id="s-2"),
        ]
    )
    assert linker.resolve("Qoder", str(project)) is None


def test_resolve_skips_stale_and_other_agents(tmp_path):
    project = tmp_path / "proj"
    now = datetime.now().astimezone()
    linker = SessionLinker()
    linker.update(
        [
            make_session(
                str(project),
                session_id="stale",
                updated_at=now - timedelta(minutes=31),
            )
        ]
    )
    assert linker.resolve("Qoder", str(project), now) is None

    linker.update(
        [
            make_session(
                str(project), session_id="claude", agent="claude", updated_at=now
            )
        ]
    )
    assert linker.resolve("Qoder", str(project), now) is None
    assert linker.resolve("Claude Code", str(project), now) is not None


def test_resolve_ignores_unrelated_directory_and_missing_input(tmp_path):
    linker = SessionLinker()
    linker.update([make_session(str(tmp_path / "proj"))])
    assert linker.resolve("Qoder", str(tmp_path / "other")) is None
    assert linker.resolve("Qoder", "") is None
    assert linker.resolve("", str(tmp_path / "proj")) is None


def test_resolve_handles_naive_timestamps(tmp_path):
    project = tmp_path / "proj"
    now = datetime.now().astimezone()
    linker = SessionLinker()
    linker.update(
        [
            make_session(
                str(project),
                updated_at=(now - timedelta(minutes=5)).replace(tzinfo=None),
            )
        ]
    )
    assert linker.resolve("Qoder", str(project), now) is not None


def test_update_keeps_newest_duplicate(tmp_path):
    project = tmp_path / "proj"
    now = datetime.now().astimezone()
    older = make_session(str(project), updated_at=now - timedelta(minutes=10))
    newer = make_session(str(project), updated_at=now)
    linker = SessionLinker()
    linker.update([older, newer])
    assert linker.snapshot() == (newer,)
