from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from agentbell import hook_cli


def _run(tmp_path, payload, capsys, agent="claude"):
    config = tmp_path / "config.json"
    if not config.exists():
        config.write_text(json.dumps({"port": 8799}), encoding="utf-8")
    code = hook_cli.main(
        [
            "--hook",
            "--agent",
            agent,
            "--config",
            str(config),
            "--dry-run",
            json.dumps(payload, ensure_ascii=True),
        ]
    )
    assert code == 0
    output = capsys.readouterr().out.strip()
    return json.loads(output) if output else None


def test_hook_cli_maps_permission_notification(tmp_path, capsys):
    data = _run(
        tmp_path,
        {
            "hook_event_name": "Notification",
            "session_id": "s1",
            "cwd": str(tmp_path),
            "message": "Claude needs your permission to use Bash",
        },
        capsys=capsys,
    )
    assert data["target"] == "http://127.0.0.1:8799/notify"
    body = data["body"]
    assert body["title"] == "Claude Code 等待权限确认"
    assert body["needs_input"] is True
    assert body["wait_reason"] == "permission"
    assert body["wait_source"] == "explicit"
    assert body["phase"] == "waiting_input"
    assert body["session_id"] == "s1"
    assert [action["kind"] for action in body["actions"]] == ["session", "timeline"]


def test_hook_cli_links_start_and_finish_turns(tmp_path, capsys):
    started = _run(
        tmp_path,
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s2",
            "cwd": str(tmp_path),
        },
        capsys=capsys,
    )["body"]
    assert started["phase"] == "started"
    assert started["silent"] is True
    assert "actions" not in started

    state_file = tmp_path / "hooks" / "state" / "claude-s2.json"
    assert state_file.is_file()

    finished = _run(
        tmp_path,
        {
            "hook_event_name": "Stop",
            "session_id": "s2",
            "last_assistant_message": "All tests passed",
        },
        capsys=capsys,
    )["body"]
    assert finished["status"] == "succeeded"
    assert finished["summary"] == "All tests passed"
    assert finished["dedupe_key"] == started["dedupe_key"]
    assert not state_file.exists()


def test_hook_cli_codex_completion_payload(tmp_path, capsys):
    data = _run(
        tmp_path,
        {
            "type": "agent-turn-complete",
            "turn-id": "turn-42",
            "thread-id": "thread-7",
            "last-assistant-message": "Codex finished",
        },
        agent="codex",
        capsys=capsys,
    )
    body = data["body"]
    assert body["title"] == "Codex 已完成"
    assert body["status"] == "succeeded"
    assert body["phase"] == "finished"
    assert body["session_id"] == "thread-7"
    assert "turn-42" in body["dedupe_key"]


def test_hook_cli_ignores_unknown_events_and_completion_notifications(tmp_path, capsys):
    assert (
        _run(
            tmp_path,
            {"hook_event_name": "PreToolUse", "session_id": "s3"},
            capsys=capsys,
        )
        is None
    )
    assert (
        _run(
            tmp_path,
            {
                "hook_event_name": "Notification",
                "notification_type": "task_complete",
            },
            agent="grok",
            capsys=capsys,
        )
        is None
    )


@pytest.mark.skipif(os.name == "nt", reason="Linux path layout")
def test_hook_cli_linux_source_command_is_quoted(tmp_path):
    from agentbell import hooks

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    root = tmp_path / "app"
    root.mkdir()
    plan = hooks.plan_install("claude", home=home, root=root)
    assert "--hook" in plan.preview
    assert "--agent claude" in " ".join(plan.preview.split())
    assert str(Path(sys.executable).resolve()) in plan.preview
    assert "run.py" in plan.preview
