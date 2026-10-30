from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt

from agentbell.agent_sessions import (
    AgentSessionScanner,
    scan_sessions,
)
from agentbell.config import AgentSessionsConfig


def write_claude_session(
    root: Path,
    project: str,
    session_id: str,
    cwd: str,
    timestamp: str,
    lines: int = 3,
) -> Path:
    folder = root / project
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    entries = [{"type": "summary", "cwd": cwd, "timestamp": timestamp}]
    entries.extend({"type": "user", "message": {"content": "hello"}} for _ in range(lines))
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    return path


def write_qoder_session(
    root: Path,
    project: str,
    session_id: str,
    created: str,
    updated: str,
) -> Path:
    folder = root / project / session_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "state.json"
    path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "createdAt": created,
                "updatedAt": updated,
                "items": {"s0": {"c": created, "u": updated}},
            }
        ),
        encoding="utf-8",
    )
    return path


def touch(path: Path, when: datetime) -> None:
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def test_scan_sessions_reads_metadata_only(tmp_path):
    claude_root = tmp_path / "claude-root"
    qoder_root = tmp_path / "qoder-root"
    claude_file = write_claude_session(
        claude_root,
        "E--opt-demo-api",
        "claude-session-1",
        "E:\\opt\\demo\\api",
        "2026-10-29T10:00:00Z",
        lines=4,
    )
    touch(claude_file, datetime(2026, 10, 1, tzinfo=timezone.utc))
    write_qoder_session(
        qoder_root,
        "E--opt-demo-web",
        "qoder-session-1",
        "2026-10-29T09:00:00.000Z",
        "2026-10-30T01:00:00.000Z",
    )

    sessions = scan_sessions(claude_root, qoder_root, max_sessions=10)

    assert [item.agent for item in sessions] == ["qoder", "claude"]
    qoder, claude = sessions
    assert qoder.agent_label == "Qoder"
    assert qoder.project == "web"
    assert qoder.project_path == "E:\\opt\\demo\\web"
    assert qoder.session_id == "qoder-session-1"
    assert qoder.message_count == 0
    assert qoder.created_at is not None
    assert qoder.updated_at > qoder.created_at
    assert Path(qoder.path).is_dir()
    assert Path(qoder.folder) == Path(qoder.path)

    assert claude.agent_label == "Claude Code"
    assert claude.project == "api"
    assert claude.project_path == "E:\\opt\\demo\\api"
    assert claude.session_id == "claude-session-1"
    assert claude.message_count == 5
    assert claude.created_at is not None
    assert claude.size_bytes > 0
    assert Path(claude.folder) == Path(claude.path).parent


def test_scan_sessions_sorts_by_update_and_limits(tmp_path):
    claude_root = tmp_path / "claude-root"
    qoder_root = tmp_path / "qoder-root"
    for index in range(3):
        path = write_claude_session(
            claude_root,
            "E--opt-demo",
            f"session-{index}",
            "E:\\opt\\demo",
            f"2026-10-2{index}T10:00:00Z",
        )
        touch(path, datetime(2026, 10, index + 1, tzinfo=timezone.utc))
    write_qoder_session(
        qoder_root,
        "E--opt-demo",
        "qoder-latest",
        "2026-10-01T00:00:00Z",
        "2026-10-30T12:00:00Z",
    )

    sessions = scan_sessions(claude_root, qoder_root, max_sessions=2)
    assert len(sessions) == 2
    assert sessions[0].session_id == "qoder-latest"
    assert sessions[1].session_id == "session-2"


def test_scan_sessions_handles_missing_roots(tmp_path):
    sessions = scan_sessions(
        tmp_path / "missing-claude", tmp_path / "missing-qoder", max_sessions=10
    )
    assert sessions == []


def test_scanner_emits_results_on_background_thread(tmp_path):
    claude_root = tmp_path / "claude-root"
    qoder_root = tmp_path / "qoder-root"
    write_claude_session(
        claude_root,
        "E--opt-demo",
        "session-a",
        "E:\\opt\\demo",
        "2026-10-30T00:00:00Z",
    )
    scanner = AgentSessionScanner(
        AgentSessionsConfig(enabled=True, scan_interval_seconds=30),
        logging.getLogger("agentbell.tests"),
        claude_root=claude_root,
        qoder_root=qoder_root,
    )
    received: list[list] = []
    scanner.scanned.connect(received.append, Qt.ConnectionType.DirectConnection)
    try:
        scanner.start()
        deadline = time.time() + 5
        while not received and time.time() < deadline:
            time.sleep(0.01)
        assert received
        assert [item.session_id for item in received[0]] == ["session-a"]
    finally:
        scanner.stop()
    assert scanner._thread is None


def test_parse_time_supports_iso_and_epoch():
    from agentbell.agent_sessions import _parse_time

    iso = _parse_time("2026-10-29T10:00:00Z")
    assert iso is not None
    assert iso.astimezone(timezone.utc) == datetime(
        2026, 10, 29, 10, 0, tzinfo=timezone.utc
    )
    epoch = _parse_time(1_790_000_000_000)
    assert epoch is not None
    assert epoch.year >= 2026
    assert _parse_time("not-a-time") is None
