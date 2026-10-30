from __future__ import annotations

import logging
import queue
import socket
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from .agent_sessions import AgentSessionScanner
from .channels import ChannelDispatcher
from .config import AppConfig
from .hotkey import GlobalHotkey
from .models import Notification, NotificationAction, safe_callback_url, safe_http_url
from .policy import Decision, Presence, decide, quiet_hours_end
from .presence import PresenceMonitor
from .server import UvicornServerThread
from .store import NotificationStore
from .ui.icons import make_app_icon
from .ui.toast import ToastManager
from .ui.tray import TrayIcon
from .ui.window import NotificationWindow

RECENT_LIMIT = 20
MAX_INBOX_BATCH = 50
DIGEST_MIN_DELAY_MS = 1500


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
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.qapp = qapp
        self.config = config
        self.logger = logger
        self.inbox = inbox
        self.store = store
        self.config_path = config_path
        self._recent: deque[Notification] = deque(maxlen=RECENT_LIMIT)
        self._shutting_down = False
        self._fatal_handled = False
        self._unread = 0
        self._presence = Presence()
        self._deferred: list[tuple[Notification, str]] = []
        self._digest_buffer: list[Notification] = []
        self._popup_times: deque[float] = deque()
        self._last_popup_at = 0.0
        self._escalation_timers: dict[str, QTimer] = {}
        self._snooze_timers: dict[str, QTimer] = {}

        self.toasts = ToastManager(
            config.auto_close_seconds,
            logger,
            templates=config.templates,
            popup_mode=config.popup_mode,
            popup_skin=config.popup_skin,
        )
        self.tray = TrayIcon(
            make_app_icon(),
            port=config.port,
            auth_enabled=config.auth_enabled,
            parent=self,
        )
        self.center = NotificationWindow(
            config, store, logger, config_path=config_path
        )
        self.session_scanner = AgentSessionScanner(
            config.agent_sessions, logger, self
        )
        self.server = UvicornServerThread(
            app=asgi_app,
            port=config.port,
            listener=listener,
            logger=logger,
            on_error=self.server_failed.emit,
        )
        self.presence_monitor = PresenceMonitor(config, self)
        self.channels = ChannelDispatcher(logger, self)
        self.hotkey = GlobalHotkey(config.hotkey, logger, self)

        self.tray.recent_selected.connect(self._show_recent)
        self.tray.open_center_requested.connect(self.open_notification_center)
        self.tray.quit_requested.connect(self.quit)
        self.center.replay_requested.connect(self._show_recent)
        self.center.quit_requested.connect(self.quit)
        self.center.ack_requested.connect(self._acknowledge)
        self.center.snooze_requested.connect(self._snooze)
        self.center.action_requested.connect(self._run_action)
        self.center.settings_saved.connect(self._apply_config)
        self.center.center_shown.connect(self._mark_read)
        self.center.session_refresh_requested.connect(self.session_scanner.refresh)
        self.session_scanner.scanned.connect(self.center.update_sessions)
        self.session_scanner.failed.connect(self._on_session_scan_failed)
        self.toasts.acknowledged.connect(self._acknowledge)
        self.toasts.snooze_requested.connect(self._snooze)
        self.toasts.action_requested.connect(self._run_action)
        self.toasts.center_requested.connect(self.open_notification_center)
        self.server_failed.connect(self._on_server_failed)
        self.hotkey.activated.connect(self.open_notification_center)
        self.presence_monitor.changed.connect(self._on_presence_changed)

        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(120)
        self._drain_timer.timeout.connect(self._drain_inbox)

        self._digest_timer = QTimer(self)
        self._digest_timer.setSingleShot(True)
        self._digest_timer.timeout.connect(self._flush_digest)

        self._deferred_timer = QTimer(self)
        self._deferred_timer.setSingleShot(True)
        self._deferred_timer.timeout.connect(self._flush_deferred)

    def start(self) -> None:
        self.tray.show()
        self.server.start()
        self.presence_monitor.start()
        self.session_scanner.start()
        self.hotkey.register()
        self._drain_timer.start()
        self.qapp.aboutToQuit.connect(self.shutdown)
        auth_state = "已开启" if self.config.auth_enabled else "未开启"
        self.logger.info(
            "AgentBell 已就绪：http://127.0.0.1:%d（X-Token 鉴权%s）",
            self.config.port,
            auth_state,
        )

    # ---------- inbox ----------

    def _drain_inbox(self) -> None:
        handled = 0
        while handled < MAX_INBOX_BATCH:
            try:
                notification = self.inbox.get_nowait()
            except queue.Empty:
                break
            handled += 1
            self._recent.appendleft(notification)
            self.tray.set_recent(list(self._recent))
            if notification.occurrence_count <= 1 and not self.center.isVisible():
                self._unread += 1
                self.tray.set_unread(self._unread)
            self._handle_notification(notification)
        if handled and self.center.isVisible():
            self.center.refresh_items(self.store.snapshot())

    def _handle_notification(self, notification: Notification) -> None:
        if notification.is_expired():
            self.logger.info("通知已过期，跳过提醒 id=%s", notification.id)
            return

        decision = decide(notification, self.config, self._presence)
        resolved = decision.notification
        if (
            resolved.require_ack != notification.require_ack
            or resolved.auto_close_seconds != notification.auto_close_seconds
        ):
            resolved = self.store.replace_notification(resolved)

        self._dispatch_channels(resolved, decision)

        if self.toasts.has_visible(resolved.id):
            self.toasts.enqueue(resolved)
            return

        if not decision.popup:
            if decision.defer_reason:
                self._deferred.append((resolved, decision.defer_reason))
                self.logger.info(
                    "通知延后提醒 id=%s 原因=%s 优先级=%s",
                    resolved.id,
                    decision.defer_reason,
                    resolved.priority,
                )
                self._schedule_deferred_flush()
            return

        if resolved.priority == "critical":
            self._show(resolved)
            return

        now = time.monotonic()
        if self._should_digest(now):
            self._digest_buffer.append(resolved)
            self.logger.info("通知进入聚合摘要 id=%s", resolved.id)
            self._schedule_digest(now)
            return

        self._show(resolved)

    def _show(self, notification: Notification) -> None:
        if self._shutting_down:
            return
        self.toasts.enqueue(notification)
        self._last_popup_at = time.monotonic()
        self._popup_times.append(self._last_popup_at)
        self._play_sound(notification)
        self._schedule_escalation(notification)

    def _dispatch_channels(self, notification: Notification, decision: Decision) -> None:
        if not decision.channel_types:
            return
        if notification.status == "running":
            return
        if notification.occurrence_count > 1 and notification.status not in {
            "failed",
            "canceled",
        }:
            return
        channels = tuple(
            channel
            for channel in self.config.channels
            if channel.type in decision.channel_types
        )
        count = self.channels.dispatch(channels, notification)
        if count:
            self.logger.info(
                "通知转投外部渠道 id=%s 渠道=%s",
                notification.id,
                ",".join(channel.type for channel in channels),
            )

    # ---------- popup pacing ----------

    def _should_digest(self, now: float) -> bool:
        if not self.config.digest.enabled:
            self._popup_times.clear()
            return False
        cooldown = self.config.popup_cooldown_seconds
        if cooldown > 0 and self._last_popup_at > 0:
            if now - self._last_popup_at < cooldown:
                return True
        frontier = now - max(1, self.config.digest.window_seconds)
        while self._popup_times and self._popup_times[0] < frontier:
            self._popup_times.popleft()
        return len(self._popup_times) + 1 >= max(2, self.config.digest.threshold)

    def _schedule_digest(self, now: float) -> None:
        delay = DIGEST_MIN_DELAY_MS
        if self.config.popup_cooldown_seconds > 0 and self._last_popup_at > 0:
            remaining = self.config.popup_cooldown_seconds - (
                now - self._last_popup_at
            )
            delay = max(delay, int(remaining * 1000) + 200)
        self._digest_timer.start(delay)

    def _flush_digest(self) -> None:
        if self._shutting_down or not self._digest_buffer:
            return
        items = self._digest_buffer
        self._digest_buffer = []
        reason = self._suppression_reason()
        if reason:
            for item in items:
                self._deferred.append((item, reason))
            self._schedule_deferred_flush()
            return
        if len(items) == 1:
            self._show(items[0])
            return
        self.toasts.show_digest(items)
        self._last_popup_at = time.monotonic()
        self._popup_times.append(self._last_popup_at)
        self.logger.info("聚合摘要弹窗：%d 条通知", len(items))

    def _suppression_reason(self) -> str:
        probe = Notification(
            id="probe",
            title="probe",
            status="succeeded",
            priority="normal",
        )
        decision = decide(probe, self.config, self._presence)
        return decision.defer_reason

    def _hold_locked(self) -> bool:
        return self.config.hold_when_locked and self._presence.locked

    def _schedule_deferred_flush(self) -> None:
        if not self._deferred:
            return
        now = datetime.now().astimezone()
        delay_ms = 30000
        reason = self._suppression_reason()
        if reason == "quiet_hours":
            end = quiet_hours_end(self.config.quiet_hours, now)
            delay_ms = max(1000, int((end - now).total_seconds() * 1000) + 1000)
        elif reason:
            delay_ms = 30000
        else:
            delay_ms = 500
        self._deferred_timer.start(delay_ms)

    def _flush_deferred(self) -> None:
        if self._shutting_down or not self._deferred:
            return
        now = datetime.now().astimezone()
        still: list[tuple[Notification, str]] = []
        ready: list[Notification] = []
        for notification, _reason in self._deferred:
            if notification.is_expired(now):
                continue
            decision = decide(notification, self.config, self._presence, now)
            if decision.popup:
                ready.append(decision.notification)
            elif decision.defer_reason:
                still.append((decision.notification, decision.defer_reason))
        self._deferred = still
        if ready:
            if len(ready) == 1:
                self._show(ready[0])
            else:
                self.toasts.show_digest(ready)
                self._last_popup_at = time.monotonic()
                self._popup_times.append(self._last_popup_at)
            self.logger.info("延时提醒已送达：%d 条", len(ready))
        if still:
            self._schedule_deferred_flush()

    def _on_presence_changed(self, presence: Presence) -> None:
        previous = self._presence
        self._presence = presence
        if previous.fullscreen != presence.fullscreen:
            self.logger.info(
                "全屏状态变化：%s", "进入全屏" if presence.fullscreen else "退出全屏"
            )
        if previous.meeting_process != presence.meeting_process:
            if presence.meeting_process:
                self.logger.info("检测到会议程序：%s", presence.meeting_process)
            else:
                self.logger.info("会议程序已结束")
        if previous.locked != presence.locked:
            if presence.locked:
                self.logger.info("检测到锁屏或息屏，弹窗计时暂停并暂缓新提醒")
            else:
                self.logger.info("已解锁，恢复弹窗计时并补发提醒")
            self.toasts.set_paused(
                presence.locked and self.config.hold_when_locked
            )
        if (
            not presence.fullscreen
            and not presence.meeting_process
            and not (presence.locked and self.config.hold_when_locked)
        ):
            self._flush_deferred()

    # ---------- escalation / snooze ----------

    def _schedule_escalation(self, notification: Notification, attempt: int = 0) -> None:
        settings = self.config.escalation
        if settings.unread_seconds <= 0 or settings.max_times <= 0:
            return
        if not notification.needs_ack:
            return
        if attempt >= settings.max_times:
            return
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(
            lambda: self._fire_escalation(notification.id, attempt + 1)
        )
        timer.start(max(5, settings.unread_seconds) * 1000)
        old = self._escalation_timers.pop(notification.id, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        self._escalation_timers[notification.id] = timer

    def _fire_escalation(self, notification_id: str, attempt: int) -> None:
        self._escalation_timers.pop(notification_id, None)
        if self._shutting_down:
            return
        stored = self.store.find(notification_id)
        if stored is None or not stored.needs_ack:
            return
        if self._hold_locked():
            self.logger.info("锁屏中，升级提醒暂缓 id=%s", notification_id)
            self._schedule_escalation(stored, max(0, attempt - 1))
            return
        if self.toasts.has_visible(notification_id):
            self.toasts.pulse(notification_id)
        else:
            self.toasts.enqueue(stored)
        if self.config.escalation.flash_tray:
            self.tray.flash()
        if self.config.escalation.sound:
            self._play_sound(stored, force=True)
        self.logger.info(
            "未确认提醒升级 id=%s 次数=%d priority=%s",
            notification_id,
            attempt,
            stored.priority,
        )
        self._schedule_escalation(stored, attempt)

    def _cancel_escalation(self, notification_id: str) -> None:
        timer = self._escalation_timers.pop(notification_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _snooze(self, notification_id: str, minutes: int) -> None:
        minutes = max(1, min(720, int(minutes)))
        stored = self.store.find(notification_id)
        if stored is None:
            return
        self._cancel_escalation(notification_id)
        self.toasts.dismiss_toast(notification_id, "snooze")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: self._deliver_snoozed(notification_id))
        timer.start(minutes * 60 * 1000)
        old = self._snooze_timers.pop(notification_id, None)
        if old is not None:
            old.stop()
            old.deleteLater()
        self._snooze_timers[notification_id] = timer
        self.logger.info("通知稍后提醒 id=%s 延迟=%d 分钟", notification_id, minutes)

    def _deliver_snoozed(self, notification_id: str) -> None:
        self._snooze_timers.pop(notification_id, None)
        if self._shutting_down:
            return
        stored = self.store.find(notification_id)
        if stored is None or not stored.needs_ack:
            return
        if self._hold_locked():
            self._deferred.append((stored, "locked"))
            self._schedule_deferred_flush()
            self.logger.info("锁屏中，稍后提醒延后 id=%s", notification_id)
            return
        self.toasts.enqueue(stored)
        self._play_sound(stored, force=True)
        self._schedule_escalation(stored)
        self.logger.info("稍后提醒已送达 id=%s", notification_id)

    # ---------- actions ----------

    def _acknowledge(self, notification_id: str) -> None:
        updated = self.store.acknowledge(notification_id)
        self._cancel_escalation(notification_id)
        timer = self._snooze_timers.pop(notification_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        if updated is not None:
            self.logger.info("通知已确认 id=%s", notification_id)
        if self.center.isVisible():
            self.center.refresh_items(self.store.snapshot())

    def _run_action(self, notification: Notification, action: NotificationAction) -> None:
        if action.kind == "open":
            url = safe_http_url(action.value or notification.link)
            if url:
                QDesktopServices.openUrl(QUrl(url))
                self.logger.info("打开通知链接 id=%s", notification.id)
            return
        if action.kind == "path":
            if not action.value:
                return
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(action.value))
            self.logger.info(
                "打开本地路径 id=%s 成功=%s", notification.id, bool(opened)
            )
            return
        if action.kind == "copy":
            QGuiApplication.clipboard().setText(action.value)
            self.tray.showMessage(
                "AgentBell", "内容已复制到剪贴板", make_app_icon(), 2500
            )
            self.logger.info("复制通知内容 id=%s", notification.id)
            return
        if action.kind == "retry":
            url = safe_callback_url(action.value)
            if not url:
                self.logger.warning("忽略非回环重试地址 id=%s", notification.id)
                return
            self.logger.info("触发重试回调 id=%s", notification.id)
            threading.Thread(
                target=self._post_retry,
                args=(url, notification),
                name="retry-callback",
                daemon=True,
            ).start()
            return
        if action.kind == "center":
            self.open_notification_center()

    def _post_retry(self, url: str, notification: Notification) -> None:
        import json

        body = json.dumps(
            {
                "action": "retry",
                "id": notification.id,
                "title": notification.title,
                "source": notification.source,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                response.read(4096)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            self.logger.warning("重试回调失败 id=%s：%s", notification.id, exc)

    # ---------- sound ----------

    def _play_sound(self, notification: Notification, force: bool = False) -> None:
        sounds = self.config.sounds
        key = notification.status
        if notification.priority == "critical" and sounds.get("critical"):
            key = "critical"
        path = sounds.get(key) or sounds.get(notification.status) or ""
        if not path:
            return
        if not force and notification.silent and not notification.require_ack:
            return
        if not Path(path).is_file():
            return
        try:
            import winsound

            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except (ImportError, RuntimeError) as exc:
            self.logger.warning("播放提示音失败：%s", exc)

    # ---------- ui ----------

    def _show_recent(self, notification: Notification) -> None:
        if self._shutting_down:
            return
        self.logger.info("从托盘重新显示通知 id=%s", notification.id)
        self.toasts.enqueue(notification)

    def open_notification_center(self) -> None:
        if self._shutting_down:
            return
        self.center.show_center()

    def _mark_read(self) -> None:
        if self._unread:
            self._unread = 0
            self.tray.set_unread(0)

    def _on_session_scan_failed(self, message: str) -> None:
        self.logger.warning("Agent 会话扫描失败：%s", message)

    def _apply_config(self, config: AppConfig) -> None:
        self.config = config
        self.toasts.set_auto_close(config.auto_close_seconds)
        self.toasts.set_templates(config.templates)
        self.toasts.set_appearance(config.popup_mode, config.popup_skin)
        self.toasts.set_paused(config.hold_when_locked and self._presence.locked)
        self.presence_monitor.apply_config(config)
        self.session_scanner.apply_config(config.agent_sessions)
        self.hotkey.apply(config.hotkey)
        self.center.apply_config(config)
        try:
            from .autostart import configure_autostart

            configure_autostart(config.autostart, self.logger)
        except Exception as exc:  # pragma: no cover - defensive
            self.logger.warning("应用开机自启设置失败：%s", exc)
        self.logger.info("设置已更新并应用")

    # ---------- lifecycle ----------

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
        self._digest_timer.stop()
        self._deferred_timer.stop()
        for timer in self._escalation_timers.values():
            timer.stop()
            timer.deleteLater()
        self._escalation_timers.clear()
        for timer in self._snooze_timers.values():
            timer.stop()
            timer.deleteLater()
        self._snooze_timers.clear()
        self.presence_monitor.stop()
        self.session_scanner.stop()
        self.hotkey.unregister()
        self.channels.stop()
        self.toasts.close_all()
        self.server.stop()
        self.center.shutdown()
        self.tray.hide()
        self.store.close()
        self.logger.info("AgentBell 已退出")
