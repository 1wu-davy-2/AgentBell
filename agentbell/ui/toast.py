from __future__ import annotations

import html
import logging
import time
from collections import deque

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QObject,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QTimer,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import Notification, safe_http_url
from .icons import status_color, status_pixmap

CARD_WIDTH = 400
SHADOW_MARGIN = 12
WINDOW_WIDTH = CARD_WIDTH + SHADOW_MARGIN * 2
EDGE_MARGIN = 12
TOAST_GAP = 8
MAX_VISIBLE = 5

_TITLE_LIMIT = 32
_SUMMARY_LIMIT = 56
_ERROR_LIMIT = 34
_DURATION_LIMIT = 18


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _escaped(text: str) -> str:
    return html.escape(text, quote=False)


class ToastWindow(QWidget):
    dismissed = Signal(object, str)

    def __init__(
        self,
        notification: Notification,
        auto_close_seconds: int,
        logger: logging.Logger,
    ) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(None, flags)
        self.notification = notification
        self._logger = logger
        self._timeout_seconds = max(0, int(auto_close_seconds))
        self._remaining = float(self._timeout_seconds)
        self._last_tick = time.monotonic()
        self._closing = False
        self._reason = ""
        self._link = safe_http_url(notification.link)
        self._entry_animation: QParallelAnimationGroup | None = None
        self._move_animation: QPropertyAnimation | None = None
        self._fade_out_animation: QPropertyAnimation | None = None
        self._summary_label: QLabel | None = None

        self.setObjectName("toastRoot")
        self.setWindowTitle("AgentBell 通知")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        mac_attribute = getattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow", None)
        if mac_attribute is not None:
            self.setAttribute(mac_attribute, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedWidth(WINDOW_WIDTH)
        self.setAccessibleName("AgentBell 通知")
        self.setAccessibleDescription(notification.headline)

        self._build_ui()
        self._apply_style()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._on_tick)

        self.ensurePolished()
        if self._summary_label is not None:
            metrics = self._summary_label.fontMetrics()
            bounds = metrics.boundingRect(
                QRect(0, 0, CARD_WIDTH - 38, 1000),
                Qt.TextFlag.TextWordWrap,
                self._summary_label.text(),
            )
            one_line = bounds.height() <= metrics.lineSpacing() + 2
            self._summary_label.setFixedHeight(18 if one_line else 34)
        self.layout().activate()
        self.setFixedHeight(self.sizeHint().height())

    # ---------- construction ----------

    def _build_ui(self) -> None:
        notification = self.notification
        accent = status_color(notification.status)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(
            SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN
        )
        outer.setSpacing(0)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 7)
        shadow.setColor(accent.darker(350))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        icon = QLabel(self.card)
        icon.setFixedSize(38, 38)
        icon.setPixmap(status_pixmap(notification.status, 38))
        icon.setAccessibleName(notification.status_label)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)

        title_text = _clip(notification.title, _TITLE_LIMIT)
        if notification.status == "failed":
            headline = f"上一轮【{title_text}】执行失败"
        elif notification.status == "canceled":
            headline = f"上一轮【{title_text}】已取消"
        else:
            headline = f"上一轮【{title_text}】已完成，请查看"

        title = QLabel(headline, self.card)
        title.setObjectName("title")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setFixedHeight(40)
        title.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        title.setToolTip(_escaped(notification.headline))
        header.addWidget(title, 1)
        root.addLayout(header)

        root.addSpacing(8)

        summary_text = notification.summary
        error_extra = ""
        if notification.status == "failed":
            if not summary_text:
                summary_text = (
                    f"错误：{notification.error}"
                    if notification.error
                    else "执行失败，未提供更多信息"
                )
            elif notification.error:
                error_extra = f"错误：{_clip(notification.error, _ERROR_LIMIT)}"

        if summary_text:
            summary = QLabel(_clip(summary_text, _SUMMARY_LIMIT), self.card)
            summary.setObjectName("summary")
            summary.setTextFormat(Qt.TextFormat.PlainText)
            summary.setWordWrap(True)
            summary.setFixedHeight(36)
            summary.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            summary.setToolTip(_escaped(" ".join(summary_text.split())))
            self._summary_label = summary
            root.addWidget(summary)
            if error_extra:
                root.addSpacing(3)
                error_label = QLabel(error_extra, self.card)
                error_label.setObjectName("error")
                error_label.setTextFormat(Qt.TextFormat.PlainText)
                error_label.setFixedHeight(17)
                error_label.setToolTip(
                    _escaped(" ".join((notification.error or "").split()))
                )
                root.addWidget(error_label)

        root.addSpacing(8)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        meta_parts = []
        if notification.duration:
            meta_parts.append(f"耗时 {_clip(notification.duration, _DURATION_LIMIT)}")
        meta_parts.append(notification.received_at.strftime("%H:%M"))
        meta = QLabel(" · ".join(meta_parts), self.card)
        meta.setObjectName("meta")
        meta.setTextFormat(Qt.TextFormat.PlainText)
        bottom.addWidget(meta, 1)

        self.view_button = QPushButton("查看", self.card)
        self.view_button.setObjectName("view")
        self.view_button.setFixedHeight(28)
        self.view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self._link:
            self.view_button.setToolTip(_escaped(self._link))
            self.view_button.clicked.connect(self._on_view_clicked)
        else:
            self.view_button.setEnabled(False)
            self.view_button.setToolTip("此通知未提供可打开的链接")
        bottom.addWidget(self.view_button)

        self.ack_button = QPushButton("知道了", self.card)
        self.ack_button.setObjectName("ack")
        self.ack_button.setFixedHeight(28)
        self.ack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ack_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ack_button.clicked.connect(lambda: self.dismiss("ack"))
        bottom.addWidget(self.ack_button)

        root.addLayout(bottom)

        self.progress: QProgressBar | None = None
        if self._timeout_seconds > 0:
            root.addSpacing(10)
            self.progress = QProgressBar(self.card)
            self.progress.setObjectName("countdown")
            self.progress.setRange(0, 1000)
            self.progress.setValue(1000)
            self.progress.setTextVisible(False)
            self.progress.setFixedHeight(3)
            self.progress.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.progress.setToolTip("自动关闭倒计时（鼠标悬停可暂停）")
            root.addWidget(self.progress)

    def _apply_style(self) -> None:
        accent = status_color(self.notification.status).name()
        self.setStyleSheet(
            f"""
            QWidget#toastRoot {{
                background: transparent;
            }}
            QFrame#card {{
                background-color: #171A21;
                border: 1px solid #2A303B;
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
                color: #A9B2C0;
            }}
            QLabel#title {{
                color: #F3F6FA;
                font-size: 14px;
                font-weight: 600;
            }}
            QLabel#summary {{
                color: #A9B2C0;
                font-size: 12px;
            }}
            QLabel#error {{
                color: {accent};
                font-size: 11px;
            }}
            QLabel#meta {{
                color: #778192;
                font-size: 11px;
            }}
            QPushButton {{
                font-size: 12px;
                border-radius: 8px;
                padding: 0px 12px;
            }}
            QPushButton#view {{
                background-color: #4F8CFF;
                color: #FFFFFF;
                font-weight: 600;
                border: none;
            }}
            QPushButton#view:hover {{
                background-color: #669CFF;
            }}
            QPushButton#view:pressed {{
                background-color: #3F7AE8;
            }}
            QPushButton#view:disabled {{
                background-color: #2B3240;
                color: #6D7788;
            }}
            QPushButton#ack {{
                background-color: transparent;
                color: #DDE3EC;
                border: 1px solid #343C49;
            }}
            QPushButton#ack:hover {{
                background-color: #232A36;
                border-color: #465164;
            }}
            QPushButton#ack:pressed {{
                background-color: #1C222C;
            }}
            QProgressBar#countdown {{
                background-color: #252C38;
                border: none;
                border-radius: 1px;
            }}
            QProgressBar#countdown::chunk {{
                background-color: {accent};
                border-radius: 1px;
            }}
            """
        )

    # ---------- display / animation ----------

    def show_at(self, target: QPoint) -> None:
        self.move(target + QPoint(24, 0))
        self.setWindowOpacity(0.0)
        self.show()

        slide = QPropertyAnimation(self, b"pos", self)
        slide.setDuration(220)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.setStartValue(target + QPoint(24, 0))
        slide.setEndValue(target)

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(170)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)

        group = QParallelAnimationGroup(self)
        group.addAnimation(slide)
        group.addAnimation(fade)
        self._entry_animation = group
        group.start()

        self._last_tick = time.monotonic()
        if self._timeout_seconds > 0:
            self._tick_timer.start()

    def move_to(self, target: QPoint) -> None:
        if self._closing or self.pos() == target:
            return
        if self._entry_animation is not None:
            if self._entry_animation.state() == QAbstractAnimation.State.Running:
                self._entry_animation.stop()
            self._entry_animation = None
            self.setWindowOpacity(1.0)
        if self._move_animation is not None:
            self._move_animation.stop()
            self._move_animation.deleteLater()

        animation = QPropertyAnimation(self, b"pos", self)
        animation.setDuration(170)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.setStartValue(self.pos())
        animation.setEndValue(target)
        self._move_animation = animation
        animation.start()

    # ---------- countdown ----------

    def _cursor_over_card(self) -> bool:
        local = self.card.mapFromGlobal(QCursor.pos())
        return self.card.rect().contains(local)

    def _on_tick(self) -> None:
        if self._closing or self._timeout_seconds <= 0:
            return
        now = time.monotonic()
        if self._cursor_over_card():
            self._last_tick = now
            return
        elapsed = now - self._last_tick
        self._last_tick = now
        self._remaining = max(0.0, self._remaining - elapsed)
        if self.progress is not None:
            self.progress.setValue(
                int(1000 * self._remaining / self._timeout_seconds)
            )
        if self._remaining <= 0.001:
            self.dismiss("timeout")

    # ---------- actions ----------

    def _on_view_clicked(self) -> None:
        if not self._link:
            return
        self._logger.info(
            "点击查看 id=%s url=%s", self.notification.id, _clip(self._link, 200)
        )
        opened = QDesktopServices.openUrl(QUrl(self._link))
        if not opened:
            self._logger.warning("打开链接失败 id=%s url=%s", self.notification.id, self._link)
            return
        self.dismiss("view")

    def dismiss(self, reason: str) -> None:
        if self._closing:
            return
        self._closing = True
        self._reason = reason
        self._tick_timer.stop()
        if self._entry_animation is not None:
            self._entry_animation.stop()
            self._entry_animation = None
        if self._move_animation is not None:
            self._move_animation.stop()

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(130)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.finished.connect(self._finish_dismiss)
        self._fade_out_animation = fade
        fade.start()

    def _finish_dismiss(self) -> None:
        self.hide()
        self.dismissed.emit(self.notification, self._reason)

    def close_now(self) -> None:
        self._closing = True
        self._tick_timer.stop()
        if self._entry_animation is not None:
            self._entry_animation.stop()
        if self._move_animation is not None:
            self._move_animation.stop()
        if self._fade_out_animation is not None:
            self._fade_out_animation.stop()
        self.hide()


class ToastManager(QObject):
    def __init__(
        self,
        auto_close_seconds: int,
        logger: logging.Logger,
        visible_limit: int = MAX_VISIBLE,
    ) -> None:
        super().__init__()
        self._auto_close_seconds = auto_close_seconds
        self._logger = logger
        self._visible_limit = visible_limit
        self._active: list[ToastWindow] = []
        self._pending: deque[Notification] = deque()
        self._shutting_down = False

    def enqueue(self, notification: Notification) -> bool:
        if self._shutting_down:
            return False
        if any(
            toast.notification.id == notification.id for toast in self._active
        ) or any(item.id == notification.id for item in self._pending):
            self._logger.info("忽略重复弹窗 id=%s", notification.id)
            return False

        if len(self._active) >= self._visible_limit or self._pending:
            self._pending.append(notification)
            self._logger.info(
                "弹窗排队 id=%s 可见=%d 排队=%d",
                notification.id,
                len(self._active),
                len(self._pending),
            )
            return True

        self._present(notification)
        return True

    def _present(self, notification: Notification) -> None:
        toast = ToastWindow(notification, self._auto_close_seconds, self._logger)
        toast.dismissed.connect(self._on_dismissed)
        self._active.append(toast)

        x, y = self._next_position()
        toast.show_at(QPoint(x, y))
        self._logger.info(
            "弹窗显示 id=%s status=%s 可见=%d 排队=%d",
            notification.id,
            notification.status,
            len(self._active),
            len(self._pending),
        )

    def _screen_geometry(self) -> object:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        return screen.availableGeometry()

    def _next_position(self) -> tuple[int, int]:
        geometry = self._screen_geometry()
        if geometry is None:
            x = 120
            top = 20
        else:
            x = geometry.x() + geometry.width() - WINDOW_WIDTH - EDGE_MARGIN
            top = geometry.y() + EDGE_MARGIN
        used = sum(toast.height() for toast in self._active[:-1])
        used += TOAST_GAP * max(0, len(self._active) - 1)
        return x, top + used

    def _reposition(self) -> None:
        geometry = self._screen_geometry()
        if geometry is None:
            x = 120
            top = 20
        else:
            x = geometry.x() + geometry.width() - WINDOW_WIDTH - EDGE_MARGIN
            top = geometry.y() + EDGE_MARGIN
        y = top
        for toast in self._active:
            toast.move_to(QPoint(x, y))
            y += toast.height() + TOAST_GAP

    def _on_dismissed(self, notification: Notification, reason: str) -> None:
        toast = next(
            (
                item
                for item in self._active
                if item.notification.id == notification.id
            ),
            None,
        )
        if toast is None:
            return
        self._active.remove(toast)
        toast.deleteLater()

        reason_text = {
            "ack": "用户点击知道了",
            "view": "用户点击查看",
            "timeout": f"{self._auto_close_seconds} 秒自动关闭",
        }.get(reason, reason)
        self._logger.info(
            "弹窗关闭 id=%s 原因=%s 可见=%d 排队=%d",
            notification.id,
            reason_text,
            len(self._active),
            len(self._pending),
        )
        self._reposition()
        if self._pending and not self._shutting_down:
            QTimer.singleShot(60, self._show_next)

    def _show_next(self) -> None:
        if self._shutting_down:
            return
        while self._pending and len(self._active) < self._visible_limit:
            self._present(self._pending.popleft())

    def close_all(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        count = len(self._active) + len(self._pending)
        for toast in self._active:
            toast.close_now()
            toast.deleteLater()
        self._active.clear()
        self._pending.clear()
        if count:
            self._logger.info("已关闭全部弹窗，共 %d 条", count)
