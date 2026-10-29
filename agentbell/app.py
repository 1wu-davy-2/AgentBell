from __future__ import annotations

import logging
import queue
import socket
from collections import deque
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import AppConfig
from .models import Notification
from .server import UvicornServerThread
from .store import NotificationStore
from .ui.icons import make_app_icon
from .ui.toast import ToastManager
from .ui.tray import TrayIcon
from .ui.window import NotificationWindow

RECENT_LIMIT = 20


class AgentBellApp(QObject):
    server_failed = Signal(str)

    def __init__(
        self,
        qapp: QApplication,
        config: AppConfig,
        logger: logging.Logger,
        inbox: queue.Queue[Notification],
        store: NotificationStore,
        asgi_app: Any,
        listener: socket.socket,
    ) -> None:
        super().__init__()
        self.qapp = qapp
        self.config = config
        self.logger = logger
        self.inbox = inbox
        self.store = store
        self._recent: deque[Notification] = deque(maxlen=RECENT_LIMIT)
        self._shutting_down = False
        self._fatal_handled = False

        self.toasts = ToastManager(config.auto_close_seconds, logger)
        self.tray = TrayIcon(
            make_app_icon(),
            port=config.port,
            auth_enabled=config.auth_enabled,
            parent=self,
        )
        self.center = NotificationWindow(config, store, logger)
        self.server = UvicornServerThread(
            app=asgi_app,
            port=config.port,
            listener=listener,
            logger=logger,
            on_error=self.server_failed.emit,
        )

        self.tray.recent_selected.connect(self._show_recent)
        self.tray.open_center_requested.connect(self.open_notification_center)
        self.tray.quit_requested.connect(self.quit)
        self.center.replay_requested.connect(self._show_recent)
        self.center.quit_requested.connect(self.quit)
        self.server_failed.connect(self._on_server_failed)

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(120)
        self._drain_timer.timeout.connect(self._drain_inbox)

    def start(self) -> None:
        self.tray.show()
        self.server.start()
        self._drain_timer.start()
        self.qapp.aboutToQuit.connect(self.shutdown)
        auth_state = "已开启" if self.config.auth_enabled else "未开启"
        self.logger.info(
            "AgentBell 已就绪：http://127.0.0.1:%d（X-Token 鉴权%s）",
            self.config.port,
            auth_state,
        )

    def _drain_inbox(self) -> None:
        for _ in range(50):
            try:
                notification = self.inbox.get_nowait()
            except queue.Empty:
                return
            self._recent.appendleft(notification)
            self.tray.set_recent(list(self._recent))
            self.toasts.enqueue(notification)
            if self.center.isVisible():
                self.center.refresh_items(self.store.snapshot())

    def _show_recent(self, notification: Notification) -> None:
        if self._shutting_down:
            return
        self.logger.info("从托盘重新显示通知 id=%s", notification.id)
        self.toasts.enqueue(notification)

    def open_notification_center(self) -> None:
        if self._shutting_down:
            return
        self.center.show_center()

    def _on_server_failed(self, message: str) -> None:
        if self._shutting_down or self._fatal_handled:
            return
        self._fatal_handled = True
        self.logger.error("HTTP 服务异常：%s", message)
        QMessageBox.critical(
            None,
            "AgentBell 服务异常",
            f"本地 HTTP 服务意外停止：\n{message}\n\n程序将退出。请查看日志后重试。",
        )
        self.quit()

    def quit(self) -> None:
        if self._shutting_down:
            return
        self.qapp.quit()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._drain_timer.stop()
        self.toasts.close_all()
        self.server.stop()
        self.center.shutdown()
        self.tray.hide()
        self.logger.info("AgentBell 已退出")
