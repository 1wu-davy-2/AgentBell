from __future__ import annotations

from collections import deque
from threading import Lock

from .models import Notification

DEFAULT_HISTORY_LIMIT = 200


class NotificationStore:
    def __init__(self, limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._items: deque[Notification] = deque(maxlen=limit)
        self._lock = Lock()

    def add(self, notification: Notification) -> None:
        with self._lock:
            self._items.appendleft(notification)

    def snapshot(self) -> list[Notification]:
        with self._lock:
            return list(self._items)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)
