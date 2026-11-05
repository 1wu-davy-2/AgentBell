from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Sequence

from .paths import app_dir as default_app_dir

MAX_TITLE = 100
MAX_SUMMARY = 200
MAX_SESSION = 120
MAX_RUN = 120
MAX_DEDUPE = 200

_LABELS = {
    "claude": "Claude Code",
    "gemini": "Gemini CLI",
    "grok": "Grok",
    "codex": "Codex",
}
_MESSAGE_KEYS = (
    "message",
    "last_assistant_message",
    "lastAssistantMessage",
    "last-assistant-message",
    "errorDetails",
    "error_details",
    "error",
    "details",
)
_SESSION_KEYS = (
    "session_id",
    "sessionId",
    "conversation_id",
    "conversationId",
    "thread_id",
    "threadId",
    "thread-id",
    "chat_id",
    "chatId",
)
_CWD_KEYS = (
    "cwd",
    "working_dir",
    "workingDirectory",
    "project_dir",
    "projectDir",
    "project_path",
    "projectPath",
)
_EVENT_KEYS = (
    "hook_event_name",
    "hookEventName",
    "event_name",
    "eventName",
    "event",
)


def _field(payload: Any, keys: Sequence[str]) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if value is None or isinstance(value, (dict, list)):
            continue
        if isinstance(value, (str, int, float, bool)):
            text = str(value).strip()
            if text:
                return text
    return ""


def _clean(value: str, limit: int) -> str:
    text = " ".join((value or "").replace("\x00", " ").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _turn() -> str:
    return uuid.uuid4().hex[:12]


def _app_dir() -> Path:
    return default_app_dir()


def _state_path(app_dir: Path, agent: str, session_id: str) -> Path:
    key = session_id or "default"
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", key)[:100]
    return app_dir / "hooks" / "state" / f"{agent}-{safe}.json"


def _read_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, turn: str, waiting: bool) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temp.write_text(
            json.dumps(
                {"turn": turn, "waiting": waiting, "updated": int(time.time())},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        os.replace(temp, path)
    except OSError:
        pass


def _remove_state(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _wait_reason(kind: str, message: str) -> str:
    kind_text = (kind or "").lower()
    text = f"{kind} {message}".lower()
    if re.search(r"permission|approval|confirm", kind_text):
        return "permission"
    if re.search(r"idle|question|input", kind_text):
        return "question"
    if re.search(r"rate.?limit|quota|too many requests|429|限流|配额|速率|频率", text):
        return "rate_limit"
    if re.search(r"context|token limit|max.*(token|length)|上下文|超出.*长度|token.*超", text):
        return "context_limit"
    if re.search(
        r"permission|approval|approve|allow|authorize|confirm|权限|允许|批准|确认|授权",
        text,
    ):
        return "permission"
    if re.search(r"idle|question|input|answer|ask|是否|要不要|回答|提问|输入", text):
        return "question"
    return "other"


def _parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(prog="AgentBell --hook", add_help=False)
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--agent", default="auto")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_known_args(argv)


def _read_payload(extra: Sequence[str]) -> dict:
    candidate = " ".join(str(item) for item in extra).strip()
    if candidate.startswith("{"):
        try:
            data = json.loads(candidate)
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}
    if sys.stdin is not None and not sys.stdin.isatty():
        try:
            text = sys.stdin.read()
        except (OSError, UnicodeError):
            return {}
        if text.strip():
            try:
                data = json.loads(text)
                return data if isinstance(data, dict) else {}
            except ValueError:
                return {}
    return {}


def _detect_agent(requested: str) -> str:
    agent = (requested or "auto").strip().lower()
    if agent != "auto":
        return agent if agent in _LABELS else "claude"
    if os.environ.get("GROK_EVENT") or os.environ.get("GROK_SESSION_ID"):
        return "grok"
    if os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_PROJECT_DIR"):
        return "claude"
    if os.environ.get("GEMINI_SESSION_ID"):
        return "gemini"
    return "claude"


class _Hook:
    def __init__(self, args: argparse.Namespace, payload: dict) -> None:
        self.payload = payload
        self.agent = _detect_agent(args.agent)
        self.label = _LABELS.get(self.agent, "Agent")
        self.app_dir = Path(args.config).resolve().parent if args.config else _app_dir()
        self.dry_run = bool(args.dry_run)
        config_path = (
            Path(args.config).expanduser().resolve()
            if args.config
            else self.app_dir / "config.json"
        )
        self.port = 0
        self.token = ""
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(config.get("port"), int):
                self.port = int(config["port"])
            if config.get("token"):
                self.token = str(config["token"])
        except (OSError, ValueError):
            pass
        env_port = os.environ.get("AGENTBELL_PORT", "")
        if env_port.isdigit() and 1 <= int(env_port) <= 65535:
            self.port = int(env_port)
        if os.environ.get("AGENTBELL_TOKEN"):
            self.token = os.environ["AGENTBELL_TOKEN"]
        self.session_id = _field(payload, _SESSION_KEYS)
        if not self.session_id:
            self.session_id = (
                os.environ.get("GROK_SESSION_ID")
                or os.environ.get("CLAUDE_SESSION_ID")
                or os.environ.get("GEMINI_SESSION_ID")
                or ""
            )
        self.session_id = self.session_id[:MAX_SESSION]
        self.cwd = _field(payload, _CWD_KEYS) or os.getcwd()
        self.state_path = _state_path(self.app_dir, self.agent, self.session_id)

    def send(
        self,
        title: str,
        status: str,
        summary: str,
        *,
        phase: str = "",
        needs_input: bool = False,
        wait_reason: str = "",
        priority: str = "normal",
        silent: bool = False,
        turn: str = "",
        with_actions: bool = True,
    ) -> None:
        turn = turn or _turn()
        run_id = f"hook:{self.agent}"
        dedupe = f"agentbell-hook:{self.agent}"
        if self.session_id:
            run_id += f":{self.session_id}"
            dedupe += f":{self.session_id}"
        run_id = (run_id + f":{turn}")[:MAX_RUN]
        dedupe = (dedupe + f":{turn}")[:MAX_DEDUPE]
        body: dict[str, Any] = {
            "title": _clean(title, MAX_TITLE),
            "status": status,
            "summary": _clean(summary, MAX_SUMMARY),
            "source": self.label,
            "priority": priority,
            "silent": bool(silent),
            "needs_input": bool(needs_input),
            "dedupe_key": dedupe,
            "run_id": run_id,
            "origin": {"pid": os.getpid(), "working_dir": self.cwd},
        }
        if needs_input:
            body["wait_reason"] = wait_reason
            body["wait_source"] = "explicit"
        if phase:
            body["phase"] = phase
        if self.session_id:
            body["session_id"] = self.session_id
        if with_actions:
            actions = []
            if self.session_id:
                actions.append({"kind": "session", "label": "查看记录"})
            actions.append({"kind": "timeline", "label": "时间线"})
            body["actions"] = actions
        if self.dry_run:
            print(
                json.dumps(
                    {
                        "target": f"http://127.0.0.1:{self.port}/notify",
                        "body": body,
                    },
                    ensure_ascii=False,
                )
            )
            return
        if not self.port:
            return
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/notify",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json; charset=utf-8",
                **({"X-Token": self.token} if self.token else {}),
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            pass

    def run(self) -> int:
        event = _field(self.payload, _EVENT_KEYS) or _field(self.payload, ("type",))
        if not event and os.environ.get("GROK_EVENT"):
            event = os.environ["GROK_EVENT"]
        event_key = re.sub(r"[_\-]", "", event.lower())
        message = _field(self.payload, _MESSAGE_KEYS)
        notification_type = _field(
            self.payload,
            ("notification_type", "notificationType", "notification", "matcher"),
        )

        if self.agent == "codex":
            turn = _field(self.payload, ("turn-id", "turn_id", "turnId")) or _turn()
            failed = bool(re.search(r"fail|error|cancel", event_key))
            if _field(self.payload, ("error",)):
                failed = True
            if failed:
                self.send(
                    f"{self.label} 执行失败",
                    "failed",
                    message or "本轮任务执行失败",
                    phase="finished",
                    priority="high",
                    turn=turn,
                )
            else:
                self.send(
                    f"{self.label} 已完成",
                    "succeeded",
                    message or "本轮任务已完成",
                    phase="finished",
                    turn=turn,
                )
            return 0

        state = _read_state(self.state_path)
        if event_key == "sessionend":
            _remove_state(self.state_path)
            return 0
        if event_key in {"userpromptsubmit", "beforeagent"}:
            turn = _turn()
            _write_state(self.state_path, turn, False)
            summary = "新一轮任务已开始"
            project = Path(self.cwd).name[:60]
            if project:
                summary = f"项目 {project} · 新一轮任务已开始"
            self.send(
                f"{self.label} 开始处理",
                "running",
                summary,
                phase="started",
                silent=True,
                turn=turn,
                with_actions=False,
            )
            return 0

        turn = str(state.get("turn") or "") or _turn()
        if event_key == "notification":
            type_text = f"{notification_type} {event}".lower()
            if re.search(r"task_complete|turn_complete|session_ready", type_text):
                return 0
            _write_state(self.state_path, turn, True)
            reason = _wait_reason(notification_type, message)
            titles = {
                "permission": f"{self.label} 等待权限确认",
                "rate_limit": f"{self.label} 触发限流",
                "context_limit": f"{self.label} 上下文接近上限",
                "question": f"{self.label} 等待你的回答",
            }
            priority = (
                "high"
                if reason in {"permission", "rate_limit", "context_limit"}
                else "normal"
            )
            self.send(
                titles.get(reason, f"{self.label} 需要你处理"),
                "running",
                message or "会话已暂停，等待你回到终端处理",
                phase="waiting_input",
                needs_input=True,
                wait_reason=reason,
                priority=priority,
                turn=turn,
            )
            return 0

        if event_key in {"stop", "afteragent"}:
            if _field(self.payload, ("stop_hook_active", "stopHookActive")).lower() == "true":
                return 0
            self.send(
                f"{self.label} 已完成",
                "succeeded",
                message or "本轮任务已完成",
                phase="finished",
                turn=turn,
            )
            _remove_state(self.state_path)
            return 0

        if event_key == "stopfailure":
            self.send(
                f"{self.label} 执行失败",
                "failed",
                message or "本轮任务执行失败",
                phase="finished",
                priority="high",
                turn=turn,
            )
            _remove_state(self.state_path)
            return 0

        if event_key == "stopcancelled":
            self.send(
                f"{self.label} 已取消",
                "canceled",
                message or "本轮任务已取消",
                phase="finished",
                turn=turn,
            )
            _remove_state(self.state_path)
            return 0
        return 0


def main(argv: Sequence[str]) -> int:
    args, extra = _parse_args(argv)
    if not args.hook:
        return 0
    payload = _read_payload(extra)
    if not payload:
        return 0
    try:
        return _Hook(args, payload).run()
    except Exception:
        return 0
