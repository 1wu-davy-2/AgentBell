from __future__ import annotations

import json
import logging
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request

from PySide6.QtCore import QObject, Signal

from .config import ChannelConfig
from .models import Notification

TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 64 * 1024
QUEUE_MAX_SIZE = 200

_NTFY_PRIORITY = {"low": "2", "normal": "3", "high": "4", "critical": "5"}
_BARK_LEVEL = {
    "low": "passive",
    "normal": "active",
    "high": "timeSensitive",
    "critical": "timeSensitive",
}


def message_text(notification: Notification) -> str:
    parts = [f"{notification.status_label}｜{notification.title}"]
    if notification.summary:
        parts.append(notification.summary)
    if notification.status == "failed" and notification.error:
        parts.append(f"错误：{notification.error}")
    if notification.duration:
        parts.append(f"耗时 {notification.duration}")
    if notification.link:
        parts.append(notification.link)
    if notification.source:
        parts.append(f"来源：{notification.source}")
    return "\n".join(parts)


def _post(
    url: str,
    body: bytes,
    headers: dict[str, str],
) -> tuple[bool, str]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response.read(MAX_RESPONSE_BYTES)
            status = getattr(response, "status", 200)
            if 200 <= status < 300:
                return True, ""
            return False, f"HTTP {status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"网络错误：{exc.reason}"
    except (OSError, ValueError) as exc:
        return False, f"发送失败：{type(exc).__name__}"


def _json_body(payload: dict[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _webhook_payload(notification: Notification) -> dict[str, object]:
    return {
        "app": "AgentBell",
        "id": notification.id,
        "title": notification.title,
        "status": notification.status,
        "summary": notification.summary,
        "duration": notification.duration,
        "link": notification.link,
        "error": notification.error,
        "priority": notification.priority,
        "source": notification.source,
        "received_at": notification.received_at.isoformat(),
    }


def send(channel: ChannelConfig, notification: Notification) -> tuple[bool, str]:
    text = message_text(notification)
    headers = dict(channel.headers)
    headers.setdefault("User-Agent", "AgentBell/2")

    if channel.type == "webhook":
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return _post(channel.url, _json_body(_webhook_payload(notification)), headers)

    if channel.type == "feishu":
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return _post(
            channel.url,
            _json_body({"msg_type": "text", "content": {"text": text}}),
            headers,
        )

    if channel.type == "wecom":
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return _post(
            channel.url,
            _json_body({"msgtype": "text", "text": {"content": text}}),
            headers,
        )

    if channel.type == "ntfy":
        base = (channel.url or "https://ntfy.sh").rstrip("/")
        query = urllib.parse.urlencode(
            {
                "title": f"{notification.status_label}｜{notification.title}",
                "tags": "bell",
            }
        )
        url = f"{base}/{urllib.parse.quote(channel.topic, safe='')}?{query}"
        headers.setdefault("Content-Type", "text/plain; charset=utf-8")
        headers.setdefault("Priority", _NTFY_PRIORITY.get(notification.priority, "3"))
        return _post(url, text.encode("utf-8"), headers)

    if channel.type == "bark":
        base = (channel.url or "https://api.day.app").rstrip("/")
        key = urllib.parse.quote(channel.device_key, safe="")
        headers.setdefault("Content-Type", "application/json; charset=utf-8")
        return _post(
            f"{base}/{key}",
            _json_body(
                {
                    "title": f"{notification.status_label}｜{notification.title}",
                    "body": text,
                    "group": "AgentBell",
                    "level": _BARK_LEVEL.get(notification.priority, "active"),
                }
            ),
            headers,
        )

    if channel.type == "telegram":
        token = urllib.parse.quote(channel.token, safe=":")
        data = urllib.parse.urlencode(
            {
                "chat_id": channel.chat_id,
                "text": f"[AgentBell] {text}",
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return _post(
            f"https://api.telegram.org/bot{token}/sendMessage", data, headers
        )

    return False, f"未知渠道类型：{channel.type}"


class ChannelDispatcher(QObject):
    """Background delivery worker so slow webhooks never block the UI thread."""

    delivered = Signal(str, bool, str)

    def __init__(self, logger: logging.Logger, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._logger = logger
        self._queue: queue.Queue[tuple[ChannelConfig, Notification]] = queue.Queue(
            maxsize=QUEUE_MAX_SIZE
        )
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="channel-delivery", daemon=True
        )
        self._thread.start()

    def dispatch(
        self, channels: tuple[ChannelConfig, ...], notification: Notification
    ) -> int:
        queued = 0
        for channel in channels:
            try:
                self._queue.put_nowait((channel, notification))
                queued += 1
            except queue.Full:
                self._logger.warning(
                    "外部渠道队列已满，丢弃 type=%s id=%s",
                    channel.type,
                    notification.id,
                )
        return queued

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                channel, notification = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            ok, detail = send(channel, notification)
            if ok:
                self._logger.info(
                    "外部渠道送达 type=%s id=%s", channel.type, notification.id
                )
            else:
                self._logger.warning(
                    "外部渠道发送失败 type=%s id=%s 原因=%s",
                    channel.type,
                    notification.id,
                    detail,
                )
            self.delivered.emit(channel.type, ok, detail)

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)
