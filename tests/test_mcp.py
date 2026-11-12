from __future__ import annotations

import json
import logging
import queue

import pytest
from fastapi.testclient import TestClient

import agentbell.api as api_module
from agentbell import __version__
from agentbell.agent_sessions import SessionReportRegistry
from agentbell.api import create_app
from agentbell.config import AppConfig
from agentbell.mcp import MCP_PROTOCOL_VERSION
from agentbell.models import Notification, WAIT_REASONS
from agentbell.store import NotificationStore
from agentbell.usage import UsageLedger

TOKEN = "mcp-secret"
HEADERS = {"X-Token": TOKEN, "Content-Type": "application/json"}


@pytest.fixture(autouse=True)
def _stub_window_snapshot(monkeypatch):
    monkeypatch.setattr(api_module.window_focus, "snapshot_focus", lambda pid: None)
    monkeypatch.setattr(api_module.window_focus, "client_pid", lambda *args: None)
    monkeypatch.setattr(api_module.window_focus, "sender_label", lambda pid: "")


def build(ledger=None, sessions=None):
    inbox: queue.Queue[Notification] = queue.Queue(maxsize=20)
    store = NotificationStore(50)
    app = create_app(
        AppConfig(port=18766, token=TOKEN),
        inbox,
        logging.getLogger("agentbell.tests.mcp"),
        store=store,
        ledger=ledger,
        sessions=sessions,
    )
    return TestClient(app), inbox, store


def rpc(client, method, params=None, request_id=1, headers=HEADERS):
    payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post("/mcp", json=payload, headers=headers)


def call_tool(client, name, arguments=None):
    return rpc(
        client,
        "tools/call",
        {"name": name, "arguments": arguments or {}},
    )


def result_payload(response):
    body = response.json()
    assert "error" not in body, body
    result = body["result"]
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


def test_mcp_requires_token():
    client, inbox, _store = build()
    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == -32001
    assert inbox.empty()

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        headers={"X-Token": "wrong", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


def test_bearer_token_is_accepted():
    client, _inbox, _store = build()
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == {}


def test_initialize_and_tools_list():
    client, _inbox, _store = build()
    response = rpc(client, "initialize", {"protocolVersion": MCP_PROTOCOL_VERSION})
    body = response.json()
    assert body["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert body["result"]["serverInfo"] == {
        "name": "agentbell",
        "version": __version__,
    }
    assert body["result"]["capabilities"]["tools"]["listChanged"] is False

    response = rpc(client, "tools/list")
    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "notify",
        "search_history",
        "get_status",
        "report_usage",
        "report_session",
    }
    notify = next(tool for tool in tools if tool["name"] == "notify")
    assert notify["inputSchema"]["properties"]["wait_reason"]["enum"] == list(
        WAIT_REASONS
    )


def test_notify_tool_creates_notification():
    client, inbox, store = build()
    payload = result_payload(
        call_tool(
            client,
            "notify",
            {
                "title": "MCP 测试任务",
                "status": "failed",
                "summary": "构建失败",
                "priority": "high",
                "dedupe_key": "mcp-demo",
                "run_id": "run-1",
            },
        )
    )
    assert payload["ok"] is True
    assert payload["queued"] is True
    notification = inbox.get_nowait()
    assert notification.title == "MCP 测试任务"
    assert notification.status == "failed"
    assert notification.source == "MCP"
    assert notification.priority == "high"
    assert notification.dedupe_key == "mcp-demo"
    assert store.find_by_dedupe("mcp-demo") is not None


def test_notify_tool_rejects_invalid_arguments():
    client, inbox, _store = build()
    response = call_tool(
        client, "notify", {"title": "x", "status": "succeeded", "needs_input": True}
    )
    result = response.json()["result"]
    assert result["isError"] is True
    assert "needs_input" in result["content"][0]["text"]
    assert inbox.empty()


def test_search_history_and_get_status():
    client, _inbox, _store = build()
    result_payload(
        call_tool(
            client,
            "notify",
            {"title": "搜索目标", "status": "succeeded", "source": "qoder"},
        )
    )
    found = result_payload(
        call_tool(client, "search_history", {"query": "搜索目标", "limit": 5})
    )
    assert found["count"] == 1
    assert found["notifications"][0]["title"] == "搜索目标"

    filtered = result_payload(
        call_tool(client, "search_history", {"query": "status:failed"})
    )
    assert filtered["count"] == 0

    status = result_payload(call_tool(client, "get_status"))
    assert status["ok"] is True
    assert status["app"] == "AgentBell"
    assert status["version"] == __version__
    assert status["stats_7d"]["total"] >= 1


def test_notification_without_id_returns_202():
    client, _inbox, _store = build()
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=HEADERS,
    )
    assert response.status_code == 202
    assert response.content == b""


def test_unknown_method_and_parse_error():
    client, _inbox, _store = build()
    response = rpc(client, "does/not/exist")
    assert response.json()["error"]["code"] == -32601

    response = client.post("/mcp", content=b"{not json", headers=HEADERS)
    assert response.json()["error"]["code"] == -32700


def test_batch_requests():
    client, _inbox, _store = build()
    response = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
        ],
        headers=HEADERS,
    )
    body = response.json()
    assert len(body) == 2
    assert body[0]["result"] == {}
    assert body[1]["id"] == 2


def test_report_usage_tool_is_idempotent():
    ledger = UsageLedger(None, logging.getLogger("agentbell.tests.mcp.usage"))
    client, _inbox, _store = build(ledger=ledger)
    arguments = {
        "report_id": "mcp-r1",
        "model": "deepseek-chat",
        "input_tokens": 10,
        "output_tokens": 5,
    }
    first = result_payload(call_tool(client, "report_usage", arguments))
    assert first["duplicate"] is False
    assert first["total_tokens"] == 15
    second = result_payload(call_tool(client, "report_usage", arguments))
    assert second["duplicate"] is True
    assert ledger.version == 1


def test_report_usage_tool_requires_model():
    ledger = UsageLedger(None, logging.getLogger("agentbell.tests.mcp.usage"))
    client, _inbox, _store = build(ledger=ledger)
    response = call_tool(client, "report_usage", {"input_tokens": 3})
    result = response.json()["result"]
    assert result["isError"] is True
    assert "model" in result["content"][0]["text"]


def test_report_session_tool_registers_heartbeat():
    registry = SessionReportRegistry(
        logging.getLogger("agentbell.tests.mcp.sessions")
    )
    client, _inbox, _store = build(sessions=registry)
    payload = result_payload(
        call_tool(
            client,
            "report_session",
            {"session_id": "mcp-s1", "title": "MCP 会话", "status": "running"},
        )
    )
    assert payload["stored"] is True
    assert payload["sessions"] == 1
    assert registry.to_agent_sessions()[0].title == "MCP 会话"

    ended = result_payload(
        call_tool(
            client,
            "report_session",
            {"session_id": "mcp-s1", "status": "finished"},
        )
    )
    assert ended["active"] is False
    assert registry.count == 0


def test_notify_tool_carries_metadata_and_wait_reason():
    client, inbox, _store = build()
    result_payload(
        call_tool(
            client,
            "notify",
            {
                "title": "权限等待",
                "status": "running",
                "needs_input": True,
                "wait_reason": "permission",
                "metadata": {"model": "deepseek-chat", "turn": 2},
            },
        )
    )
    notification = inbox.get_nowait()
    assert notification.metadata == {"model": "deepseek-chat", "turn": "2"}
    found = result_payload(
        call_tool(client, "search_history", {"query": "权限等待", "limit": 5})
    )
    item = found["notifications"][0]
    assert item["wait_reason"] == "permission"
    assert item["metadata"] == {"model": "deepseek-chat", "turn": "2"}
