from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt

from agentbell.agent_sessions import (
    AgentSession,
    AgentSessionScanner,
    parse_session_transcript,
    scan_sessions,
    transcript_to_markdown,
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
        codex_root=tmp_path / "missing-codex",
        gemini_root=tmp_path / "missing-gemini",
        grok_root=tmp_path / "missing-grok",
        opencode_db=tmp_path / "missing-opencode.db",
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


def write_transcript(path: Path, entries: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    return path


def transcript_entries() -> list[dict]:
    return [
        {
            "type": "summary",
            "cwd": "E:\\opt\\demo",
            "timestamp": "2026-10-30T08:00:00Z",
        },
        {
            "type": "user",
            "cwd": "E:\\opt\\demo",
            "timestamp": "2026-10-30T08:00:00Z",
            "message": {
                "content": [{"type": "text", "text": "帮我重构设置页的布局"}]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:00:05Z",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "先看看现有布局再动手"},
                    {"type": "text", "text": "我先读取设置页代码。"},
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Read",
                        "input": {"file_path": "agentbell/ui/settings.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:00:07Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t1",
                        "content": "1 from __future__ ...",
                    }
                ]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:00:12Z",
            "message": {
                "content": [{"type": "text", "text": "布局已调整完成。"}]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:02:00Z",
            "message": {
                "content": [{"type": "text", "text": "再补一组单元测试"}]
            },
        },
        {
            "type": "assistant",
            "timestamp": "2026-10-30T08:02:05Z",
            "message": {
                "content": [
                    {"type": "text", "text": "已补充设置页布局测试。"},
                    {
                        "type": "tool_use",
                        "id": "t2",
                        "name": "Write",
                        "input": {"file_path": "tests/test_settings.py"},
                    },
                ]
            },
        },
        {
            "type": "user",
            "timestamp": "2026-10-30T08:02:09Z",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t2",
                        "is_error": True,
                        "content": "permission denied",
                    }
                ]
            },
        },
    ]


def test_scan_extracts_title_from_first_prompt(tmp_path):
    claude_root = tmp_path / "claude-root"
    with_title = write_transcript(
        claude_root / "E--opt-demo" / "session-title.jsonl",
        transcript_entries(),
    )
    touch(with_title, datetime(2026, 10, 30, 8, 0, tzinfo=timezone.utc))
    no_prompt = write_transcript(
        claude_root / "E--opt-demo" / "session-empty.jsonl",
        [{"type": "summary", "cwd": "E:\\opt\\demo"}],
    )
    touch(no_prompt, datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc))

    sessions = scan_sessions(claude_root, tmp_path / "missing", max_sessions=10)
    by_id = {item.session_id: item for item in sessions}
    assert by_id["session-title"].title == "帮我重构设置页的布局"
    assert by_id["session-title"].display_title == "帮我重构设置页的布局"
    assert by_id["session-title"].project_path == "E:\\opt\\demo"
    assert by_id["session-title"].created_at is not None
    assert by_id["session-empty"].title == ""
    assert by_id["session-empty"].display_title.startswith("会话 ")


def test_parse_transcript_builds_turns_tools_and_errors(tmp_path):
    path = write_transcript(
        tmp_path / "claude" / "E--opt-demo" / "session-a.jsonl",
        transcript_entries(),
    )
    session = AgentSession(
        agent="claude",
        session_id="session-a",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(path),
        updated_at=datetime(2026, 10, 30, 8, 5, tzinfo=timezone.utc),
        title="帮我重构设置页的布局",
    )

    transcript = parse_session_transcript(session)

    assert transcript.note == ""
    assert transcript.truncated is False
    assert transcript.total_turns == 2
    assert [turn.prompt for turn in transcript.turns] == [
        "帮我重构设置页的布局",
        "再补一组单元测试",
    ]
    first, second = transcript.turns
    assert first.tool_calls == 1
    assert first.files == 0
    assert first.tool_failures == 0
    assert [item.kind for item in first.items] == [
        "thinking",
        "text",
        "tool",
        "result",
        "text",
    ]
    tool = first.items[2]
    assert tool.name == "Read"
    assert tool.text == "agentbell/ui/settings.py"
    result = first.items[3]
    assert result.name == "Read"
    assert result.error is False
    assert second.tool_calls == 1
    assert second.files == 1
    assert second.tool_failures == 1
    assert second.items[-1].error is True
    assert second.items[-1].name == "Write"


def test_transcript_markdown_contains_sections(tmp_path):
    path = write_transcript(
        tmp_path / "claude" / "E--opt-demo" / "session-a.jsonl",
        transcript_entries(),
    )
    session = AgentSession(
        agent="claude",
        session_id="session-a",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(path),
        updated_at=datetime(2026, 10, 30, 8, 5, tzinfo=timezone.utc),
        title="帮我重构设置页的布局",
    )
    markdown = transcript_to_markdown(parse_session_transcript(session))

    assert markdown.startswith("# 帮我重构设置页的布局")
    assert "## 1. 帮我重构设置页的布局" in markdown
    assert "**工具 · Read**" in markdown
    assert "**工具结果 · 失败 · Write**" in markdown
    assert "> 思考" in markdown
    assert "```\npermission denied\n```" in markdown


def test_parse_transcript_handles_missing_file(tmp_path):
    session = AgentSession(
        agent="qoder",
        session_id="missing",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(tmp_path / "nowhere"),
        updated_at=datetime(2026, 10, 30, 8, 5, tzinfo=timezone.utc),
    )
    transcript = parse_session_transcript(session)
    assert transcript.turns == ()
    assert "未找到" in transcript.note


def write_codex_session(
    root: Path, session_id: str, cwd: str, timestamp: str
) -> Path:
    folder = root / "2026" / "10" / "30"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-30T08-00-00-{session_id}.jsonl"
    entries = [
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {"session_id": session_id, "cwd": cwd, "timestamp": timestamp},
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<environment_context>\n<cwd>E:\\opt\\demo</cwd>\n"
                        "</environment_context>",
                    }
                ],
            },
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "帮我检查 Codex 会话"}],
            },
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "我先看一下。"}],
            },
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "c1",
                "name": "exec",
                "input": "ls",
            },
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call_output",
                "call_id": "c1",
                "output": [{"type": "input_text", "text": "a.txt"}],
            },
        },
        {
            "timestamp": timestamp,
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "继续"}],
            },
        },
    ]
    return write_transcript(path, entries)


def write_gemini_session(
    root: Path,
    slug: str,
    session_id: str,
    project_path: str,
    timestamp: str,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root.parent / "projects.json").write_text(
        json.dumps({"projects": {project_path: slug}}),
        encoding="utf-8",
    )
    folder = root / slug / "chats"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"session-2026-10-30T08-00-00-{session_id[:8]}.json"
    path.write_text(
        json.dumps(
            {
                "sessionId": session_id,
                "startTime": timestamp,
                "lastUpdated": timestamp,
                "messages": [
                    {
                        "type": "user",
                        "timestamp": timestamp,
                        "content": [
                            {
                                "text": "<session_context>\nThis is the Gemini CLI."
                                "\n</session_context>"
                            }
                        ],
                    },
                    {
                        "type": "user",
                        "timestamp": timestamp,
                        "content": [{"text": "梳理 Gemini 会话"}],
                    },
                    {
                        "type": "gemini",
                        "timestamp": timestamp,
                        "content": "我来梳理。",
                        "toolCalls": [
                            {
                                "id": "g1",
                                "name": "read_file",
                                "args": {"path": "a.py"},
                                "status": "success",
                                "result": [{"text": "print(1)"}],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def write_grok_session(
    root: Path,
    session_id: str,
    project_path: str,
    timestamp: str,
) -> Path:
    folder_path = root / urllib.parse.quote(project_path, safe="") / session_id
    folder_path.mkdir(parents=True, exist_ok=True)
    (folder_path / "summary.json").write_text(
        json.dumps(
            {
                "generated_title": "Grok 会话标题",
                "num_chat_messages": 4,
                "git_root_dir": project_path,
                "created_at": timestamp,
                "updated_at": timestamp,
                "last_active_at": timestamp,
            }
        ),
        encoding="utf-8",
    )
    return write_transcript(
        folder_path / "chat_history.jsonl",
        [
            {"type": "system", "content": "You are Grok."},
            {
                "type": "user",
                "content": [{"type": "text", "text": "<user_info>OS: windows</user_info>"}],
            },
            {
                "type": "user",
                "content": [
                    {"type": "text", "text": "<user_query>\n排查闲置\n</user_query>"}
                ],
                "prompt_index": 0,
            },
            {
                "type": "reasoning",
                "summary": [{"type": "summary_text", "text": "先查引用"}],
            },
            {
                "type": "assistant",
                "content": "我先查一下。",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "grep",
                        "arguments": '{"pattern":"duckdb"}',
                    }
                ],
            },
            {
                "type": "tool_result",
                "tool_call_id": "call-1",
                "content": "found",
            },
        ],
    )


def write_opencode_db(
    path: Path, session_id: str, project_path: str, title: str, updated_ms: int
) -> Path:
    import sqlite3

    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE session (id text primary key, directory text, title text, "
        "time_created integer, time_updated integer, time_archived integer)"
    )
    connection.execute(
        "INSERT INTO session VALUES (?, ?, ?, ?, ?, 0)",
        (session_id, project_path, title, updated_ms, updated_ms),
    )
    connection.commit()
    connection.close()
    return path


def test_scan_sessions_covers_codex_gemini_grok_and_opencode(tmp_path):
    claude_root = tmp_path / "claude-root"
    qoder_root = tmp_path / "qoder-root"
    codex_root = tmp_path / "codex-root"
    gemini_root = tmp_path / "gemini-root" / "tmp"
    grok_root = tmp_path / "grok-root"
    opencode_db = tmp_path / "opencode" / "opencode.db"

    claude_file = write_claude_session(
        claude_root, "E--opt-demo", "claude-1", "E:\\opt\\demo", "2026-10-01T00:00:00Z"
    )
    touch(claude_file, datetime(2026, 10, 1, tzinfo=timezone.utc))
    write_qoder_session(
        qoder_root,
        "E--opt-demo",
        "qoder-1",
        "2026-10-01T00:00:00Z",
        "2026-10-02T00:00:00Z",
    )
    codex_file = write_codex_session(
        codex_root, "codex-1", "E:\\opt\\demo", "2026-10-03T00:00:00Z"
    )
    touch(codex_file, datetime(2026, 10, 3, tzinfo=timezone.utc))
    write_gemini_session(
        gemini_root,
        "demo-gemini",
        "gemini-1",
        "E:\\opt\\gemini-app",
        "2026-10-04T00:00:00Z",
    )
    write_grok_session(
        grok_root,
        "grok-1",
        "E:\\opt\\argus",
        "2026-10-05T00:00:00Z",
    )
    write_opencode_db(
        opencode_db,
        "opencode-1",
        "E:\\opt\\opencode-app",
        "OpenCode 会话标题",
        1_792_000_000_000,
    )

    sessions = scan_sessions(
        claude_root,
        qoder_root,
        max_sessions=10,
        codex_root=codex_root,
        gemini_root=gemini_root,
        grok_root=grok_root,
        opencode_db=opencode_db,
    )

    assert [item.agent for item in sessions] == [
        "opencode",
        "grok",
        "gemini",
        "codex",
        "qoder",
        "claude",
    ]
    by_agent = {item.agent: item for item in sessions}
    assert by_agent["codex"].agent_label == "Codex"
    assert by_agent["codex"].session_id == "codex-1"
    assert by_agent["codex"].project == "demo"
    assert by_agent["codex"].title == "帮我检查 Codex 会话"
    assert by_agent["gemini"].agent_label == "Gemini CLI"
    assert by_agent["gemini"].project == "gemini-app"
    assert by_agent["gemini"].title == "梳理 Gemini 会话"
    assert by_agent["gemini"].message_count == 3
    assert by_agent["grok"].agent_label == "Grok"
    assert by_agent["grok"].project == "argus"
    assert by_agent["grok"].title == "Grok 会话标题"
    assert by_agent["grok"].message_count == 4
    assert by_agent["opencode"].agent_label == "OpenCode"
    assert by_agent["opencode"].project == "opencode-app"
    assert by_agent["opencode"].title == "OpenCode 会话标题"
    assert by_agent["opencode"].folder == "E:\\opt\\opencode-app"


def test_parse_transcript_normalizes_codex_gemini_and_grok(tmp_path):
    codex = AgentSession(
        agent="codex",
        session_id="codex-1",
        project="demo",
        project_path="E:\\opt\\demo",
        path=str(
            write_codex_session(
                tmp_path / "codex", "codex-1", "E:\\opt\\demo", "2026-10-03T00:00:00Z"
            )
        ),
        updated_at=datetime(2026, 10, 3, tzinfo=timezone.utc),
    )
    codex_transcript = parse_session_transcript(codex)
    assert [turn.prompt for turn in codex_transcript.turns] == [
        "帮我检查 Codex 会话",
        "继续",
    ]
    assert codex_transcript.turns[0].tool_calls == 1
    assert codex_transcript.turns[0].items[-1].name == "exec"
    assert codex_transcript.turns[0].items[-1].text == "a.txt"

    gemini_path = write_gemini_session(
        tmp_path / "gemini" / "tmp",
        "demo-gemini",
        "gemini-1",
        "E:\\opt\\gemini-app",
        "2026-10-04T00:00:00Z",
    )
    gemini = AgentSession(
        agent="gemini",
        session_id="gemini-1",
        project="gemini-app",
        project_path="E:\\opt\\gemini-app",
        path=str(gemini_path),
        updated_at=datetime(2026, 10, 4, tzinfo=timezone.utc),
    )
    gemini_transcript = parse_session_transcript(gemini)
    assert [turn.prompt for turn in gemini_transcript.turns] == ["梳理 Gemini 会话"]
    turn = gemini_transcript.turns[0]
    assert [item.kind for item in turn.items] == ["text", "tool", "result"]
    assert turn.items[1].name == "read_file"
    assert turn.items[1].text == "a.py"
    assert turn.items[2].text == "print(1)"

    grok_path = write_grok_session(
        tmp_path / "grok", "grok-1", "E:\\opt\\argus", "2026-10-05T00:00:00Z"
    )
    grok = AgentSession(
        agent="grok",
        session_id="grok-1",
        project="argus",
        project_path="E:\\opt\\argus",
        path=str(grok_path.parent),
        updated_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
    )
    grok_transcript = parse_session_transcript(grok)
    assert [turn.prompt for turn in grok_transcript.turns] == ["排查闲置"]
    items = grok_transcript.turns[0].items
    assert [item.kind for item in items] == ["thinking", "text", "tool", "result"]
    assert items[2].name == "grep"
    assert items[2].text == "duckdb"
    assert items[3].text == "found"


def test_opencode_transcript_is_metadata_only(tmp_path):
    session = AgentSession(
        agent="opencode",
        session_id="opencode-1",
        project="opencode-app",
        project_path="E:\\opt\\opencode-app",
        path="",
        updated_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        title="OpenCode 会话标题",
    )
    transcript = parse_session_transcript(session)
    assert transcript.turns == ()
    assert "数据库" in transcript.note


def test_qoder_scan_prefers_jsonl_and_reads_titles(tmp_path):
    qoder_root = tmp_path / "qoder-root"
    project = qoder_root / "E--opt-demo"
    session_dir = project / "qoder-session-1"
    session_dir.mkdir(parents=True)
    (session_dir / "state.json").write_text(
        json.dumps(
            {
                "sessionId": "qoder-session-1",
                "createdAt": "2026-10-30T08:00:00Z",
                "updatedAt": "2026-10-30T09:00:00Z",
                "cwd": "E:\\opt\\demo",
            }
        ),
        encoding="utf-8",
    )
    write_transcript(project / "qoder-session-1.jsonl", transcript_entries())

    sessions = scan_sessions(tmp_path / "missing", qoder_root, max_sessions=10)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.agent == "qoder"
    assert session.path.endswith("qoder-session-1.jsonl")
    assert session.title == "帮我重构设置页的布局"
    assert session.project == "demo"
    assert session.message_count == len(transcript_entries())
    transcript = parse_session_transcript(session)
    assert len(transcript.turns) == 2
    assert Path(session.folder) == project


def test_session_report_registry_tracks_heartbeats():
    from agentbell.agent_sessions import SessionReport, SessionReportRegistry

    registry = SessionReportRegistry(logging.getLogger("agentbell.tests.sessions"))
    assert registry.report(
        SessionReport(
            session_id="dsh-1",
            title="外部任务",
            project="demo",
            status="running",
        )
    ) is True
    assert registry.count == 1
    sessions = registry.to_agent_sessions()
    assert sessions[0].external is True
    assert sessions[0].path == ""
    assert sessions[0].title == "外部任务"

    assert registry.report(
        SessionReport(session_id="dsh-1", status="ended")
    ) is False
    assert registry.count == 0


def test_session_report_registry_drops_stale_heartbeats():
    from datetime import timedelta

    from agentbell.agent_sessions import SessionReport, SessionReportRegistry

    registry = SessionReportRegistry(
        logging.getLogger("agentbell.tests.sessions"), ttl_seconds=60
    )
    old = datetime.now().astimezone() - timedelta(minutes=30)
    registry.report(SessionReport(session_id="stale", updated_at=old))
    assert registry.count == 1
    assert registry.snapshot(ttl_seconds=60) == []
    assert registry.count == 0
