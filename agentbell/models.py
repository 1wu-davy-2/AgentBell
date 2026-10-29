from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

Status = Literal["succeeded", "failed", "canceled"]

STATUS_LABELS: dict[str, str] = {
    "succeeded": "已完成",
    "failed": "失败",
    "canceled": "已取消",
}


def safe_http_url(value: str | None) -> str | None:
    """Return a trimmed http(s) URL, or None for anything else."""
    if not value:
        return None
    value = value.strip()
    if not value or len(value) > 2048:
        return None
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value


@dataclass(frozen=True, slots=True)
class Notification:
    id: str
    title: str
    status: Status
    summary: str = ""
    duration: str = ""
    link: str | None = None
    error: str | None = None
    received_at: datetime = field(default_factory=lambda: datetime.now().astimezone())

    @property
    def headline(self) -> str:
        if self.status == "failed":
            return f"上一轮【{self.title}】执行失败"
        if self.status == "canceled":
            return f"上一轮【{self.title}】已取消"
        return f"上一轮【{self.title}】已完成，请查看"

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)
