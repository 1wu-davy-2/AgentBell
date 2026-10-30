from __future__ import annotations

import html
import logging
import time
import uuid
from collections import deque
from typing import Mapping

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
    QMenu,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import (
    POPUP_MODES,
    POPUP_SKINS,
    Notification,
    NotificationAction,
    safe_http_url,
)
from .icons import priority_color, status_color, status_pixmap

CARD_WIDTH = 400
CENTER_CARD_WIDTH = 470
OVERLAY_CARD_WIDTH = 540
SHADOW_MARGIN = 12
WINDOW_WIDTH = CARD_WIDTH + SHADOW_MARGIN * 2
EDGE_MARGIN = 12
TOAST_GAP = 8
MAX_VISIBLE = 5

_MODAL_MODES = {"center", "overlay"}

_SKIN_PALETTES: dict[str, dict[str, str]] = {
    "midnight": {
        "card": "#171A21",
        "border": "#2A303B",
        "title": "#F3F6FA",
        "text": "#A9B2C0",
        "muted": "#778192",
        "bar": "#252C38",
        "button_bg": "#232A36",
        "button_border": "#343C49",
        "button_hover": "#2C3543",
        "button_hover_border": "#4A566A",
        "backdrop": "rgba(9, 12, 18, 165)",
        "error": "",
    },
    "light": {
        "card": "#FFFFFF",
        "border": "#E3E7ED",
        "title": "#1F2329",
        "text": "#5A6472",
        "muted": "#8A919D",
        "bar": "#EEF1F6",
        "button_bg": "#F5F6FA",
        "button_border": "#DDE1E8",
        "button_hover": "#EAF1FF",
        "button_hover_border": "#C9DBFF",
        "backdrop": "rgba(20, 28, 40, 110)",
        "error": "#C24141",
    },
    "ocean": {
        "card": "#0F2730",
        "border": "#1E4552",
        "title": "#EAF7FA",
        "text": "#A7C5CD",
        "muted": "#6E929C",
        "bar": "#173A45",
        "button_bg": "#16333D",
        "button_border": "#24505F",
        "button_hover": "#1C4250",
        "button_hover_border": "#2E6475",
        "backdrop": "rgba(4, 18, 24, 170)",
        "error": "",
    },
    "amber": {
        "card": "#2A2014",
        "border": "#4A3A22",
        "title": "#FBF1DF",
        "text": "#D8C2A2",
        "muted": "#A08A6B",
        "bar": "#3A2C1B",
        "button_bg": "#332619",
        "button_border": "#4E3C26",
        "button_hover": "#3E2F1E",
        "button_hover_border": "#67512F",
        "backdrop": "rgba(16, 11, 6, 170)",
        "error": "",
    },
}


def _normalized_mode(mode: str | None) -> str:
    return mode if mode in POPUP_MODES else "corner"


def _normalized_skin(skin: str | None) -> str:
    return skin if skin in POPUP_SKINS else "midnight"

_TITLE_LIMIT = 30
_SUMMARY_LIMIT = 56
_ERROR_LIMIT = 34
_DURATION_LIMIT = 18
_MAX_ACTION_BUTTONS = 2


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _escaped(text: str) -> str:
    return html.escape(text, quote=False)


class ToastWindow(QWidget):
    dismissed = Signal(object, str)
    acknowledged = Signal(str)
    snooze_requested = Signal(str, int)
    action_requested = Signal(object, object)
    center_requested = Signal()

    def __init__(
        self,
        notification: Notification,
        auto_close_seconds: int,
        logger: logging.Logger,
        templates: Mapping[str, str] | None = None,
        digest_titles: tuple[str, ...] | None = None,
        popup_mode: str | None = None,
        popup_skin: str | None = None,
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
        self._templates = templates
        self._digest_titles = digest_titles
        self._is_digest = digest_titles is not None
        self.popup_mode = _normalized_mode(popup_mode or notification.popup_mode)
        self.popup_skin = _normalized_skin(popup_skin or notification.popup_skin)
        self._card_width = {
            "corner": CARD_WIDTH,
            "center": CENTER_CARD_WIDTH,
            "overlay": OVERLAY_CARD_WIDTH,
        }[self.popup_mode]
        self._window_width = self._card_width + SHADOW_MARGIN * 2
        requested_seconds = (
            notification.auto_close_seconds
            if notification.auto_close_seconds is not None
            else auto_close_seconds
        )
        if notification.require_ack or self.popup_mode in _MODAL_MODES:
            requested_seconds = 0
        self._timeout_seconds = max(0, int(requested_seconds))
        self._remaining = float(self._timeout_seconds)
        self._last_tick = time.monotonic()
        self._paused = False
        self._closing = False
        self._reason = ""
        self._link = safe_http_url(notification.link)
        self._entry_animation: QParallelAnimationGroup | None = None
        self._move_animation: QPropertyAnimation | None = None
        self._fade_out_animation: QPropertyAnimation | None = None
        self._summary_label: QLabel | None = None
        self._error_label: QLabel | None = None
        self._title_label: QLabel | None = None
        self._meta_label: QLabel | None = None
        self._priority_badge: QLabel | None = None
        self._actions_row: QWidget | None = None
        self._progress_row: QWidget | None = None
        self._progress_label: QLabel | None = None
        self._progress_bar: QProgressBar | None = None
        self._action_buttons: list[QPushButton] = []
        self._snooze_button: QPushButton | None = None
        self._pulse_timer: QTimer | None = None
        self._overlay_backdrop: QWidget | None = None

        self.setObjectName("toastRoot")
        self.setWindowTitle("AgentBell 通知")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        mac_attribute = getattr(Qt.WidgetAttribute, "WA_MacAlwaysShowToolWindow", None)
        if mac_attribute is not None:
            self.setAttribute(mac_attribute, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self.popup_mode != "overlay":
            self.setFixedWidth(self._window_width)
        self.setAccessibleName("AgentBell 通知")
        self.setAccessibleDescription(notification.headline_text(templates))

        self._build_ui()
        self._apply_style()
        self._refresh_summary_height()

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(100)
        self._tick_timer.timeout.connect(self._on_tick)

        self.layout().activate()
        if self.popup_mode != "overlay":
            self.setFixedHeight(self.sizeHint().height())

    # ---------- construction ----------

    def _headline(self) -> str:
        if self._is_digest:
            count = len(self._digest_titles or ())
            return f"{count} 条通知待查看"
        return self.notification.headline_text(self._templates)

    def _summary(self) -> str:
        if self._is_digest:
            titles = self._digest_titles or ()
            joined = "、".join(_clip(title, 14) for title in titles[:5])
            if len(titles) > 5:
                joined += f" 等 {len(titles)} 条"
            return joined
        notification = self.notification
        summary_text = notification.summary
        if notification.status == "failed" and not summary_text:
            summary_text = (
                f"错误：{notification.error}"
                if notification.error
                else "执行失败，未提供更多信息"
            )
        return summary_text

    def _error_text(self) -> str:
        notification = self.notification
        if notification.status != "failed" or not notification.error:
            return ""
        if notification.summary:
            return f"错误：{_clip(notification.error, _ERROR_LIMIT)}"
        return ""

    def _meta_text(self) -> str:
        notification = self.notification
        if self._is_digest:
            return f"{notification.received_at.strftime('%H:%M')} 聚合提醒"
        parts = []
        if notification.duration:
            parts.append(f"耗时 {_clip(notification.duration, _DURATION_LIMIT)}")
        parts.append(notification.effective_updated_at.strftime("%H:%M"))
        if notification.occurrence_count > 1:
            parts.append(f"第 {notification.occurrence_count} 次更新")
        if notification.source:
            parts.append(_clip(notification.source, 16))
        return " · ".join(parts)

    def _build_ui(self) -> None:
        notification = self.notification
        accent = status_color(notification.status)

        outer = QVBoxLayout(self)
        outer.setSpacing(0)

        if self.popup_mode == "overlay":
            outer.setContentsMargins(0, 0, 0, 0)
            backdrop = QWidget(self)
            backdrop.setObjectName("overlayBackdrop")
            backdrop_layout = QVBoxLayout(backdrop)
            backdrop_layout.setContentsMargins(24, 24, 24, 24)
            backdrop_layout.setSpacing(0)
            backdrop_layout.addStretch(1)
            card_row = QHBoxLayout()
            card_row.setContentsMargins(0, 0, 0, 0)
            card_row.addStretch(1)
            self.card = QFrame(backdrop)
            self.card.setObjectName("card")
            self.card.setMaximumWidth(self._card_width)
            self.card.setMinimumWidth(self._card_width)
            card_row.addWidget(self.card)
            card_row.addStretch(1)
            backdrop_layout.addLayout(card_row)
            backdrop_layout.addStretch(1)
            outer.addWidget(backdrop)
            self._overlay_backdrop = backdrop
        else:
            outer.setContentsMargins(
                SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN, SHADOW_MARGIN
            )
            self.card = QFrame(self)
            self.card.setObjectName("card")
            outer.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(36 if self.popup_mode == "overlay" else 32)
        shadow.setOffset(0, 8)
        shadow.setColor(accent.darker(350))
        self.card.setGraphicsEffect(shadow)

        root = QVBoxLayout(self.card)
        root.setContentsMargins(18, 14, 18, 10)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        self._icon_label = QLabel(self.card)
        self._icon_label.setFixedSize(38, 38)
        self._icon_label.setPixmap(status_pixmap(notification.status, 38))
        self._icon_label.setAccessibleName(notification.status_label)
        header.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self._title_label = QLabel(self._headline(), self.card)
        self._title_label.setObjectName("title")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(True)
        self._title_label.setFixedHeight(40)
        self._title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._title_label.setToolTip(_escaped(self._headline()))
        header.addWidget(self._title_label, 1)

        if not self._is_digest and notification.priority in {"high", "critical"}:
            badge = QLabel(notification.priority_label, self.card)
            badge.setObjectName("priority")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.setFixedHeight(20)
            color = priority_color(notification.priority)
            badge.setStyleSheet(
                f"color: {color.name()};"
                f"background-color: rgba({color.red()}, {color.green()}, {color.blue()}, 0.16);"
                f"border: 1px solid {color.name()};"
                f"border-radius: 8px; padding: 0px 7px; font-size: 10px; font-weight: 600;"
            )
            header.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
            self._priority_badge = badge

        root.addLayout(header)
        root.addSpacing(8)

        summary_text = self._summary()
        self._summary_label = QLabel(self.card)
        self._summary_label.setObjectName("summary")
        self._summary_label.setTextFormat(Qt.TextFormat.PlainText)
        self._summary_label.setWordWrap(True)
        self._summary_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        self._update_summary_label(summary_text)
        root.addWidget(self._summary_label)

        self._error_label = QLabel(self.card)
        self._error_label.setObjectName("error")
        self._error_label.setTextFormat(Qt.TextFormat.PlainText)
        self._error_label.setFixedHeight(17)
        error_text = self._error_text()
        self._error_label.setText(error_text)
        self._error_label.setToolTip(
            _escaped(" ".join((notification.error or "").split()))
        )
        self._error_label.setVisible(bool(error_text))
        root.addWidget(self._error_label)

        self._actions_row = QWidget(self.card)
        actions_layout = QHBoxLayout(self._actions_row)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(6)
        for action in notification.actions[:_MAX_ACTION_BUTTONS]:
            button = QPushButton(action.label, self._actions_row)
            button.setObjectName("action")
            button.setFixedHeight(26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(
                lambda checked=False, item=action: self._on_action_clicked(item)
            )
            actions_layout.addWidget(button)
            self._action_buttons.append(button)
        actions_layout.addStretch(1)
        self._actions_row.setVisible(bool(self._action_buttons))
        root.addWidget(self._actions_row)

        self._progress_row = QWidget(self.card)
        progress_layout = QHBoxLayout(self._progress_row)
        progress_layout.setContentsMargins(0, 4, 0, 0)
        progress_layout.setSpacing(8)
        self._progress_label = QLabel(self._progress_row)
        self._progress_label.setObjectName("progressText")
        self._progress_label.setFixedWidth(58)
        progress_layout.addWidget(self._progress_label)
        self._progress_bar = QProgressBar(self._progress_row)
        self._progress_bar.setObjectName("taskProgress")
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(5)
        self._progress_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        progress_layout.addWidget(self._progress_bar, 1)
        self._progress_row.setVisible(False)
        root.addWidget(self._progress_row)
        self._apply_progress()

        root.addSpacing(8)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(8)

        self._meta_label = QLabel(self._meta_text(), self.card)
        self._meta_label.setObjectName("meta")
        self._meta_label.setTextFormat(Qt.TextFormat.PlainText)
        bottom.addWidget(self._meta_label, 1)

        self.view_button = QPushButton(
            "打开通知中心" if self._is_digest else "查看", self.card
        )
        self.view_button.setObjectName("view")
        self.view_button.setFixedHeight(28)
        self.view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if self._is_digest:
            self.view_button.setToolTip("打开 AgentBell 通知中心")
            self.view_button.clicked.connect(self._on_center_clicked)
        elif self._link:
            self.view_button.setToolTip(_escaped(self._link))
            self.view_button.clicked.connect(self._on_view_clicked)
        else:
            self.view_button.setEnabled(False)
            self.view_button.setToolTip("此通知未提供可打开的链接")
        bottom.addWidget(self.view_button)

        if notification.require_ack and not self._is_digest:
            self._snooze_button = QPushButton("稍后", self.card)
            self._snooze_button.setObjectName("snooze")
            self._snooze_button.setFixedHeight(28)
            self._snooze_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._snooze_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            menu = QMenu(self._snooze_button)
            menu.setToolTipsVisible(True)
            for minutes in (5, 15, 30):
                action = menu.addAction(f"{minutes} 分钟后提醒")
                action.triggered.connect(
                    lambda checked=False, value=minutes: self._on_snooze(value)
                )
            self._snooze_button.setMenu(menu)
            bottom.addWidget(self._snooze_button)

        self.ack_button = QPushButton("知道了", self.card)
        self.ack_button.setObjectName("ack")
        self.ack_button.setFixedHeight(28)
        self.ack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ack_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ack_button.clicked.connect(self._on_ack_clicked)
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
        palette = _SKIN_PALETTES[self.popup_skin]
        accent = status_color(self.notification.status).name()
        error_color = palette["error"] or accent
        self.setStyleSheet(
            f"""
            QWidget#toastRoot {{
                background: transparent;
            }}
            QWidget#overlayBackdrop {{
                background-color: {palette['backdrop']};
            }}
            QFrame#card {{
                background-color: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 16px;
            }}
            QFrame#card[alert="true"] {{
                border: 1px solid #FF6B6B;
            }}
            QLabel {{
                background: transparent;
                color: {palette['text']};
            }}
            QLabel#title {{
                color: {palette['title']};
                font-size: 14px;
                font-weight: 600;
            }}
            QLabel#summary {{
                color: {palette['text']};
                font-size: 12px;
            }}
            QLabel#error {{
                color: {error_color};
                font-size: 11px;
            }}
            QLabel#meta {{
                color: {palette['muted']};
                font-size: 11px;
            }}
            QLabel#progressText {{
                color: {palette['muted']};
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
                background-color: {palette['bar']};
                color: {palette['muted']};
            }}
            QPushButton#ack {{
                background-color: transparent;
                color: {palette['title']};
                border: 1px solid {palette['button_border']};
            }}
            QPushButton#ack:hover {{
                background-color: {palette['button_hover']};
                border-color: {palette['button_hover_border']};
            }}
            QPushButton#ack:pressed {{
                background-color: {palette['button_bg']};
            }}
            QPushButton#snooze {{
                background-color: transparent;
                color: {palette['text']};
                border: 1px solid {palette['button_border']};
            }}
            QPushButton#snooze:hover {{
                background-color: {palette['button_hover']};
                border-color: {palette['button_hover_border']};
            }}
            QPushButton#action {{
                background-color: {palette['button_bg']};
                color: {palette['title']};
                border: 1px solid {palette['button_border']};
            }}
            QPushButton#action:hover {{
                background-color: {palette['button_hover']};
                border-color: {palette['button_hover_border']};
            }}
            QProgressBar#countdown {{
                background-color: {palette['bar']};
                border: none;
                border-radius: 1px;
            }}
            QProgressBar#countdown::chunk {{
                background-color: {accent};
                border-radius: 1px;
            }}
            QProgressBar#taskProgress {{
                background-color: {palette['bar']};
                border: none;
                border-radius: 2px;
            }}
            QProgressBar#taskProgress::chunk {{
                background-color: #4F8CFF;
                border-radius: 2px;
            }}
            """
        )

    # ---------- content updates ----------

    def _update_summary_label(self, text: str) -> None:
        if self._summary_label is None:
            return
        self._summary_label.setText(_clip(text, _SUMMARY_LIMIT))
        self._summary_label.setToolTip(_escaped(" ".join(text.split())))
        self._summary_label.setVisible(bool(text))
        self._refresh_summary_height()

    def _refresh_summary_height(self) -> None:
        if self._summary_label is None or not self._summary_label.text():
            return
        metrics = self._summary_label.fontMetrics()
        bounds = metrics.boundingRect(
            QRect(0, 0, self._card_width - 38, 1000),
            Qt.TextFlag.TextWordWrap,
            self._summary_label.text(),
        )
        one_line = bounds.height() <= metrics.lineSpacing() + 2
        self._summary_label.setFixedHeight(18 if one_line else 34)

    def _apply_progress(self) -> None:
        if (
            self._progress_row is None
            or self._progress_bar is None
            or self._progress_label is None
        ):
            return
        progress = self.notification.progress
        visible = progress is not None and not self._is_digest
        self._progress_row.setVisible(visible)
        if visible and progress is not None:
            self._progress_bar.setValue(max(0, min(100, int(progress))))
            self._progress_label.setText(f"进度 {int(progress)}%")

    def update_notification(self, notification: Notification) -> None:
        if self._closing:
            return
        self.notification = notification
        self.popup_skin = _normalized_skin(
            notification.popup_skin or self.popup_skin
        )
        if not self._is_digest:
            self._link = safe_http_url(notification.link)
            self._icon_label.setPixmap(status_pixmap(notification.status, 38))
            self._icon_label.setAccessibleName(notification.status_label)
            self._title_label.setText(self._headline())
            self._title_label.setToolTip(_escaped(self._headline()))
            self._update_summary_label(self._summary())
            error_text = self._error_text()
            self._error_label.setText(error_text)
            self._error_label.setVisible(bool(error_text))
            if self._priority_badge is not None:
                self._priority_badge.setText(notification.priority_label)
            if self._meta_label is not None:
                self._meta_label.setText(self._meta_text())
            if self._link:
                self.view_button.setEnabled(True)
                self.view_button.setToolTip(_escaped(self._link))
                try:
                    self.view_button.clicked.disconnect()
                except RuntimeError:
                    pass
                self.view_button.clicked.connect(self._on_view_clicked)
            else:
                self.view_button.setEnabled(False)
                self.view_button.setToolTip("此通知未提供可打开的链接")
            self._apply_progress()
        self._apply_style()
        self.layout().activate()
        if self.popup_mode != "overlay":
            self.setFixedHeight(self.sizeHint().height())
        self._logger.info(
            "弹窗原地更新 id=%s 次数=%d 进度=%s",
            notification.id,
            notification.occurrence_count,
            notification.progress,
        )

    def pulse(self) -> None:
        if self._closing:
            return
        self.card.setProperty("alert", True)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)
        if self._pulse_timer is not None:
            self._pulse_timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(self._clear_pulse)
        timer.start(1200)
        self._pulse_timer = timer
        self.raise_()

    def _clear_pulse(self) -> None:
        self.card.setProperty("alert", False)
        self.card.style().unpolish(self.card)
        self.card.style().polish(self.card)

    # ---------- display / animation ----------

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if self._closing:
            return
        if paused:
            self._tick_timer.stop()
        elif self._timeout_seconds > 0:
            self._last_tick = time.monotonic()
            self._tick_timer.start()

    def show_at(self, target: QPoint) -> None:
        if self.popup_mode == "overlay":
            self.show_overlay()
            return
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
        if self._timeout_seconds > 0 and not self._paused:
            self._tick_timer.start()

    def show_overlay(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(190)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        self._entry_animation = group
        group.start()

    def mousePressEvent(self, event) -> None:
        if (
            self.popup_mode == "overlay"
            and event.button() == Qt.MouseButton.LeftButton
            and not self.card.rect().contains(
                self.card.mapFromGlobal(event.globalPosition().toPoint())
            )
        ):
            if self.notification.require_ack:
                self.pulse()
            else:
                self.dismiss("backdrop")
            event.accept()
            return
        super().mousePressEvent(event)

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
        if self._closing or self._paused or self._timeout_seconds <= 0:
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
            self._logger.warning(
                "打开链接失败 id=%s url=%s", self.notification.id, self._link
            )
            return
        self.dismiss("view")

    def _on_center_clicked(self) -> None:
        self.center_requested.emit()
        self.dismiss("center")

    def _on_ack_clicked(self) -> None:
        self.acknowledged.emit(self.notification.id)
        self.dismiss("ack")

    def _on_snooze(self, minutes: int) -> None:
        self.snooze_requested.emit(self.notification.id, int(minutes))
        self.dismiss("snooze")

    def _on_action_clicked(self, action: NotificationAction) -> None:
        self.action_requested.emit(self.notification, action)
        self.dismiss("action")

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
    acknowledged = Signal(str)
    snooze_requested = Signal(str, int)
    action_requested = Signal(object, object)
    center_requested = Signal()

    def __init__(
        self,
        auto_close_seconds: int,
        logger: logging.Logger,
        visible_limit: int = MAX_VISIBLE,
        templates: Mapping[str, str] | None = None,
        popup_mode: str = "corner",
        popup_skin: str = "midnight",
    ) -> None:
        super().__init__()
        self._auto_close_seconds = auto_close_seconds
        self._logger = logger
        self._visible_limit = visible_limit
        self._templates = templates
        self._popup_mode = _normalized_mode(popup_mode)
        self._popup_skin = _normalized_skin(popup_skin)
        self._paused = False
        self._active: list[ToastWindow] = []
        self._pending: deque[tuple[Notification, tuple[str, ...] | None]] = deque()
        self._shutting_down = False

    def set_auto_close(self, seconds: int) -> None:
        self._auto_close_seconds = max(0, int(seconds))

    def set_templates(self, templates: Mapping[str, str]) -> None:
        self._templates = dict(templates)

    def set_appearance(self, popup_mode: str, popup_skin: str) -> None:
        self._popup_mode = _normalized_mode(popup_mode)
        self._popup_skin = _normalized_skin(popup_skin)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        for toast in self._active:
            toast.set_paused(self._paused)

    def _has_modal(self) -> bool:
        return any(toast.popup_mode in _MODAL_MODES for toast in self._active)

    def _modal_conflict(self, mode: str) -> bool:
        if mode in _MODAL_MODES:
            return bool(self._active)
        return self._has_modal()

    def has_visible(self, notification_id: str) -> bool:
        return any(
            toast.notification.id == notification_id for toast in self._active
        )

    def enqueue(self, notification: Notification) -> bool:
        if self._shutting_down:
            return False
        existing = self._find_active(notification.id)
        if existing is not None:
            existing.update_notification(notification)
            self._reposition()
            return True
        for index, (item, digest_titles) in enumerate(self._pending):
            if item.id == notification.id:
                self._pending[index] = (notification, digest_titles)
                self._logger.info("更新排队中的弹窗 id=%s", notification.id)
                return True

        mode = _normalized_mode(notification.popup_mode or self._popup_mode)
        if (
            len(self._active) >= self._visible_limit
            or self._pending
            or self._modal_conflict(mode)
        ):
            self._pending.append((notification, None))
            self._logger.info(
                "弹窗排队 id=%s 模式=%s 可见=%d 排队=%d",
                notification.id,
                mode,
                len(self._active),
                len(self._pending),
            )
            return True

        self._present(notification, None)
        return True

    def show_digest(self, notifications: list[Notification]) -> bool:
        if self._shutting_down or not notifications:
            return False
        titles = tuple(item.title for item in notifications)
        summary = "、".join(_clip(title, 14) for title in titles[:5])
        if len(titles) > 5:
            summary += f" 等 {len(titles)} 条"
        digest = Notification(
            id=f"digest-{uuid.uuid4().hex[:8]}",
            title=f"{len(notifications)} 条通知",
            status="running",
            summary=summary,
            priority="normal",
        )
        digest_titles = titles
        if (
            len(self._active) >= self._visible_limit
            or self._pending
            or self._has_modal()
        ):
            self._pending.append((digest, digest_titles))
            return True
        self._present(digest, digest_titles)
        return True

    def pulse(self, notification_id: str) -> bool:
        toast = self._find_active(notification_id)
        if toast is None:
            return False
        toast.pulse()
        return True

    def dismiss_toast(self, notification_id: str, reason: str = "ack") -> None:
        toast = self._find_active(notification_id)
        if toast is not None:
            toast.dismiss(reason)
        self._pending = deque(
            item for item in self._pending if item[0].id != notification_id
        )

    def _find_active(self, notification_id: str) -> ToastWindow | None:
        return next(
            (
                toast
                for toast in self._active
                if toast.notification.id == notification_id
            ),
            None,
        )

    def _present(
        self, notification: Notification, digest_titles: tuple[str, ...] | None
    ) -> None:
        is_digest = digest_titles is not None
        mode = (
            "corner"
            if is_digest
            else _normalized_mode(notification.popup_mode or self._popup_mode)
        )
        skin = _normalized_skin(
            self._popup_skin
            if is_digest
            else (notification.popup_skin or self._popup_skin)
        )
        toast = ToastWindow(
            notification,
            self._auto_close_seconds,
            self._logger,
            templates=self._templates,
            digest_titles=digest_titles,
            popup_mode=mode,
            popup_skin=skin,
        )
        toast.dismissed.connect(self._on_dismissed)
        toast.acknowledged.connect(self.acknowledged)
        toast.snooze_requested.connect(self.snooze_requested)
        toast.action_requested.connect(self.action_requested)
        toast.center_requested.connect(self.center_requested)
        self._active.append(toast)

        if mode == "center":
            target = self._center_position(toast)
        elif mode == "overlay":
            target = QPoint(0, 0)
        else:
            target = QPoint(*self._next_position())
        if self._paused:
            toast.set_paused(True)
        toast.show_at(target)
        self._logger.info(
            "弹窗显示 id=%s status=%s 模式=%s 皮肤=%s 可见=%d 排队=%d",
            notification.id,
            notification.status,
            mode,
            skin,
            len(self._active),
            len(self._pending),
        )

    def _center_position(self, toast: ToastWindow) -> QPoint:
        geometry = self._screen_geometry()
        if geometry is None:
            return QPoint(120, 120)
        return QPoint(
            geometry.x() + max(0, (geometry.width() - toast.width()) // 2),
            geometry.y() + max(0, (geometry.height() - toast.height()) // 2),
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
            if toast.popup_mode != "corner":
                continue
            toast.move_to(QPoint(x, y))
            y += toast.height() + TOAST_GAP

    def _on_dismissed(self, notification: Notification, reason: str) -> None:
        toast = self._find_active(notification.id)
        if toast is None:
            return
        self._active.remove(toast)
        toast.deleteLater()

        reason_text = {
            "ack": "用户点击知道了",
            "view": "用户点击查看",
            "snooze": "用户选择稍后提醒",
            "action": "用户点击卡片操作",
            "center": "用户打开通知中心",
            "timeout": (
                f"{notification.auto_close_seconds} 秒自动关闭"
                if notification.auto_close_seconds is not None
                else f"{self._auto_close_seconds} 秒自动关闭"
            ),
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
            notification, digest_titles = self._pending[0]
            mode = (
                "corner"
                if digest_titles is not None
                else _normalized_mode(
                    notification.popup_mode or self._popup_mode
                )
            )
            if mode in _MODAL_MODES and self._active:
                break
            if mode == "corner" and self._has_modal():
                break
            self._pending.popleft()
            self._present(notification, digest_titles)

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
