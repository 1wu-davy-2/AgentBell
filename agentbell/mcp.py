from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .agent_sessions import SESSION_REPORT_STATUSES
from .models import WAIT_REASONS

MCP_PROTOCOL_VERSION = "2024-11-05"
MAX_SEARCH_LIMIT = 100

_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "notify",
        "description": (
            "向 AgentBell 发送一条桌面通知。适用于任务完成、失败、"
            "需要用户确认或继续输入时提醒用户。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "任务标题"},
                "status": {
                    "type": "string",
                    "enum": ["succeeded", "failed", "canceled", "running"],
                    "description": "任务状态，默认 succeeded",
                },
                "summary": {"type": "string", "description": "简短结论"},
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "critical"],
                },
                "needs_input": {
                    "type": "boolean",
                    "description": "是否正在等待用户输入",
                },
                "wait_reason": {
                    "type": "string",
                    "enum": list(WAIT_REASONS),
                },
                "source": {"type": "string", "description": "来源名称"},
                "dedupe_key": {
                    "type": "string",
                    "description": "相同 key 会更新原卡片而不是新建",
                },
                "run_id": {"type": "string"},
                "session_id": {"type": "string"},
                "duration": {
                    "type": "string",
                    "description": "耗时，例如 8m30s",
                },
                "link": {"type": "string", "description": "http(s) 链接"},
                "require_ack": {"type": "boolean"},
                "silent": {"type": "boolean"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "search_history",
        "description": (
            "搜索 AgentBell 通知历史。支持字段过滤语法，"
            "例如 status:failed、source:qoder、priority:high。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "关键词或过滤语法"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_SEARCH_LIMIT,
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "get_status",
        "description": "读取 AgentBell 运行状态与最近 7 天通知统计。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "report_usage",
        "description": (
            "上报一次模型调用的 Token 用量与成本，计入 AgentBell 今日用量"
            "和预算守卫。report_id 相同则幂等去重。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_id": {
                    "type": "string",
                    "description": "幂等键；缺省时按内容自动生成",
                },
                "source": {"type": "string", "default": "deepseek"},
                "model": {"type": "string"},
                "input_tokens": {"type": "integer", "minimum": 0},
                "output_tokens": {"type": "integer", "minimum": 0},
                "cache_read_tokens": {"type": "integer", "minimum": 0},
                "cache_write_tokens": {"type": "integer", "minimum": 0},
                "cost_usd": {"type": "number", "minimum": 0},
                "occurred_at": {
                    "type": "string",
                    "description": "ISO-8601 时间，缺省为当前时间",
                },
                "session_id": {"type": "string"},
                "run_id": {"type": "string"},
                "project": {"type": "string"},
            },
            "required": ["model"],
        },
    },
    {
        "name": "report_session",
        "description": (
            "上报外部 Agent 的活跃会话心跳，显示在 AgentBell「进行中」。"
            "status=ended 时移除该会话。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "agent": {"type": "string", "default": "deepseek"},
                "title": {"type": "string"},
                "project": {"type": "string"},
                "project_path": {"type": "string"},
                "status": {
                    "type": "string",
                    "default": "running",
                    "enum": list(SESSION_REPORT_STATUSES),
                    "description": "running 为活跃；ended / finished / stopped / canceled 移除该会话",
                },
                "detail": {"type": "string"},
                "turn": {"type": "integer", "minimum": 0},
                "updated_at": {"type": "string"},
                "started_at": {"type": "string"},
                "run_id": {"type": "string"},
                "needs_input": {"type": "boolean"},
                "wait_reason": {"type": "string", "enum": list(WAIT_REASONS)},
            },
            "required": ["session_id"],
        },
    },
)

NotifyHandler = Callable[[dict[str, Any]], dict[str, Any]]
SearchHandler = Callable[[dict[str, Any]], dict[str, Any]]
StatusHandler = Callable[[dict[str, Any]], dict[str, Any]]
UsageHandler = Callable[[dict[str, Any]], dict[str, Any]]
SessionHandler = Callable[[dict[str, Any]], dict[str, Any]]


class _RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(payload: Any, *, is_error: bool = False) -> dict[str, Any]:
    text = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


class McpServer:
    """Minimal MCP JSON-RPC server exposing AgentBell as five tools."""

    def __init__(
        self,
        *,
        version: str,
        notify: NotifyHandler,
        search: SearchHandler,
        status: StatusHandler,
        usage: UsageHandler,
        sessions: SessionHandler,
        logger: logging.Logger | None = None,
    ) -> None:
        self._version = version
        self._handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "notify": notify,
            "search_history": search,
            "get_status": status,
            "report_usage": usage,
            "report_session": sessions,
        }
        self._logger = logger or logging.getLogger("agentbell.mcp")

    def handle(self, message: Any) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return _error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        is_notification = "id" not in message
        method = message.get("method")
        if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
            return None if is_notification else _error(
                request_id, -32600, "Invalid Request"
            )
        if is_notification:
            return None
        try:
            result = self._dispatch(method, message.get("params"))
        except _RpcError as exc:
            return _error(request_id, exc.code, exc.message)
        except Exception as exc:  # noqa: BLE001 - keep the transport alive
            self._logger.exception("MCP 请求处理失败 method=%s", method)
            return _error(request_id, -32603, f"Internal error: {exc}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _dispatch(self, method: str, params: Any) -> dict[str, Any]:
        if method == "initialize":
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "agentbell", "version": self._version},
            }
        if method in {"notifications/initialized", "notifications/cancelled"}:
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": list(_TOOLS)}
        if method == "resources/list":
            return {"resources": []}
        if method == "prompts/list":
            return {"prompts": []}
        if method == "tools/call":
            return self._call_tool(params)
        raise _RpcError(-32601, f"Method not found: {method}")

    def _call_tool(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise _RpcError(-32602, "Invalid params")
        name = params.get("name")
        arguments = params.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise _RpcError(-32602, "Invalid params")
        handler = self._handlers.get(name)
        if handler is None:
            raise _RpcError(-32602, f"Unknown tool: {name}")
        try:
            payload = handler(arguments)
        except ValueError as exc:
            return _tool_result({"ok": False, "error": str(exc)}, is_error=True)
        return _tool_result(payload)
