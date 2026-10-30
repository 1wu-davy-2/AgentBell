from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ..models import Notification
from .icons import make_alert_icon

_STATUS_MARKS = {
    "succeeded": "✓",
    "failed": "✕",
    "canceled": "–",
    "running": "…",
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
        self._normal_icon = icon
        self._alert_icon = make_alert_icon()
        self._recent: list[Notification] = []
        self._unread = 0
        self._base_tooltip = (
            f"AgentBell · 127.0.0.1:{port} · "
            f"{'已鉴权' if auth_enabled else '未鉴权'}"
        )

        self.setToolTip(self._base_tooltip)

        self._flash_timer = QTimer(self)
        self._flash_timer.timeout.connect(self._toggle_flash)
        self._flash_on = False
        self._flash_remaining = 0
        self._flashing = False

        menu = QMenu()
        menu.setToolTipsVisible(True)

        listening = menu.addAction(f"AgentBell · 127.0.0.1:{port}")
        listening.setEnabled(False)
        auth = menu.addAction(
            "X-Token 鉴权：已开启" if auth_enabled else "X-Token 鉴权：未开启"
        )
        auth.setEnabled(False)
        self._unread_action = menu.addAction("0 条未读通知")
        self._unread_action.setEnabled(False)
        self._unread_action.setVisible(False)

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

    def set_unread(self, count: int) -> None:
        self._unread = max(0, int(count))
        self._unread_action.setText(f"{self._unread} 条未读通知")
        self._unread_action.setVisible(self._unread > 0)
        suffix = f" · {self._unread} 条未读" if self._unread else ""
        self.setToolTip(self._base_tooltip + suffix)

    def flash(self, times: int = 6) -> None:
        self._flash_remaining = max(1, times)
        self._flashing = True
        if not self._flash_timer.isActive():
            self._flash_timer.start(400)
        self._toggle_flash()

    def stop_flash(self) -> None:
        self._flash_timer.stop()
        self._flashing = False
        self._flash_on = False
        self.setIcon(self._normal_icon)

    def _toggle_flash(self) -> None:
        if self._flash_remaining <= 0:
            self.stop_flash()
            return
        self._flash_on = not self._flash_on
        self.setIcon(self._alert_icon if self._flash_on else self._normal_icon)
        self._flash_remaining -= 1

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        if not self._recent:
            empty = self._recent_menu.addAction("暂无通知")
            empty.setEnabled(False)
            return

        for notification in self._recent[:10]:
            mark = _STATUS_MARKS.get(notification.status, "•")
            unread = "● " if notification.needs_ack else ""
            label = (
                f"{unread}{mark}  {_clip(notification.title, 26)}"
                f"    {notification.effective_updated_at.strftime('%H:%M')}"
            )
            action = self._recent_menu.addAction(label)
            tooltip = notification.summary or notification.error or notification.headline
            action.setToolTip(" ".join(tooltip.split()))
            action.triggered.connect(
                lambda checked=False, item=notification: self.recent_selected.emit(item)
            )
