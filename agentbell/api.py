from __future__ import annotations

import hmac
import json
import logging
import queue
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import __version__
from .config import AppConfig
from .models import Notification, Status, safe_http_url
from .store import NotificationStore

QUEUE_MAX_SIZE = 200
MAX_BODY_BYTES = 1024 * 1024

_DEFAULT_WHEN_NULL = {
    "title": "未命名任务",
    "status": "succeeded",
    "summary": "",
    "duration": "",
}


class NotifyPayload(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    title: str = Field(default="未命名任务", max_length=200)
    status: Status = "succeeded"
    summary: str = Field(default="", max_length=4000)
    duration: str = Field(default="", max_length=64)
    link: str | None = Field(default=None, max_length=2048)
    error: str | None = Field(default=None, max_length=2000)

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

    @field_validator("summary", "duration")
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


def create_app(
    config: AppConfig,
    inbox: queue.Queue[Notification],
    logger: logging.Logger,
    store: NotificationStore | None = None,
) -> FastAPI:
    app = FastAPI(
        title="AgentBell",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    expected_token = config.token.encode("utf-8")
    history = store if store is not None else NotificationStore(QUEUE_MAX_SIZE)

    @app.middleware("http")
    async def verify_token(request: Request, call_next):
        if request.url.path == "/notify" and config.token:
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
            "auth": config.auth_enabled,
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

        link = safe_http_url(payload.link)
        if payload.link and link is None:
            logger.warning("忽略非 http(s) 链接：%s", _log_text(payload.link, 200))

        notification = Notification(
            id=uuid.uuid4().hex[:12],
            title=payload.title,
            status=payload.status,
            summary=payload.summary,
            duration=payload.duration,
            link=link,
            error=payload.error if payload.status == "failed" else None,
        )

        try:
            inbox.put_nowait(notification)
        except queue.Full:
            logger.error(
                "通知队列已满，拒绝请求 id=%s title=%s client=%s",
                notification.id,
                _log_text(notification.title),
                _client(request),
            )
            return JSONResponse(
                status_code=503,
                content={"ok": False, "error": "notification queue is full"},
            )

        history.add(notification)
        logger.info(
            "收到通知 id=%s status=%s title=%s duration=%s summary_len=%d client=%s",
            notification.id,
            notification.status,
            _log_text(notification.title),
            _log_text(notification.duration, 32) or "-",
            len(notification.summary),
            _client(request),
        )
        return {"ok": True, "id": notification.id, "queued": True}

    return app
