from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..models import Notification

_STATUS_MARKS = {
    "succeeded": "✓",
    "failed": "✕",
    "canceled": "–",
}


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TrayIcon(QSystemTrayIcon):
    recent_selected = Signal(object)
    open_center_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        icon: QIcon,
        port: int,
        auth_enabled: bool,
        parent=None,
    ) -> None:
        super().__init__(icon, parent)
        self._recent: list[Notification] = []

        suffix = "已鉴权" if auth_enabled else "未鉴权"
        self.setToolTip(f"AgentBell · 127.0.0.1:{port} · {suffix}")

        menu = QMenu()
        menu.setToolTipsVisible(True)

        listening = menu.addAction(f"AgentBell · 127.0.0.1:{port}")
        listening.setEnabled(False)
        auth = menu.addAction(
            "X-Token 鉴权：已开启" if auth_enabled else "X-Token 鉴权：未开启"
        )
        auth.setEnabled(False)

        menu.addSeparator()
        open_center = menu.addAction("打开通知中心")
        open_center.triggered.connect(self.open_center_requested.emit)
        self._recent_menu = menu.addMenu("显示最近通知")
        self._recent_menu.aboutToShow.connect(self._rebuild_recent_menu)
        menu.addSeparator()

        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self.quit_requested.emit)
        self.setContextMenu(menu)

    def set_recent(self, notifications: list[Notification]) -> None:
        self._recent = list(notifications)

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        if not self._recent:
            empty = self._recent_menu.addAction("暂无通知")
            empty.setEnabled(False)
            return

        for notification in self._recent[:10]:
            mark = _STATUS_MARKS.get(notification.status, "•")
            label = (
                f"{mark}  {_clip(notification.title, 28)}"
                f"    {notification.received_at.strftime('%H:%M')}"
            )
            action = self._recent_menu.addAction(label)
            tooltip = notification.summary or notification.error or notification.headline
            action.setToolTip(" ".join(tooltip.split()))
            action.triggered.connect(
                lambda checked=False, item=notification: self.recent_selected.emit(item)
            )
