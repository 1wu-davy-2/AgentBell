from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agentbell import hooks

POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
requires_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="Windows PowerShell is required for helper tests"
)


def _make_env(base: Path, *, dirs: tuple[str, ...] = (".claude", ".gemini", ".grok", ".codex")) -> tuple[Path, Path]:
    home = base / "home"
    root = base / "app"
    root.mkdir(parents=True, exist_ok=True)
    for name in dirs:
        (home / name).mkdir(parents=True, exist_ok=True)
    return home, root


def _installed(command: str) -> bool:
    return hooks._is_agentbell_handler({"command": command})


def _commands(data: dict) -> list[str]:
    commands: list[str] = []
    for groups in (data.get("hooks") or {}).values():
        for group in groups:
            for handler in group.get("hooks", []):
                command = handler.get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def _run_helper(
    helper: Path,
    config: Path,
    agent: str,
    payload: dict | None,
    *,
    as_argument: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    command = [
        POWERSHELL,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper),
        "-Agent",
        agent,
        "-ConfigPath",
        str(config),
        "-DryRun",
    ]
    stdin = ""
    if payload is not None:
        encoded = json.dumps(payload, ensure_ascii=True)
        if as_argument:
            command.append(encoded)
        else:
            stdin = encoded
    result = subprocess.run(
        command,
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _helper_body(helper: Path, config: Path, agent: str, payload: dict) -> dict:
    output = _run_helper(helper, config, agent, payload)
    assert output, "helper produced no output"
    data = json.loads(output)
    assert set(data) == {"target", "body"}
    return data


def test_helper_script_is_utf8_bom() -> None:
    source = hooks.helper_source()
    assert source.is_file()
    assert source.read_bytes().startswith(b"\xef\xbb\xbf")


def test_hook_statuses_detects_agents(tmp_path):
    home, root = _make_env(tmp_path)
    statuses = hooks.hook_statuses(home=home, root=root)
    assert [status.agent.id for status in statuses] == [
        "claude",
        "gemini",
        "grok",
        "codex",
    ]
    assert all(status.detected for status in statuses)
    assert not any(status.installed for status in statuses)
    assert statuses[-1].agent.support == "partial"


def test_hook_statuses_without_cli_dirs(tmp_path):
    home, root = _make_env(tmp_path, dirs=())
    statuses = hooks.hook_statuses(home=home, root=root)
    assert not any(status.detected for status in statuses)
    assert all("未检测到" in status.summary for status in statuses)


def test_claude_install_preserves_existing_and_uninstall_restores(tmp_path):
    home, root = _make_env(tmp_path)
    settings = home / ".claude" / "settings.json"
    original = {
        "permissions": {"allow": ["Bash"]},
        "mcpServers": {"demo": {"command": "node"}},
        "hooks": {
            "Stop": [
                {
                    "hooks": [
                        {"type": "command", "command": "echo user-hook"}
                    ]
                }
            ]
        },
    }
    settings.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

    plan = hooks.plan_install("claude", home=home, root=root)
    assert plan.backup_path is not None
    assert plan.backup_path.name.startswith("settings.json" + hooks.BACKUP_SUFFIX)
    assert "echo user-hook" not in plan.preview or "保留已有 hook：1" in plan.preview
    assert "UserPromptSubmit" in plan.preview
    assert not plan.backup_path.exists()

    result = hooks.install_hook("claude", home=home, root=root)
    assert result.changed is True
    assert result.backup_path is not None and result.backup_path.is_file()
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["permissions"] == {"allow": ["Bash"]}
    assert data["mcpServers"] == {"demo": {"command": "node"}}
    stop_commands = [
        handler["command"]
        for group in data["hooks"]["Stop"]
        for handler in group["hooks"]
    ]
    assert "echo user-hook" in stop_commands
    assert any(_installed(command) for command in stop_commands)
    for event in ("UserPromptSubmit", "Notification", "Stop"):
        commands = [
            handler.get("command", "")
            for group in data["hooks"][event]
            for handler in group["hooks"]
        ]
        assert sum(_installed(command) for command in commands) == 1
        assert all(
            handler.get("timeout") == 10
            for group in data["hooks"][event]
            for handler in group["hooks"]
            if _installed(handler.get("command", ""))
        )
    if os.name == "nt":
        assert "powershell.exe" in stop_commands[-1]
        assert "-Agent claude" in stop_commands[-1]
    else:
        assert "--hook" in stop_commands[-1]
        assert "--agent claude" in stop_commands[-1]

    again = hooks.install_hook("claude", home=home, root=root)
    assert again.changed is False
    assert again.backup_path is None

    removed = hooks.uninstall_hook("claude", home=home, root=root)
    assert removed.changed is True
    assert removed.backup_path is not None
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert restored["permissions"] == original["permissions"]
    assert restored["mcpServers"] == original["mcpServers"]
    assert not any(_installed(command) for command in _commands(restored))
    assert "echo user-hook" in _commands(restored)
    status = hooks.hook_statuses(home=home, root=root)[0]
    assert status.installed is False


def test_gemini_install_creates_settings_and_removes_hooks(tmp_path):
    home, root = _make_env(tmp_path)
    settings = home / ".gemini" / "settings.json"
    assert not settings.exists()

    result = hooks.install_hook("gemini", home=home, root=root)
    assert result.changed is True
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert set(data["hooks"]) == {"BeforeAgent", "Notification", "AfterAgent"}

    removed = hooks.uninstall_hook("gemini", home=home, root=root)
    assert removed.changed is True
    assert json.loads(settings.read_text(encoding="utf-8")) == {}


def test_grok_merges_user_hooks_and_keeps_file(tmp_path):
    home, root = _make_env(tmp_path)
    hook_file = home / ".grok" / "hooks" / "agentbell.json"
    hook_file.parent.mkdir(parents=True)
    hook_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo user-grok"}
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = hooks.install_hook("grok", home=home, root=root)
    assert result.changed is True
    data = json.loads(hook_file.read_text(encoding="utf-8"))
    assert "echo user-grok" in _commands(data)
    assert "StopFailure" in data["hooks"]
    assert "StopCancelled" in data["hooks"]

    removed = hooks.uninstall_hook("grok", home=home, root=root)
    assert removed.changed is True
    data = json.loads(hook_file.read_text(encoding="utf-8"))
    assert "echo user-grok" in _commands(data)
    assert not any(_installed(command) for command in _commands(data))

    hook_file.write_text(
        json.dumps({"hooks": {}}, ensure_ascii=False), encoding="utf-8"
    )
    hooks.install_hook("grok", home=home, root=root)
    hooks.uninstall_hook("grok", home=home, root=root)
    assert not hook_file.exists()


def test_codex_notify_is_inserted_before_tables_and_undone(tmp_path):
    home, root = _make_env(tmp_path)
    config = home / ".codex" / "config.toml"
    original = 'model = "gpt-5"\n\n[model_providers.custom]\nname = "demo"\n'
    config.write_text(original, encoding="utf-8")

    plan = hooks.plan_install("codex", home=home, root=root)
    assert plan.warnings
    assert "notify" in plan.preview

    result = hooks.install_hook("codex", home=home, root=root)
    assert result.changed is True
    text = config.read_text(encoding="utf-8")
    assert text.index("notify =") < text.index("[model_providers.custom]")
    data = __import__("tomllib").loads(text)
    assert data["model"] == "gpt-5"
    assert data["model_providers"]["custom"]["name"] == "demo"
    if os.name == "nt":
        assert any("agentbell-hook.ps1" in item for item in data["notify"])
    else:
        assert any("--hook" in item for item in data["notify"])

    again = hooks.install_hook("codex", home=home, root=root)
    assert again.changed is False
    assert again.backup_path is None

    removed = hooks.uninstall_hook("codex", home=home, root=root)
    assert removed.changed is True
    assert config.read_text(encoding="utf-8") == original


def test_codex_existing_notify_is_not_overwritten(tmp_path):
    home, root = _make_env(tmp_path)
    config = home / ".codex" / "config.toml"
    original = 'notify = ["echo", "mine"]\n'
    config.write_text(original, encoding="utf-8")

    with pytest.raises(hooks.HookError, match="notify"):
        hooks.plan_install("codex", home=home, root=root)
    with pytest.raises(hooks.HookError, match="notify"):
        hooks.install_hook("codex", home=home, root=root)
    assert config.read_text(encoding="utf-8") == original


def test_codex_marker_without_notify_requires_manual_cleanup(tmp_path):
    home, root = _make_env(tmp_path)
    config = home / ".codex" / "config.toml"
    original = '# agentbell-hook (manual)\nmodel = "gpt-5"\n'
    config.write_text(original, encoding="utf-8")

    status = hooks.hook_statuses(home=home, root=root)[-1]
    assert status.installed is False
    assert "手动" in status.summary
    with pytest.raises(hooks.HookError, match="手动"):
        hooks.plan_install("codex", home=home, root=root)
    with pytest.raises(hooks.HookError, match="手动"):
        hooks.plan_uninstall("codex", home=home, root=root)
    with pytest.raises(hooks.HookError, match="手动"):
        hooks.uninstall_hook("codex", home=home, root=root)
    assert config.read_text(encoding="utf-8") == original


def test_malformed_settings_are_not_overwritten(tmp_path):

    home, root = _make_env(tmp_path)
    settings = home / ".claude" / "settings.json"
    settings.write_text("{broken", encoding="utf-8")

    with pytest.raises(hooks.HookError, match="JSON"):
        hooks.plan_install("claude", home=home, root=root)
    with pytest.raises(hooks.HookError, match="JSON"):
        hooks.install_hook("claude", home=home, root=root)
    assert settings.read_text(encoding="utf-8") == "{broken"
    status = hooks.hook_statuses(home=home, root=root)[0]
    assert status.installed is False
    assert "JSON" in status.summary


def test_unknown_agent_is_rejected(tmp_path):
    home, root = _make_env(tmp_path)
    with pytest.raises(hooks.HookError, match="未知"):
        hooks.plan_install("nope", home=home, root=root)


@requires_powershell
def test_helper_maps_permission_wait_and_writes_only_state(tmp_path):
    home, root = _make_env(tmp_path)
    config = root / "config.json"
    config.write_text(
        json.dumps({"port": 8799, "token": "top-secret"}), encoding="utf-8"
    )
    helper = hooks.helper_source()
    payload = {
        "hook_event_name": "Notification",
        "session_id": "s1",
        "cwd": r"E:\demo\project",
        "message": "Claude needs your permission to use Bash",
    }
    data = _helper_body(helper, config, "claude", payload)
    assert data["target"] == "http://127.0.0.1:8799/notify"
    assert "top-secret" not in json.dumps(data)
    body = data["body"]
    assert body["title"] == "Claude Code 等待权限确认"
    assert body["status"] == "running"
    assert body["needs_input"] is True
    assert body["wait_reason"] == "permission"
    assert body["wait_source"] == "explicit"
    assert body["phase"] == "waiting_input"
    assert body["session_id"] == "s1"
    assert body["origin"]["working_dir"] == r"E:\demo\project"
    assert [action["kind"] for action in body["actions"]] == ["session", "timeline"]

    state = root / "hooks" / "state" / "claude-s1.json"
    state_data = json.loads(state.read_text(encoding="utf-8"))
    assert set(state_data) == {"turn", "waiting", "updated"}
    assert state_data["waiting"] is True
    assert "Claude needs" not in state.read_text(encoding="utf-8")


@requires_powershell
def test_helper_turn_state_links_start_wait_and_finish(tmp_path):
    home, root = _make_env(tmp_path)
    config = root / "config.json"
    config.write_text(json.dumps({"port": 8799}), encoding="utf-8")
    helper = hooks.helper_source()

    started = _helper_body(
        helper,
        config,
        "claude",
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s2",
            "cwd": r"E:\demo\project",
        },
    )["body"]
    assert started["phase"] == "started"
    assert started["silent"] is True
    assert started["needs_input"] is False
    assert "actions" not in started

    waiting = _helper_body(
        helper,
        config,
        "claude",
        {
            "hook_event_name": "Notification",
            "session_id": "s2",
            "message": "Claude is waiting for your input",
        },
    )["body"]
    assert waiting["wait_reason"] == "question"
    assert waiting["dedupe_key"] == started["dedupe_key"]
    assert waiting["run_id"] == started["run_id"]

    finished = _helper_body(
        helper,
        config,
        "claude",
        {
            "hook_event_name": "Stop",
            "session_id": "s2",
            "last_assistant_message": "All tests passed",
        },
    )["body"]
    assert finished["status"] == "succeeded"
    assert finished["phase"] == "finished"
    assert finished["summary"] == "All tests passed"
    assert finished["dedupe_key"] == started["dedupe_key"]
    assert not (root / "hooks" / "state" / "claude-s2.json").exists()


@requires_powershell
def test_helper_ignores_completion_notifications_and_unknown_events(tmp_path):
    home, root = _make_env(tmp_path)
    config = root / "config.json"
    config.write_text(json.dumps({"port": 8799}), encoding="utf-8")
    helper = hooks.helper_source()
    assert (
        _run_helper(
            helper,
            config,
            "grok",
            {"hook_event_name": "Notification", "notification_type": "task_complete"},
        )
        == ""
    )
    assert (
        _run_helper(helper, config, "claude", {"hook_event_name": "PreToolUse"})
        == ""
    )


@requires_powershell
def test_helper_codex_reads_payload_argument(tmp_path):
    home, root = _make_env(tmp_path)
    config = root / "config.json"
    config.write_text(json.dumps({"port": 8799}), encoding="utf-8")
    helper = hooks.helper_source()
    output = _run_helper(
        helper,
        config,
        "codex",
        {
            "type": "agent-turn-complete",
            "turn-id": "turn-42",
            "thread-id": "thread-7",
            "last-assistant-message": "Codex finished",
        },
        as_argument=True,
    )
    body = json.loads(output)["body"]
    assert body["title"] == "Codex 已完成"
    assert body["status"] == "succeeded"
    assert body["phase"] == "finished"
    assert body["session_id"] == "thread-7"
    assert "turn-42" in body["dedupe_key"]


@requires_powershell
def test_helper_requires_valid_port_without_default_fallback(tmp_path):
    home, root = _make_env(tmp_path)
    helper = hooks.helper_source()
    payload = {"hook_event_name": "Stop", "session_id": "s9"}
    config = root / "config.json"

    assert _run_helper(helper, config, "claude", payload) == ""

    config.write_text(json.dumps({"port": "not-a-port"}), encoding="utf-8")
    assert _run_helper(helper, config, "claude", payload) == ""

    config.write_text(json.dumps({"port": 8799}), encoding="utf-8")
    env = dict(os.environ)
    env["AGENTBELL_PORT"] = "invalid"
    output = _run_helper(helper, config, "claude", payload, env=env)
    assert json.loads(output)["target"] == "http://127.0.0.1:8799/notify"

    env["AGENTBELL_PORT"] = "8798"
    output = _run_helper(helper, config, "claude", payload, env=env)
    assert json.loads(output)["target"] == "http://127.0.0.1:8798/notify"


@requires_powershell
def test_helper_posts_json_to_loopback_server(tmp_path):
    home, root = _make_env(tmp_path)
    captured: dict[str, object] = {}
    received = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            captured["path"] = self.path
            captured["token"] = self.headers.get("X-Token")
            captured["body"] = self.rfile.read(length)
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            received.set()

        def log_message(self, format, *args):  # noqa: A002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = root / "config.json"
        config.write_text(
            json.dumps(
                {
                    "port": server.server_address[1],
                    "token": "loopback-token",
                }
            ),
            encoding="utf-8",
        )
        helper = hooks.helper_source()
        command = [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-Agent",
            "claude",
            "-ConfigPath",
            str(config),
        ]
        result = subprocess.run(
            command,
            input=json.dumps(
                {
                    "hook_event_name": "Notification",
                    "session_id": "post-1",
                    "message": "Claude needs your permission to use Bash",
                }
            ),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        assert result.returncode == 0
        assert received.wait(10)
        assert captured["path"] == "/notify"
        assert captured["token"] == "loopback-token"
        body = json.loads(captured["body"])  # type: ignore[arg-type]
        assert body["needs_input"] is True
        assert body["wait_reason"] == "permission"
    finally:
        server.shutdown()
        server.server_close()
