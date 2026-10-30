from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbell.agent_launch import (
    AgentAvailability,
    LaunchResult,
    agent_spec,
    discover_agents,
    launch_agent,
    launch_focus_value,
)
from agentbell.window_focus import parse_focus_value


def _availability(agent_id: str, executable: str = "") -> AgentAvailability:
    spec = agent_spec(agent_id)
    assert spec is not None
    return AgentAvailability(spec=spec, executable=executable)


def test_discover_agents_puts_installed_first_and_detects_cli():
    paths = {"claude": r"C:\npm\claude.cmd", "pi": r"C:\npm\pi.cmd"}

    def fake_which(command, path=""):
        return paths.get(command)

    found = discover_agents(env={"PATH": "x"}, which=fake_which, exists=lambda _: False)

    assert [item.spec.id for item in found[:2]] == ["claude-code", "pi"]
    assert all(item.installed for item in found[:2])
    assert all(not item.installed for item in found[2:])
    assert len(found) == 11


def test_discover_agents_detects_desktop_path(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\AppData\Local")
    target = r"C:\AppData\Local\Programs\Antigravity\Antigravity.exe"

    found = discover_agents(
        env={"PATH": ""},
        which=lambda *args, **kwargs: None,
        exists=lambda path: path == target,
    )

    antigravity = next(item for item in found if item.spec.id == "antigravity")
    assert antigravity.installed is True
    assert antigravity.executable == target
    assert antigravity.kind_label == "桌面应用"


def test_launch_missing_agent_is_rejected(tmp_path):
    result = launch_agent(_availability("claude-code"), str(tmp_path), "hi")

    assert result.ok is False
    assert "未检测到 Claude Code" in result.message


def test_launch_rejects_missing_project(tmp_path):
    result = launch_agent(
        _availability("claude-code", r"C:\npm\claude.cmd"),
        str(tmp_path / "missing"),
    )

    assert result.ok is False
    assert "项目目录不存在" in result.message


@pytest.mark.skipif(os.name != "nt", reason="terminal launch is Windows-only")
def test_launch_cli_uses_static_script_and_env(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=4321)

    project = tmp_path / "demo"
    project.mkdir()
    prompt = '请阅读项目，然后总结；带 & 中文 " 引号'
    result = launch_agent(
        _availability("claude-code", r"C:\npm\claude.cmd"),
        str(project),
        prompt,
        env=dict(os.environ),
        popen=fake_popen,
    )

    assert result.ok is True
    assert result.pid == 4321
    assert result.prompt_sent is True
    assert result.agent_kind == "cli"
    args = captured["args"]
    kwargs = captured["kwargs"]
    assert args[0].lower().endswith("powershell.exe")
    script = args[-1]
    assert "AGENTBELL_PROMPT" in script
    assert prompt not in script
    assert prompt not in " ".join(args)
    assert kwargs["env"]["AGENTBELL_PROMPT"] == prompt
    assert kwargs["env"]["AGENTBELL_EXE"] == r"C:\npm\claude.cmd"
    assert kwargs["cwd"] == str(project)
    assert kwargs["creationflags"] == subprocess.CREATE_NEW_CONSOLE


@pytest.mark.skipif(os.name != "nt", reason="terminal launch is Windows-only")
def test_launch_cli_without_prompt_has_empty_prompt_env(tmp_path):
    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=7)

    project = tmp_path / "demo"
    project.mkdir()
    result = launch_agent(
        _availability("codex", r"C:\npm\codex.cmd"),
        str(project),
        "   ",
        env=dict(os.environ),
        popen=fake_popen,
    )

    assert result.ok is True
    assert result.prompt_sent is False
    assert captured["kwargs"]["env"]["AGENTBELL_PROMPT"] == ""


def test_launch_desktop_app_does_not_send_prompt(tmp_path):
    captured: dict[str, object] = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(pid=99)

    project = tmp_path / "demo"
    project.mkdir()
    result = launch_agent(
        _availability("claude-desktop", r"C:\Claude\Claude.exe"),
        str(project),
        "写一份报告",
        env={"PATH": ""},
        popen=fake_popen,
    )

    assert result.ok is True
    assert result.prompt_sent is False
    assert captured["args"] == [r"C:\Claude\Claude.exe"]
    assert "AGENTBELL_PROMPT" not in captured["kwargs"]["env"]
    assert "不支持自动预填" in result.message
    assert result.agent_kind == "desktop"


def test_launch_rejects_null_prompt(tmp_path):
    result = launch_agent(
        _availability("claude-code", r"C:\npm\claude.cmd"),
        str(tmp_path),
        "bad\x00prompt",
    )

    assert result.ok is False
    assert "无效字符" in result.message


def test_launch_rejects_oversized_prompt(tmp_path):
    result = launch_agent(
        _availability("claude-code", r"C:\npm\claude.cmd"),
        str(tmp_path),
        "x" * 8001,
    )

    assert result.ok is False
    assert "8000" in result.message


def test_launch_focus_value_round_trips():
    result = LaunchResult(
        ok=True,
        message="done",
        agent_id="codex",
        agent_name="Codex",
        agent_kind="cli",
        pid=321,
        title="AgentBell · Codex · demo",
        working_dir=r"E:\work\demo",
    )

    value = launch_focus_value(result)
    target = parse_focus_value(value)

    assert target is not None
    assert target.pid == 321
    assert target.window_title == "AgentBell · Codex · demo"
    assert target.working_dir == r"E:\work\demo"
    assert json.loads(value)["pid"] == 321
    assert result.focus_request() is not None


def test_desktop_result_without_pid_has_no_focus_request(tmp_path):
    result = LaunchResult(ok=True, message="opened", pid=0)

    assert result.focus_request() is None
    assert launch_focus_value(result) == ""
