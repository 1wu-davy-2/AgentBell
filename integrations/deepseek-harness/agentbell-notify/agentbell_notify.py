#!/usr/bin/env python3
"""Send one AgentBell notification over the local HTTP API.

This is the reference implementation used by the ``agentbell-notify`` skill.
It only uses the Python standard library, never reads conversation content,
never executes shell commands, and cannot approve or resume an agent turn.

Usage:
    python agentbell_notify.py --title "Build" --status succeeded \
        --summary "All tests passed" --duration 2m10s
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

DEFAULT_PORT = 8765
DEFAULT_TITLE = "未命名任务"
DEFAULT_SOURCE = "DeepSeek Harness"
TIMEOUT_SECONDS = 5

# Mirrors the limits enforced by AgentBell's /notify payload model.
LIMITS = {
    "title": 200,
    "summary": 4000,
    "source": 100,
    "dedupe_key": 200,
    "session_id": 120,
    "run_id": 120,
    "duration": 64,
    "working_dir": 1024,
    "error": 2000,
}
PHASES = ("started", "progress", "waiting_input", "resumed", "finished", "note")
STATUSES = ("succeeded", "failed", "canceled", "running")


def _compact(value: Any, limit: int) -> str:
    """Collapse whitespace and truncate to the API's field limit."""
    text = " ".join(str(value or "").split())
    return text[:limit]


def _optional(value: str | None, limit: int) -> str | None:
    text = _compact(value, limit)
    return text or None


def config_candidates(explicit: str | None) -> list[Path]:
    """Return config paths in priority order."""
    if explicit:
        return [Path(explicit).expanduser()]

    candidates: list[Path] = []
    env_config = os.environ.get("AGENTBELL_CONFIG", "").strip()
    if env_config:
        candidates.append(Path(env_config).expanduser())

    agentbell_home = os.environ.get("AGENTBELL_HOME", "").strip()
    if agentbell_home:
        candidates.append(Path(agentbell_home).expanduser() / "config.json")

    for env_name in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env_name, "").strip()
        if base:
            candidates.append(Path(base) / "AgentBell" / "config.json")

    home = Path.home()
    candidates.append(home / ".agentbell" / "config.json")
    candidates.append(home / "AgentBell" / "config.json")
    return candidates


def load_config(explicit: str | None) -> dict[str, Any]:
    """Load the first existing config file. Missing implicit files are ignored."""
    for path in config_candidates(explicit):
        try:
            if not path.is_file():
                continue
            with path.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            if explicit:
                raise SystemExit(_fail(f"无法读取配置文件 {path}：{_brief(exc)}"))
            continue
        if isinstance(data, dict):
            return data
    if explicit:
        raise SystemExit(
            _fail(f"配置文件不存在或内容无效：{Path(explicit).expanduser()}")
        )
    return {}


def _brief(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:200] or exc.__class__.__name__


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 2


def _scrub(text: str, token: str) -> str:
    """Never echo the token, even if a server reflects it back."""
    if token:
        return text.replace(token, "***")
    return text


def _resolve_token(args: argparse.Namespace, config: dict[str, Any]) -> tuple[str, int]:
    if args.token is not None:
        token = args.token.strip()
    else:
        token = config.get("token", "")
        token = token.strip() if isinstance(token, str) else ""

    try:
        port = int(config.get("port", DEFAULT_PORT))
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    if not 1 <= port <= 65535:
        port = DEFAULT_PORT
    return token, port


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    title = _compact(args.title, LIMITS["title"]) or DEFAULT_TITLE
    status = args.status
    needs_input = bool(args.needs_input)

    # AgentBell only accepts needs_input together with status="running".
    if needs_input and status != "running":
        status = "running"

    payload: dict[str, Any] = {
        "title": title,
        "status": status,
        "summary": _compact(args.summary, LIMITS["summary"]),
        "duration": _compact(args.duration, LIMITS["duration"]),
        "source": _compact(args.source, LIMITS["source"]),
        "needs_input": needs_input,
        "require_ack": bool(args.require_ack),
        "silent": bool(args.silent),
    }

    wait_reason = _optional(args.wait_reason, 32)
    if wait_reason:
        payload["wait_reason"] = wait_reason.lower()
        payload["wait_source"] = "explicit"

    session_id = _optional(args.session_id, LIMITS["session_id"])
    if session_id:
        payload["session_id"] = session_id
    run_id = _optional(args.run_id, LIMITS["run_id"])
    if run_id:
        payload["run_id"] = run_id
    dedupe_key = _optional(args.dedupe_key, LIMITS["dedupe_key"])
    if dedupe_key:
        payload["dedupe_key"] = dedupe_key
    if args.phase:
        payload["phase"] = args.phase

    if args.progress is not None:
        payload["progress"] = max(0, min(100, int(args.progress)))

    origin: dict[str, Any] = {}
    if args.origin_pid is not None:
        origin["pid"] = max(0, int(args.origin_pid))
    working_dir = _compact(args.working_dir, LIMITS["working_dir"])
    if working_dir:
        origin["working_dir"] = working_dir
    if origin:
        payload["origin"] = origin

    return payload


def notify(url: str, payload: dict[str, Any], token: str, as_json: bool = False) -> int:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["X-Token"] = token

    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", "replace").strip()
            status_code = response.status
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", "replace").strip()[:300]
        except OSError:
            detail = ""
        message = f"AgentBell 拒绝了通知：HTTP {exc.code}"
        if detail:
            message = f"{message} {detail}"
        return _fail(_scrub(" ".join(message.split()), token))
    except urllib.error.URLError as exc:
        return _fail(f"无法连接 AgentBell：{_scrub(_brief(exc.reason), token)}")
    except TimeoutError:
        return _fail(f"连接 AgentBell 超时（{TIMEOUT_SECONDS}s）")
    except OSError as exc:
        return _fail(f"通知发送失败：{_scrub(_brief(exc), token)}")

    data: Any = raw
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = raw

    if status_code >= 400:
        return _fail(f"AgentBell 返回 HTTP {status_code}")

    if as_json:
        print(json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data)
    elif isinstance(data, dict) and data.get("id"):
        print(data["id"])
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentbell-notify",
        description=(
            "向本机 AgentBell 发送一条通知。仅访问本机 HTTP API，"
            "不读取会话正文，不执行命令，也不能批准权限。"
        ),
    )
    parser.add_argument("--title", default=DEFAULT_TITLE, help="通知标题（默认 未命名任务）")
    parser.add_argument(
        "--status",
        default="succeeded",
        choices=STATUSES,
        help="任务状态（默认 succeeded）",
    )
    parser.add_argument("--summary", default="", help="简要说明，最多 4000 字符")
    parser.add_argument("--duration", default="", help="耗时文本，如 8m30s")
    parser.add_argument("--session-id", dest="session_id", default=None, help="会话 ID")
    parser.add_argument("--run-id", dest="run_id", default=None, help="运行 ID")
    parser.add_argument(
        "--dedupe-key",
        dest="dedupe_key",
        default=None,
        help="去重键，同一键的通知会合并更新",
    )
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="来源名称")
    parser.add_argument("--phase", default=None, choices=PHASES, help="运行阶段")
    parser.add_argument(
        "--needs-input",
        dest="needs_input",
        action="store_true",
        help="表示任务正在等待用户输入（会使用 status=running）",
    )
    parser.add_argument("--wait-reason", dest="wait_reason", default=None, help="等待原因")
    parser.add_argument(
        "--require-ack",
        dest="require_ack",
        action="store_true",
        help="要求用户确认收到",
    )
    parser.add_argument("--silent", action="store_true", help="静默通知（不弹窗）")
    parser.add_argument("--progress", type=int, default=None, help="进度 0-100")
    parser.add_argument("--origin-pid", dest="origin_pid", type=int, default=None)
    parser.add_argument("--working-dir", dest="working_dir", default="")
    parser.add_argument("--config", default=None, help="配置文件路径")
    parser.add_argument("--url", default=None, help="完整 /notify 地址")
    parser.add_argument("--token", default=None, help="覆盖配置中的 token")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出完整 JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    token, port = _resolve_token(args, config)

    if args.url:
        url = args.url.strip()
        split = urlsplit(url)
        if split.scheme not in ("http", "https") or not split.netloc:
            return _fail("--url 必须是完整的 http(s) 地址，例如 http://127.0.0.1:8765/notify")
    else:
        url = f"http://127.0.0.1:{port}/notify"

    payload = build_payload(args)
    return notify(url, payload, token, as_json=args.as_json)


if __name__ == "__main__":
    raise SystemExit(main())
