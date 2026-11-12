from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / "integrations"
    / "deepseek-harness"
    / "agentbell-notify"
    / "agentbell_notify.py"
)

TOKEN = "super-secret-token"


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


@pytest.fixture()
def fake_server():
    state = {
        "requests": [],
        "status": 202,
        "body": {"ok": True, "id": "abc123", "queued": True},
    }

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            state["requests"].append(
                {
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": json.loads(raw.decode("utf-8")) if raw else {},
                }
            )
            body = json.dumps(state["body"]).encode("utf-8")
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence test output
            return

    server = _Server(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield state, f"http://127.0.0.1:{port}/notify", port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        env=env,
    )


def test_script_exists():
    assert SCRIPT.is_file(), f"missing skill script: {SCRIPT}"


def test_help_works_without_third_party_dependencies():
    result = run_script("--help")
    assert result.returncode == 0
    assert "agentbell" in result.stdout.lower()
    assert "--title" in result.stdout
    assert "--dedupe-key" in result.stdout


def test_sends_full_payload_and_token(fake_server):
    state, url, _ = fake_server
    result = run_script(
        "--url",
        url,
        "--token",
        TOKEN,
        "--title",
        "构建成功",
        "--status",
        "succeeded",
        "--summary",
        "所有测试通过",
        "--duration",
        "8m30s",
        "--session-id",
        "session-1",
        "--run-id",
        "run-1",
        "--dedupe-key",
        "dedupe-1",
        "--source",
        "DeepSeek Harness",
        "--phase",
        "finished",
        "--origin-pid",
        "1234",
        "--working-dir",
        r"C:\work\demo",
        "--json",
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["id"] == "abc123"

    assert len(state["requests"]) == 1
    request = state["requests"][0]
    assert request["path"] == "/notify"
    assert request["headers"]["x-token"] == TOKEN

    body = request["body"]
    assert body["title"] == "构建成功"
    assert body["status"] == "succeeded"
    assert body["summary"] == "所有测试通过"
    assert body["duration"] == "8m30s"
    assert body["session_id"] == "session-1"
    assert body["run_id"] == "run-1"
    assert body["dedupe_key"] == "dedupe-1"
    assert body["source"] == "DeepSeek Harness"
    assert body["phase"] == "finished"
    assert body["origin"] == {"pid": 1234, "working_dir": r"C:\work\demo"}


def test_without_token_omits_header_and_origin(fake_server):
    state, url, _ = fake_server
    result = run_script("--url", url, "--token", "", "--title", "plain run")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "abc123"

    body = state["requests"][0]["body"]
    assert body["title"] == "plain run"
    assert "x-token" not in state["requests"][0]["headers"]
    assert "origin" not in body


def test_needs_input_switches_to_running(fake_server):
    state, url, _ = fake_server
    result = run_script(
        "--url",
        url,
        "--title",
        "需要权限",
        "--needs-input",
        "--wait-reason",
        "permission",
    )

    assert result.returncode == 0, result.stderr
    body = state["requests"][0]["body"]
    assert body["status"] == "running"
    assert body["needs_input"] is True
    assert body["wait_reason"] == "permission"
    assert body["wait_source"] == "explicit"


def test_config_file_supplies_port_and_token(fake_server, tmp_path):
    state, _, port = fake_server
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"port": port, "token": "config-token"}),
        encoding="utf-8",
    )

    result = run_script("--config", str(config), "--title", "from config")

    assert result.returncode == 0, result.stderr
    assert len(state["requests"]) == 1
    request = state["requests"][0]
    assert request["headers"]["x-token"] == "config-token"
    assert request["body"]["title"] == "from config"


def test_http_error_exits_2_without_leaking_token(fake_server):
    state, url, _ = fake_server
    state["status"] = 401
    state["body"] = {"ok": False, "error": "invalid token"}

    result = run_script("--url", url, "--token", TOKEN, "--title", "denied")

    assert result.returncode == 2
    assert result.stderr.strip()
    assert TOKEN not in result.stderr
    assert TOKEN not in result.stdout
    assert "401" in result.stderr


def test_title_and_summary_are_truncated_to_api_limits(fake_server):
    state, url, _ = fake_server
    long_title = "T" * 300
    long_summary = "S" * 4500

    result = run_script(
        "--url",
        url,
        "--title",
        long_title,
        "--summary",
        long_summary,
    )

    assert result.returncode == 0, result.stderr
    body = state["requests"][0]["body"]
    assert len(body["title"]) == 200
    assert len(body["summary"]) == 4000
