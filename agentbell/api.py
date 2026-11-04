from __future__ import annotations

import hmac
import json
import logging
import queue
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from . import __version__, window_focus
from .config import AppConfig
from .models import (
    ActionKind,
    Notification,
    NotificationAction,
    PopupMode,
    PopupSkin,
    Priority,
    RunEventKind,
    Status,
    WAIT_REASONS,
    WAIT_SOURCES,
    WaitReason,
    WaitSource,
    default_priority,
    safe_callback_url,
    safe_http_url,
    safe_local_path,
)
from .policy import apply_rules
from .store import NotificationStore

QUEUE_MAX_SIZE = 200
MAX_BODY_BYTES = 1024 * 1024
MAX_ACTIONS = 4

_DEFAULT_WHEN_NULL = {
    "title": "未命名任务",
    "status": "succeeded",
    "summary": "",
    "duration": "",
}

_ACTION_LABELS: dict[str, str] = {
    "open": "打开链接",
    "copy": "复制",
    "retry": "重试",
    "path": "打开文件",
    "center": "通知中心",
    "focus": "回到终端",
    "session": "查看记录",
    "timeline": "时间线",
}

_ACTION_PRIORITY = {"focus": 0, "session": 1, "timeline": 2}

_SUSPECT_MARKS = re.compile(r"\?{3,}")
_LOSSY_FIELDS = ("title", "summary", "duration", "error", "source")


class ActionPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    kind: ActionKind
    label: str = Field(default="", max_length=40)
    value: str = Field(default="", max_length=2048)


class OriginPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    pid: int | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    window_title: str = Field(default="", max_length=200)
    working_dir: str = Field(default="", max_length=1024)

    @field_validator("window_title", "working_dir")
    @classmethod
    def _compact_origin_text(cls, value: str) -> str:
        return " ".join(value.replace("\x00", " ").split())


class NotifyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(default="未命名任务", max_length=200)
    status: Status = "succeeded"
    summary: str = Field(default="", max_length=4000)
    duration: str = Field(default="", max_length=64)
    link: str | None = Field(default=None, max_length=2048)
    error: str | None = Field(default=None, max_length=2000)
    priority: Priority | None = None
    source: str = Field(default="", max_length=100)
    dedupe_key: str | None = Field(default=None, max_length=200)
    needs_input: bool = False
    wait_reason: WaitReason | None = None
    wait_source: WaitSource | None = None
    session_id: str | None = Field(default=None, max_length=120)
    run_id: str | None = Field(default=None, max_length=120)
    phase: RunEventKind | None = None
    require_ack: bool = False
    silent: bool = False
    progress: int | None = Field(default=None, ge=0, le=100)
    actions: list[ActionPayload] = Field(default_factory=list, max_length=8)
    origin: OriginPayload | None = None
    bypass_quiet_hours: bool = False
    auto_close_seconds: int | None = Field(default=None, ge=0, le=3600)
    expires_in: int | None = Field(default=None, ge=1, le=604800)
    channel_types: list[str] = Field(default_factory=list, max_length=10)
    popup_mode: PopupMode | None = None
    popup_skin: PopupSkin | None = None

    @field_validator("title", "status", "summary", "duration", mode="before")
    @classmethod
    def _fill_null_with_default(cls, value: Any, info: Any) -> Any:
        if value is None:
            return _DEFAULT_WHEN_NULL[info.field_name]
        return value

    @field_validator("title")
    @classmethod
    def _compact_title(cls, value: str) -> str:
        value = " ".join(value.split())
        return value or "未命名任务"

    @field_validator("summary", "duration", "source")
    @classmethod
    def _compact_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("error")
    @classmethod
    def _compact_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        return value or None

    @field_validator("link")
    @classmethod
    def _empty_link_to_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator(
        "dedupe_key", "priority", "phase", "popup_mode", "popup_skin", mode="before"
    )
    @classmethod
    def _lower_optional(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value.lower() if value else None
        return value

    @field_validator("status", "priority", mode="before")
    @classmethod
    def _lower_known(cls, value: Any) -> Any:
        return value.lower() if isinstance(value, str) else value

    @field_validator("actions", "channel_types", mode="before")
    @classmethod
    def _none_to_empty(cls, value: Any) -> Any:
        return [] if value is None else value

    @field_validator("wait_reason", "wait_source", mode="before")
    @classmethod
    def _normalize_wait_enum(cls, value: Any, info: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        text = value.strip().lower()
        if not text:
            return None
        allowed = WAIT_REASONS if info.field_name == "wait_reason" else WAIT_SOURCES
        if text in allowed:
            return text
        return "other" if info.field_name == "wait_reason" else "explicit"

    @field_validator("session_id", "run_id", mode="before")
    @classmethod
    def _normalize_optional_id(cls, value: Any) -> Any:
        if value is None or not isinstance(value, str):
            return value
        return value.strip() or None

    @model_validator(mode="after")
    def _validate_waiting_input(self) -> "NotifyPayload":
        if not self.needs_input:
            self.wait_reason = None
            self.wait_source = None
            return self
        if self.status != "running":
            raise ValueError("needs_input 只允许与 status=running 一起使用")
        self.wait_reason = self.wait_reason or "other"
        self.wait_source = self.wait_source or "explicit"
        return self


def _client(request: Request) -> str:
    return request.client.host if request.client else "-"


def _log_text(value: str, limit: int = 120) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


async def _read_payload(
    request: Request,
    logger: logging.Logger,
) -> tuple[NotifyPayload | None, JSONResponse | None]:
    """Parse JSON from UTF-8, falling back to GB18030.

    Windows curl sends command-line literals in the active ANSI code page (often
    GBK), which is not valid UTF-8. Supporting it keeps the documented curl test
    working without weakening field validation.
    """
    declared_length = request.headers.get("content-length", "")
    if declared_length.isdigit() and int(declared_length) > MAX_BODY_BYTES:
        logger.warning("请求体过大 client=%s bytes=%s", _client(request), declared_length)
        return None, JSONResponse(
            status_code=413, content={"ok": False, "error": "payload too large"}
        )

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        logger.warning("请求体过大 client=%s bytes=%d", _client(request), len(body))
        return None, JSONResponse(
            status_code=413, content={"ok": False, "error": "payload too large"}
        )
    if not body:
        logger.warning("请求体为空 client=%s", _client(request))
        return None, JSONResponse(
            status_code=400, content={"ok": False, "error": "empty body"}
        )

    try:
        text = body.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = body.decode("gb18030")
        except UnicodeDecodeError:
            logger.warning("请求体编码无法识别 client=%s", _client(request))
            return None, JSONResponse(
                status_code=400, content={"ok": False, "error": "unsupported encoding"}
            )
        logger.warning(
            "请求体不是 UTF-8，已按 GB18030 兼容解码 client=%s", _client(request)
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning(
            "请求 JSON 解析失败 client=%s（第 %d 行第 %d 列：%s）",
            _client(request),
            exc.lineno,
            exc.colno,
            exc.msg,
        )
        return None, JSONResponse(
            status_code=400, content={"ok": False, "error": "invalid JSON body"}
        )

    try:
        return NotifyPayload.model_validate(data), None
    except ValidationError as exc:
        details = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", ()))
            details.append(f"{location}:{error.get('type', 'invalid')}")
        logger.warning(
            "通知字段校验失败 client=%s details=%s",
            _client(request),
            ", ".join(details) or "invalid payload",
        )
        return None, JSONResponse(
            status_code=422, content={"ok": False, "error": "invalid payload"}
        )


def _build_origin_action(
    origin: OriginPayload | None, logger: logging.Logger
) -> NotificationAction | None:
    if origin is None:
        return None
    pid = origin.pid if origin.pid and origin.pid > 0 else None
    title = origin.window_title.strip()
    working_dir = safe_local_path(origin.working_dir) or ""
    if pid is None and not title and working_dir:
        # 只有目录时用项目名兜底匹配终端标题，准确度低于 pid 但仍然可用
        title = re.split(r"[\\/]+", working_dir.rstrip("\\/"))[-1][:200]
    if pid is None and not title:
        logger.warning("origin 缺少 pid 和 window_title，忽略回到终端动作")
        return None
    if pid is not None:
        window = window_focus.snapshot_focus(pid)
        if window is not None:
            pid = window.pid
            title = window.title or title
            logger.info(
                "origin 已绑定窗口 pid=%s title=%s",
                window.pid,
                _log_text(window.title, 80),
            )
    value = json.dumps(
        {"pid": pid, "window_title": title, "working_dir": working_dir},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return NotificationAction(kind="focus", label="回到终端", value=value)


def _build_actions(
    payload: NotifyPayload, config: AppConfig, logger: logging.Logger
) -> tuple[NotificationAction, ...]:
    actions: list[NotificationAction] = []
    for item in payload.actions[:MAX_ACTIONS]:
        value = item.value.strip()
        if item.kind == "open":
            safe = safe_http_url(value)
            if not safe:
                logger.warning("忽略无效的 open 动作：%s", _log_text(value, 200))
                continue
            value = safe
        elif item.kind == "retry":
            safe = safe_callback_url(value)
            if not safe:
                logger.warning("忽略非本机回环的 retry 动作：%s", _log_text(value, 200))
                continue
            value = safe
        elif item.kind == "path":
            if not config.allow_local_paths:
                logger.warning("未开启 allow_local_paths，忽略 path 动作")
                continue
            safe = safe_local_path(value)
            if not safe:
                continue
            value = safe
        elif item.kind == "copy":
            if not value or "\x00" in value:
                continue
            value = value[:2048]
        elif item.kind == "session":
            if not payload.session_id:
                logger.warning("忽略缺少 session_id 的 session 动作")
                continue
            value = ""
        elif item.kind == "timeline":
            if not (payload.run_id or payload.session_id or payload.dedupe_key):
                logger.warning("忽略无法确定 run_id 的 timeline 动作")
                continue
            value = ""
        elif item.kind == "focus":
            logger.warning("忽略外部 focus 动作，请改用 origin 字段")
            continue
        else:
            value = ""
        label = item.label.strip()[:40] or _ACTION_LABELS[item.kind]
        actions.append(NotificationAction(kind=item.kind, label=label, value=value))
    actions.sort(key=lambda action: _ACTION_PRIORITY.get(action.kind, 3))
    return tuple(actions)


def _detect_sender(
    request: Request,
    origin: OriginPayload | None,
    logger: logging.Logger,
) -> tuple[OriginPayload | None, str]:
    """Fill in origin/source when the payload omits them.

    The notification arrives on a loopback socket owned by the sender, so the
    client port identifies the process even when the agent forgot to send
    ``origin`` or ``source``.
    """
    client = request.client
    if client is None:
        return origin, ""
    server = request.scope.get("server")
    server_port = server[1] if server else None
    detected = window_focus.client_pid(client.port, server_port)
    if origin is not None and origin.pid:
        detected = origin.pid
    elif detected is None:
        return origin, ""
    elif origin is None:
        origin = OriginPayload(pid=detected)
        logger.info("通知未带 origin，已自动识别发送进程 pid=%s", detected)
    else:
        origin = OriginPayload(
            pid=detected,
            window_title=origin.window_title,
            working_dir=origin.working_dir,
        )
        logger.info("origin 未带 pid，已自动识别发送进程 pid=%s", detected)
    return origin, window_focus.sender_label(detected)


def _project_name(origin: OriginPayload | None) -> str:
    if origin is None or not origin.working_dir:
        return ""
    parts = [part for part in re.split(r"[\\/]+", origin.working_dir.strip()) if part]
    return parts[-1][:80] if parts else ""


def _build_notification(
    payload: NotifyPayload,
    config: AppConfig,
    logger: logging.Logger,
    now: datetime,
    *,
    origin: OriginPayload | None,
    source: str,
    project: str = "",
) -> Notification:
    link = safe_http_url(payload.link)
    if payload.link and link is None:
        logger.warning("忽略非 http(s) 链接：%s", _log_text(payload.link, 200))

    priority = payload.priority or (
        "high" if payload.needs_input else default_priority(payload.status)
    )
    actions = _build_actions(payload, config, logger)
    origin_action = _build_origin_action(origin, logger)
    if origin_action is not None:
        actions = (origin_action,) + actions[: MAX_ACTIONS - 1]
    notification = Notification(
        id=uuid.uuid4().hex[:12],
        title=payload.title,
        status=payload.status,
        summary=payload.summary,
        duration=payload.duration,
        link=link,
        error=payload.error if payload.status == "failed" else None,
        received_at=now,
        updated_at=now,
        priority=priority,
        source=source,
        dedupe_key=payload.dedupe_key,
        needs_input=payload.needs_input,
        wait_reason=payload.wait_reason,
        wait_source=payload.wait_source,
        session_id=payload.session_id,
        run_id=payload.run_id,
        require_ack=payload.require_ack,
        silent=payload.silent,
        progress=payload.progress if payload.status == "running" else None,
        actions=actions,
        bypass_quiet_hours=payload.bypass_quiet_hours,
        auto_close_seconds=payload.auto_close_seconds,
        expires_at=(
            now + timedelta(seconds=payload.expires_in)
            if payload.expires_in is not None
            else None
        ),
        channel_types=tuple(payload.channel_types[:10]),
        popup_mode=payload.popup_mode,
        popup_skin=payload.popup_skin,
    )
    return apply_rules(notification, config.rules, project=project)


def create_app(
    config: AppConfig | Callable[[], AppConfig],
    inbox: queue.Queue[Notification],
    logger: logging.Logger,
    store: NotificationStore | None = None,
) -> FastAPI:
    def current_config() -> AppConfig:
        return config() if callable(config) else config

    startup_config = current_config()
    app = FastAPI(
        title="AgentBell",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    expected_token = startup_config.token.encode("utf-8")
    history = store if store is not None else NotificationStore(QUEUE_MAX_SIZE)

    @app.middleware("http")
    async def verify_token(request: Request, call_next):
        if request.url.path == "/notify" and startup_config.token:
            supplied = request.headers.get("x-token")
            supplied_bytes = supplied.encode("utf-8") if supplied is not None else None
            if supplied_bytes is None or not hmac.compare_digest(supplied_bytes, expected_token):
                logger.warning("拒绝通知：X-Token 缺失或错误 client=%s", _client(request))
                return JSONResponse(
                    status_code=401,
                    content={"ok": False, "error": "invalid token"},
                )
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "app": "AgentBell",
            "version": __version__,
            "auth": startup_config.auth_enabled,
            "history": len(history),
        }

    @app.post("/notify", status_code=202)
    async def notify(request: Request):
        payload, error_response = await _read_payload(request, logger)
        if error_response is not None:
            return error_response
        if payload is None:  # pragma: no cover - defensive
            return JSONResponse(
                status_code=400, content={"ok": False, "error": "invalid payload"}
            )

        now = datetime.now().astimezone()
        origin, auto_source = _detect_sender(request, payload.origin, logger)
        project = _project_name(origin)
        active_config = current_config()
        notification = _build_notification(
            payload,
            active_config,
            logger,
            now,
            origin=origin,
            source=payload.source or auto_source,
            project=project,
        )
        stored, updated = history.add(
            notification,
            phase=payload.phase,
            project=project,
        )

        lossy_fields = [
            name
            for name in _LOSSY_FIELDS
            if _SUSPECT_MARKS.search(getattr(payload, name) or "")
        ]
        if lossy_fields:
            logger.warning(
                "通知文本疑似编码丢失 id=%s fields=%s：发送端须按 UTF-8 发送；"
                "PowerShell 5.1 请用 [System.Text.Encoding]::UTF8.GetBytes($json)",
                stored.id,
                ",".join(lossy_fields),
            )

        log_id = stored.id
        logger.info(
            "收到通知 id=%s status=%s priority=%s title=%s duration=%s "
            "summary_len=%d source=%s dedupe=%s run=%s phase=%s updated=%s client=%s",
            log_id,
            stored.status,
            stored.priority,
            _log_text(stored.title),
            _log_text(stored.duration, 32) or "-",
            len(stored.summary),
            _log_text(stored.source, 60) or "-",
            _log_text(stored.dedupe_key or "", 60) or "-",
            _log_text(stored.run_id or "", 60) or "-",
            payload.phase or "auto",
            updated,
            _client(request),
        )

        try:
            inbox.put_nowait(stored)
        except queue.Full:
            logger.error(
                "通知队列已满，界面未更新 id=%s title=%s client=%s",
                log_id,
                _log_text(stored.title),
                _client(request),
            )
            return JSONResponse(
                status_code=503,
                content={"ok": False, "error": "notification queue is full"},
            )

        return {
            "ok": True,
            "id": log_id,
            "queued": True,
            "updated": updated,
            "run_id": stored.run_id,
            "phase": payload.phase,
            "priority": stored.priority,
            "require_ack": stored.require_ack,
            "needs_input": stored.needs_input,
            "wait_reason": stored.wait_reason,
            "wait_source": stored.wait_source,
            "occurrence": stored.occurrence_count,
            "popup_mode": stored.popup_mode or active_config.popup_mode,
            "popup_skin": stored.popup_skin or active_config.popup_skin,
        }

    return app
