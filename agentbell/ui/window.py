from __future__ import annotations

import logging
import re
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..agent_launch import (
    AgentAvailability,
    LaunchResult,
    discover_agents,
    launch_agent,
)
from ..agent_sessions import (
    AgentSession,
    SessionItem,
    SessionTranscript,
    SessionTurn,
    parse_session_transcript,
    transcript_to_markdown,
)
from ..config import (
    AgentLauncherConfig,
    AppConfig,
    ConfigError,
    save_config,
)
from ..integration import build_agent_instructions
from ..models import STATUS_LABELS, Notification, safe_http_url
from ..paths import default_project_dir, runtime_dir
from ..store import NotificationStore
from ..window_focus import FocusRequest
from .icons import make_app_icon
from .motion import motion_enabled
from .onboarding import OnboardingOverlay
from .toolchain_page import ToolchainPage

SIDEBAR_WIDTH = 232
DEFAULT_SIZE = QSize(1120, 760)
MINIMUM_SIZE = QSize(900, 580)
MAX_VISIBLE_CARDS = 100
MAX_SEARCH_RESULTS = 500
SEARCH_DEBOUNCE_MS = 260

FILTERS: tuple[tuple[str, str, str], ...] = (
    ("all", "全部", "全部通知"),
    ("succeeded", "成功", "已完成"),
    ("failed", "失败", "失败"),
    ("canceled", "已取消", "已取消"),
    ("running", "进行中", "进行中"),
)
FILTERS_LABELS = {key: sidebar for key, _, sidebar in FILTERS}

_STATUS_TILE_COLORS = {
    "succeeded": ("#E8F8F0", "#C9EEDC", "#15885C"),
    "failed": ("#FDECEC", "#F6D3D3", "#D04646"),
    "canceled": ("#FDF4E5", "#F5E2BF", "#B7791F"),
    "running": ("#EDF4FF", "#CFE0FB", "#2F6FF0"),
}

_PRIORITY_CHIP_LABELS = {"high": "高优先级", "critical": "紧急"}


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def format_received_at(when: datetime, now: datetime | None = None) -> str:
    current = (now or datetime.now().astimezone()).astimezone()
    local = when.astimezone()
    if local.date() == current.date():
        return f"今天 {local:%H:%M}"
    if local.date() == current.date() - timedelta(days=1):
        return f"昨天 {local:%H:%M}"
    if local.year == current.year:
        return f"{local:%m-%d %H:%M}"
    return f"{local:%Y-%m-%d %H:%M}"


def format_seconds(value: float | None) -> str:
    if value is None:
        return "—"
    seconds = float(value)
    if seconds < 1:
        return "<1 秒"
    if seconds < 60:
        return f"{seconds:.0f} 秒"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f} 分钟"
    return f"{minutes / 60:.1f} 小时"


def format_bytes(value: int) -> str:
    size = max(0, int(value))
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


class ElidedLabel(QLabel):
    """Single-line label that ellipsizes its text to the available width."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._apply_elision()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_elision()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (
            QEvent.Type.FontChange,
            QEvent.Type.StyleChange,
        ):
            self._apply_elision()

    def _apply_elision(self) -> None:
        width = max(0, self.contentsRect().width())
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, width
        )
        if self.text() != elided:
            super().setText(elided)


def _paint_icon(kind: str, color: QColor, size: int) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(color, 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    scale = size / 18.0
    painter.scale(scale, scale)

    if kind == "copy":
        painter.drawRoundedRect(QRectF(6.3, 6.3, 8.2, 8.7), 1.8, 1.8)
        painter.drawRoundedRect(QRectF(3.5, 3.0, 8.2, 8.7), 1.8, 1.8)
    elif kind == "check":
        path = QPainterPath()
        path.moveTo(4.0, 9.4)
        path.lineTo(7.6, 12.9)
        path.lineTo(14.2, 5.3)
        painter.drawPath(path)
    elif kind == "bell":
        path = QPainterPath()
        path.moveTo(9.0, 2.9)
        path.cubicTo(6.3, 2.9, 5.0, 5.2, 5.0, 8.0)
        path.cubicTo(5.0, 11.8, 3.8, 13.4, 3.8, 13.4)
        path.lineTo(14.2, 13.4)
        path.cubicTo(14.2, 13.4, 13.0, 11.8, 13.0, 8.0)
        path.cubicTo(13.0, 5.2, 11.7, 2.9, 9.0, 2.9)
        path.closeSubpath()
        painter.drawPath(path)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(8.0, 14.3, 2.0, 2.0))
    elif kind == "external":
        painter.drawRoundedRect(QRectF(3.4, 6.4, 8.2, 8.2), 1.7, 1.7)
        painter.drawLine(QPointF(9.1, 8.9), QPointF(14.6, 3.4))
        path = QPainterPath()
        path.moveTo(10.4, 3.4)
        path.lineTo(14.6, 3.4)
        path.lineTo(14.6, 7.6)
        painter.drawPath(path)
    elif kind == "search":
        painter.drawEllipse(QRectF(3.4, 3.4, 8.4, 8.4))
        painter.drawLine(QPointF(12.6, 12.6), QPointF(15.4, 15.4))
    elif kind == "stats":
        painter.drawLine(QPointF(4.2, 14.4), QPointF(4.2, 9.4))
        painter.drawLine(QPointF(9.0, 14.4), QPointF(9.0, 4.2))
        painter.drawLine(QPointF(13.8, 14.4), QPointF(13.8, 7.0))
    elif kind == "agents":
        painter.drawRoundedRect(QRectF(2.8, 3.6, 9.6, 7.4), 2.2, 2.2)
        painter.drawLine(QPointF(5.2, 11.0), QPointF(4.4, 13.6))
        painter.drawLine(QPointF(4.4, 13.6), QPointF(7.0, 11.0))
        painter.drawRoundedRect(QRectF(8.8, 8.6, 6.4, 5.2), 1.8, 1.8)
        painter.drawLine(QPointF(11.2, 13.8), QPointF(11.2, 15.6))
    elif kind == "terminal":
        painter.drawRoundedRect(QRectF(2.4, 3.4, 13.2, 11.2), 2.0, 2.0)
        path = QPainterPath()
        path.moveTo(5.0, 6.8)
        path.lineTo(7.6, 9.0)
        path.lineTo(5.0, 11.2)
        painter.drawPath(path)
        painter.drawLine(QPointF(9.2, 11.2), QPointF(12.6, 11.2))
    elif kind == "settings":
        painter.drawEllipse(QRectF(3.7, 3.7, 10.6, 10.6))
        painter.setBrush(color)
        painter.drawEllipse(QRectF(7.9, 7.9, 2.2, 2.2))
    elif kind == "download":
        painter.drawLine(QPointF(9.0, 3.0), QPointF(9.0, 11.2))
        path = QPainterPath()
        path.moveTo(5.9, 8.3)
        path.lineTo(9.0, 11.4)
        path.lineTo(12.1, 8.3)
        painter.drawPath(path)
        painter.drawLine(QPointF(3.6, 14.2), QPointF(14.4, 14.2))
    elif kind == "folder":
        path = QPainterPath()
        path.moveTo(2.9, 5.0)
        path.lineTo(7.5, 5.0)
        path.lineTo(9.1, 6.7)
        path.lineTo(15.1, 6.7)
        path.lineTo(15.1, 14.3)
        path.lineTo(2.9, 14.3)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "back":
        path = QPainterPath()
        path.moveTo(11.2, 4.0)
        path.lineTo(5.6, 9.0)
        path.lineTo(11.2, 14.0)
        painter.drawPath(path)

    painter.end()
    return QIcon(pixmap)


def _dot_icon(color: str, size: int = 14) -> QIcon:
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(color))
    painter.drawEllipse(QRectF(3.2, 3.2, 7.6, 7.6))
    painter.end()
    return QIcon(pixmap)


def _status_tile(status: str, size: int = 44) -> QPixmap:
    fill, border, symbol = _STATUS_TILE_COLORS.get(
        status, _STATUS_TILE_COLORS["succeeded"]
    )
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    rect = QRectF(0.7, 0.7, size - 1.4, size - 1.4)
    painter.setPen(QPen(QColor(border), 1.2))
    painter.setBrush(QColor(fill))
    painter.drawRoundedRect(rect, size * 0.27, size * 0.27)

    scale = size / 44.0
    painter.scale(scale, scale)
    pen = QPen(QColor(symbol), 2.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if status == "failed":
        painter.drawLine(QPointF(15, 15), QPointF(29, 29))
        painter.drawLine(QPointF(29, 15), QPointF(15, 29))
    elif status == "canceled":
        painter.drawLine(QPointF(14.5, 22), QPointF(29.5, 22))
    elif status == "running":
        painter.drawEllipse(QRectF(13.2, 13.2, 17.6, 17.6))
        painter.drawLine(QPointF(22, 17.6), QPointF(22, 22))
        painter.drawLine(QPointF(22, 22), QPointF(26, 24.4))
    else:
        path = QPainterPath()
        path.moveTo(12.0, 22.6)
        path.lineTo(19.0, 29.4)
        path.lineTo(32.0, 14.8)
        painter.drawPath(path)

    painter.end()
    return pixmap


class TitleBar(QFrame):
    def __init__(self, owner: NotificationWindow) -> None:
        super().__init__(owner)
        self.setObjectName("topBar")
        self.setFixedHeight(64)
        self._owner = owner
        self._drag_offset: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self.window().windowHandle()
            if handle is not None and handle.startSystemMove():
                self._drag_offset = None
                event.accept()
                return
            self._drag_offset = (
                event.globalPosition().toPoint()
                - self.window().frameGeometry().topLeft()
            )
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
            and not self.window().isMaximized()
        ):
            self.window().move(
                event.globalPosition().toPoint() - self._drag_offset
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._owner.toggle_maximize()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class EmptyState(QWidget):
    copy_requested = Signal()
    reset_filter_requested = Signal()

    def __init__(
        self,
        has_any_records: bool,
        parent: QWidget | None = None,
        query: str = "",
    ) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._has_query = bool(query)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 74, 24, 48)
        layout.setSpacing(0)
        layout.addStretch(1)

        icon = QLabel(self)
        icon.setPixmap(make_app_icon().pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(18)
        if self._has_query:
            title_text = "没有找到匹配的通知"
        elif has_any_records:
            title_text = "没有符合条件的通知"
        else:
            title_text = "还没有通知记录"
        title = QLabel(title_text, self)
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(8)
        if self._has_query:
            description = f"没有匹配「{_clip(query, 30)}」的记录，换个关键词试试。"
        elif has_any_records:
            description = "换一个筛选条件，或回到全部通知查看完整记录。"
        else:
            description = (
                "Agent 每完成一轮任务都会在这里留下记录。\n"
                "复制接入指令并粘贴给 Agent，即可开启每轮自动提醒。"
            )
        text = QLabel(description, self)
        text.setObjectName("emptyText")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)

        layout.addSpacing(22)
        if self._has_query:
            action_text = "清除搜索"
        elif has_any_records:
            action_text = "查看全部通知"
        else:
            action_text = "复制 Agent 接入指令"
        self.action = QPushButton(action_text, self)
        self.action.setObjectName("emptyAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.setFixedHeight(36)
        self.action.setMinimumWidth(170)
        if self._has_query or has_any_records:
            self.action.clicked.connect(self.reset_filter_requested.emit)
        else:
            self.action.clicked.connect(self.copy_requested.emit)
            self.action.setIcon(_paint_icon("copy", QColor("#FFFFFF"), 16))
            self.action.setIconSize(QSize(16, 16))
        layout.addWidget(self.action, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(16)
        hint = QLabel("也可以从托盘菜单重新打开此窗口", self)
        hint.setObjectName("emptyHint")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(2)


class NotificationCard(QFrame):
    replay_requested = Signal(object)
    ack_requested = Signal(str)
    snooze_requested = Signal(str, int)
    action_requested = Signal(object, object)

    def __init__(
        self,
        notification: Notification,
        logger: logging.Logger,
        latest: bool = False,
        allow_local_paths: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.notification = notification
        self._logger = logger
        self._link = safe_http_url(notification.link)
        self.setObjectName("notificationCard")
        self.setProperty("latest", latest)
        self.setProperty("priority", notification.priority)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAccessibleName(notification.headline)

        root = QHBoxLayout(self)
        root.setContentsMargins(18, 15, 14, 15)
        root.setSpacing(14)

        tile = QLabel(self)
        tile.setPixmap(_status_tile(notification.status, 44))
        tile.setFixedSize(44, 44)
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(5)
        root.addLayout(body, 1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)

        title = ElidedLabel(notification.title, self)
        title.setObjectName("cardTitle")
        title_row.addWidget(title, 1)

        priority_label = _PRIORITY_CHIP_LABELS.get(notification.priority)
        if priority_label:
            priority = QLabel(priority_label, self)
            priority.setObjectName("priorityChip")
            priority.setProperty("priority", notification.priority)
            priority.setAlignment(Qt.AlignmentFlag.AlignCenter)
            priority.setFixedHeight(20)
            title_row.addWidget(priority, 0, Qt.AlignmentFlag.AlignVCenter)

        chip = QLabel(notification.status_label, self)
        chip.setObjectName("statusChip")
        chip.setProperty("status", notification.status)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setFixedHeight(20)
        title_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

        time_label = QLabel(format_received_at(notification.effective_updated_at), self)
        time_label.setObjectName("cardTime")
        title_row.addWidget(time_label, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(title_row)

        summary_text = notification.summary
        if not summary_text:
            if notification.status == "failed":
                summary_text = notification.error or "执行失败，未提供更多信息。"
            elif notification.status == "canceled":
                summary_text = "本轮任务已取消。"
            elif notification.status == "running":
                summary_text = "本轮任务正在进行中。"
            else:
                summary_text = "本轮任务已完成。"
        summary = ElidedLabel(summary_text, self)
        summary.setObjectName("cardSummary")
        body.addWidget(summary)

        self.progress_bar: QProgressBar | None = None
        if notification.progress is not None or notification.status == "running":
            progress_row = QWidget(self)
            progress_row.setObjectName("cardProgress")
            progress_layout = QHBoxLayout(progress_row)
            progress_layout.setContentsMargins(0, 2, 0, 0)
            progress_layout.setSpacing(8)

            if notification.progress is None:
                progress_text = "进行中"
            else:
                progress_text = f"进度 {max(0, min(100, int(notification.progress)))}%"
            progress_label = QLabel(progress_text, progress_row)
            progress_label.setObjectName("cardProgressLabel")
            progress_layout.addWidget(progress_label)

            self.progress_bar = QProgressBar(progress_row)
            self.progress_bar.setObjectName("cardProgressBar")
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setFixedHeight(6)
            if notification.progress is None:
                self.progress_bar.setRange(0, 0)
            else:
                self.progress_bar.setRange(0, 100)
                self.progress_bar.setValue(
                    max(0, min(100, int(notification.progress)))
                )
            progress_layout.addWidget(self.progress_bar, 1)
            body.addWidget(progress_row)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)

        if notification.duration:
            duration = QLabel(f"耗时 {_clip(notification.duration, 24)}", self)
            duration.setObjectName("durationChip")
            duration.setAlignment(Qt.AlignmentFlag.AlignCenter)
            duration.setFixedHeight(20)
            meta_row.addWidget(duration, 0, Qt.AlignmentFlag.AlignVCenter)

        if notification.source:
            source = QLabel(f"来源 {_clip(notification.source, 18)}", self)
            source.setObjectName("sourceChip")
            source.setToolTip(notification.source)
            source.setAlignment(Qt.AlignmentFlag.AlignCenter)
            source.setFixedHeight(20)
            meta_row.addWidget(source, 0, Qt.AlignmentFlag.AlignVCenter)

        if notification.occurrence_count > 1:
            repeats = QLabel(f"更新 ×{notification.occurrence_count}", self)
            repeats.setObjectName("repeatChip")
            repeats.setAlignment(Qt.AlignmentFlag.AlignCenter)
            repeats.setFixedHeight(20)
            meta_row.addWidget(repeats, 0, Qt.AlignmentFlag.AlignVCenter)

        if notification.require_ack:
            ack_chip = QLabel(
                "已确认" if notification.acknowledged else "待确认", self
            )
            ack_chip.setObjectName("ackChip")
            ack_chip.setProperty(
                "state", "done" if notification.acknowledged else "pending"
            )
            ack_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ack_chip.setFixedHeight(20)
            meta_row.addWidget(ack_chip, 0, Qt.AlignmentFlag.AlignVCenter)

        if (
            notification.status == "failed"
            and notification.error
            and notification.summary
        ):
            error = ElidedLabel(f"错误：{notification.error}", self)
            error.setObjectName("cardError")
            meta_row.addWidget(error, 1)
        else:
            meta_row.addStretch(1)
        body.addLayout(meta_row)

        self.action_buttons: list[QPushButton] = []
        commands_row = QHBoxLayout()
        commands_row.setContentsMargins(0, 2, 0, 0)
        commands_row.setSpacing(6)
        commands_row.addStretch(1)
        for action in notification.actions[:3]:
            if action.kind == "path" and not allow_local_paths:
                continue
            label = action.label or _default_action_label(action.kind)
            button = QPushButton(label, self)
            button.setObjectName("cardActionText")
            button.setFixedHeight(26)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, act=action: self.action_requested.emit(
                    self.notification, act
                )
            )
            commands_row.addWidget(button)
            self.action_buttons.append(button)

        self.snooze_button: QToolButton | None = None
        self.ack_button: QPushButton | None = None
        if notification.needs_ack:
            self.snooze_button = QToolButton(self)
            self.snooze_button.setObjectName("cardSnooze")
            self.snooze_button.setText("稍后提醒")
            self.snooze_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.snooze_button.setFixedHeight(26)
            self.snooze_button.setPopupMode(
                QToolButton.ToolButtonPopupMode.InstantPopup
            )
            menu = QMenu(self.snooze_button)
            for minutes, label in ((5, "5 分钟后"), (15, "15 分钟后"), (30, "30 分钟后")):
                entry = menu.addAction(label)
                entry.triggered.connect(
                    lambda checked=False, value=minutes: self.snooze_requested.emit(
                        self.notification.id, value
                    )
                )
            self.snooze_button.setMenu(menu)
            commands_row.addWidget(self.snooze_button)

            self.ack_button = QPushButton("知道了", self)
            self.ack_button.setObjectName("cardAck")
            self.ack_button.setFixedHeight(26)
            self.ack_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.ack_button.clicked.connect(
                lambda: self.ack_requested.emit(self.notification.id)
            )
            commands_row.addWidget(self.ack_button)

        if self.action_buttons or self.ack_button is not None:
            body.addLayout(commands_row)

        side = QVBoxLayout()
        side.setContentsMargins(0, 0, 0, 0)
        side.setSpacing(6)
        side.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.view_button: QToolButton | None = None
        if self._link:
            self.view_button = self._make_action(
                "external", "#4F647F", "打开通知中的链接"
            )
            self.view_button.setAccessibleName("打开链接")
            self.view_button.clicked.connect(self._open_link)
            side.addWidget(self.view_button)

        self.replay_button = self._make_action(
            "bell", "#4F647F", "再次弹出这条提醒"
        )
        self.replay_button.setAccessibleName("再次提醒")
        self.replay_button.clicked.connect(
            lambda: self.replay_requested.emit(self.notification)
        )
        side.addWidget(self.replay_button)
        side.addStretch(1)
        root.addLayout(side)

    def _make_action(self, kind: str, color: str, tooltip: str) -> QToolButton:
        button = QToolButton(self)
        button.setObjectName("cardAction")
        button.setIcon(_paint_icon(kind, QColor(color), 17))
        button.setIconSize(QSize(17, 17))
        button.setToolTip(tooltip)
        button.setFixedSize(32, 32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def _open_link(self) -> None:
        if not self._link:
            return
        self._logger.info(
            "打开通知链接 id=%s url=%s", self.notification.id, _clip(self._link, 200)
        )
        if not QDesktopServices.openUrl(QUrl(self._link)):
            self._logger.warning(
                "打开链接失败 id=%s url=%s", self.notification.id, self._link
            )


class AgentSessionCard(QFrame):
    open_requested = Signal(object)
    copy_requested = Signal(object)
    view_requested = Signal(object)
    terminal_requested = Signal(object)

    def __init__(
        self, session: AgentSession, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.setObjectName("sessionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 11, 10, 11)
        root.setSpacing(12)

        badge = QLabel(session.agent_label, self)
        badge.setObjectName("sessionAgent")
        badge.setProperty("agent", session.agent)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(70, 22)
        root.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(4)
        root.addLayout(body, 1)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = ElidedLabel(session.display_title, self)
        title.setObjectName("sessionTitle")
        title_row.addWidget(title, 1)
        updated = QLabel(format_received_at(session.updated_at), self)
        updated.setObjectName("sessionTime")
        title_row.addWidget(updated)
        body.addLayout(title_row)

        path_text = session.project_path or session.folder
        path = ElidedLabel(path_text, self)
        path.setObjectName("sessionPath")
        body.addWidget(path)

        meta_parts = []
        if session.message_count > 0:
            meta_parts.append(f"{session.message_count} 条记录")
        meta_parts.append(format_bytes(session.size_bytes))
        if session.created_at is not None:
            meta_parts.append(
                f"创建于 {session.created_at.strftime('%m-%d %H:%M')}"
            )
        meta = ElidedLabel(" · ".join(meta_parts), self)
        meta.setObjectName("sessionMeta")
        body.addWidget(meta)

        self.view_button = QPushButton("查看记录", self)
        self.view_button.setObjectName("sessionView")
        self.view_button.setFixedSize(78, 28)
        self.view_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_button.clicked.connect(
            lambda: self.view_requested.emit(session)
        )
        root.addWidget(self.view_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.terminal_button = QToolButton(self)
        self.terminal_button.setObjectName("sessionIcon")
        self.terminal_button.setIcon(
            _paint_icon("terminal", QColor("#667085"), 16)
        )
        self.terminal_button.setIconSize(QSize(16, 16))
        self.terminal_button.setFixedSize(30, 30)
        self.terminal_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.terminal_button.setToolTip(
            "回到终端：按项目名匹配并切到对应的终端或编辑器窗口"
        )
        self.terminal_button.clicked.connect(
            lambda: self.terminal_requested.emit(session)
        )
        root.addWidget(self.terminal_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.open_button = QToolButton(self)
        self.open_button.setObjectName("sessionIcon")
        self.open_button.setIcon(_paint_icon("folder", QColor("#667085"), 16))
        self.open_button.setIconSize(QSize(16, 16))
        self.open_button.setFixedSize(30, 30)
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.setToolTip("打开会话目录")
        self.open_button.clicked.connect(
            lambda: self.open_requested.emit(session)
        )
        root.addWidget(self.open_button, 0, Qt.AlignmentFlag.AlignVCenter)

        self.copy_button = QToolButton(self)
        self.copy_button.setObjectName("sessionIcon")
        self.copy_button.setIcon(_paint_icon("copy", QColor("#667085"), 16))
        self.copy_button.setIconSize(QSize(16, 16))
        self.copy_button.setFixedSize(30, 30)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("复制项目路径")
        self.copy_button.clicked.connect(
            lambda: self.copy_requested.emit(session)
        )
        root.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)


class AgentPickCard(QFrame):
    picked = Signal(object)
    activated = Signal(object)

    def __init__(
        self, availability: AgentAvailability, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.availability = availability
        self._suppress_release = False
        self.setObjectName("agentPickCard")
        self.setProperty("selected", "false")
        self.setProperty("installed", "true" if availability.installed else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        tip = availability.target
        if availability.installed:
            tip = f"{tip}\n双击直接启动"
        self.setToolTip(tip)
        self.setAccessibleName(availability.spec.name)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 12, 14, 12)
        row.setSpacing(12)

        tile = QLabel(self)
        tile.setObjectName("agentPickIcon")
        icon_kind = (
            "agents" if availability.spec.kind == "desktop" else "terminal"
        )
        color = QColor("#2F6FF0" if availability.installed else "#98A0AC")
        tile.setPixmap(_paint_icon(icon_kind, color, 16).pixmap(16, 16))
        tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile.setFixedSize(32, 32)
        row.addWidget(tile, 0, Qt.AlignmentFlag.AlignVCenter)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        name = QLabel(availability.spec.name, self)
        name.setObjectName("agentPickName")
        title_row.addWidget(name)
        chip = QLabel("已安装" if availability.installed else "未安装", self)
        chip.setObjectName("agentPickStatus")
        chip.setProperty(
            "installed", "true" if availability.installed else "false"
        )
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setFixedHeight(18)
        title_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)
        title_row.addStretch(1)
        kind = QLabel(availability.kind_label, self)
        kind.setObjectName("agentPickKind")
        title_row.addWidget(kind)
        body.addLayout(title_row)

        summary = ElidedLabel(availability.spec.summary, self)
        summary.setObjectName("agentPickHint")
        body.addWidget(summary)
        row.addLayout(body, 1)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self._suppress_release = True
            self.activated.emit(self.availability)
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        suppress = self._suppress_release
        self._suppress_release = False
        if (
            not suppress
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.picked.emit(self.availability)
        super().mouseReleaseEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        _repolish(self)


class LaunchRecordCard(QFrame):
    focus_requested = Signal(object)

    def __init__(self, result: LaunchResult, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.result = result
        self.setObjectName("launchRecord")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 9, 10, 9)
        row.setSpacing(10)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title = QLabel(
            f"{result.agent_name} · {Path(result.working_dir).name}", self
        )
        title.setObjectName("launchRecordTitle")
        text.addWidget(title)
        meta = QLabel(result.message, self)
        meta.setObjectName("launchRecordMeta")
        text.addWidget(meta)
        row.addLayout(text, 1)

        focus = result.focus_request()
        self.focus_button = QPushButton(
            "回到窗口" if result.agent_kind == "desktop" else "回到终端",
            self,
        )
        self.focus_button.setObjectName("launchFocus")
        self.focus_button.setFixedHeight(26)
        self.focus_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.focus_button.setEnabled(focus is not None)
        if focus is not None:
            self.focus_button.clicked.connect(
                lambda: self.focus_requested.emit(focus)
            )
        row.addWidget(self.focus_button, 0, Qt.AlignmentFlag.AlignVCenter)





_TURN_RENDER_LIMIT = 220
_ACTIVITY_RENDER_LIMIT = 160


class _TurnHeader(QFrame):
    clicked = Signal()

    def __init__(self, turn: SessionTurn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("turnHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 10, 8)
        row.setSpacing(10)

        index = QLabel(f"#{turn.index}", self)
        index.setObjectName("turnIndex")
        index.setAlignment(Qt.AlignmentFlag.AlignCenter)
        index.setFixedSize(36, 20)
        index.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(index, 0, Qt.AlignmentFlag.AlignVCenter)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        prompt = ElidedLabel(turn.preview, self)
        prompt.setObjectName("turnPrompt")
        prompt.setCursor(Qt.CursorShape.PointingHandCursor)
        text.addWidget(prompt)

        parts: list[str] = []
        if turn.tool_calls:
            parts.append(f"{turn.tool_calls} 次工具调用")
        if turn.tool_failures:
            parts.append(f"{turn.tool_failures} 次失败")
        if turn.files:
            parts.append(f"{turn.files} 个文件")
        if turn.timestamp is not None:
            parts.append(turn.timestamp.astimezone().strftime("%m-%d %H:%M"))
        if not parts:
            parts.append("无工具调用")
        meta = QLabel(" · ".join(parts), self)
        meta.setObjectName("turnMeta")
        meta.setCursor(Qt.CursorShape.PointingHandCursor)
        text.addWidget(meta)
        row.addLayout(text, 1)

        self.arrow = QLabel("▸", self)
        self.arrow.setObjectName("turnArrow")
        self.arrow.setFixedWidth(16)
        self.arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arrow.setCursor(Qt.CursorShape.PointingHandCursor)
        row.addWidget(self.arrow, 0, Qt.AlignmentFlag.AlignVCenter)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class SessionTurnView(QFrame):
    def __init__(
        self,
        turn: SessionTurn,
        default_expanded: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.turn = turn
        self.default_expanded = default_expanded
        self._expanded = False
        self._activity_items: list[SessionItem] = []
        self._activity_built = False
        self._body: QWidget | None = None
        self._activity_host: QWidget | None = None
        self._activity_layout: QVBoxLayout | None = None
        self._activity_toggle: QToolButton | None = None

        self.setObjectName("turnCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self.header = _TurnHeader(turn, self)
        self.header.clicked.connect(self._toggle)
        self._layout.addWidget(self.header)
        self.set_expanded(default_expanded)

    def _toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        if expanded and self._body is None:
            self._build_body()
        self._expanded = expanded
        self.header.arrow.setText("▾" if expanded else "▸")
        if self._body is not None:
            self._body.setVisible(expanded)

    def _build_body(self) -> None:
        body = QWidget(self)
        body.setObjectName("turnBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 2, 16, 12)
        layout.setSpacing(8)

        prompt = QLabel(self.turn.prompt or "（会话开始）", body)
        prompt.setObjectName("turnPromptFull")
        prompt.setWordWrap(True)
        prompt.setTextFormat(Qt.TextFormat.PlainText)
        prompt.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(prompt)

        rendered = 0
        for item in self.turn.items:
            if rendered >= _TURN_RENDER_LIMIT:
                break
            if item.kind in {"text", "image"}:
                label = QLabel(item.text or "[图片]", body)
                label.setObjectName(
                    "turnText" if item.kind == "text" else "turnImage"
                )
                label.setWordWrap(True)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextSelectableByMouse
                )
                layout.addWidget(label)
                rendered += 1
                continue
            self._activity_items.append(item)
            if self._activity_toggle is None:
                self._build_activity_block(body, layout)
        dropped = len(self.turn.items) - rendered - len(self._activity_items)
        if dropped > 0:
            more = QLabel(f"另有 {dropped} 项内容未展示（超出单轮显示上限）。", body)
            more.setObjectName("turnMore")
            layout.addWidget(more)

        self._body = body
        self._layout.addWidget(body)

    def _build_activity_block(
        self, body: QWidget, layout: QVBoxLayout
    ) -> None:
        parts = [f"{len(self._activity_items)} 项过程"]
        if self.turn.tool_calls:
            parts.append(f"{self.turn.tool_calls} 次工具调用")
        if self.turn.tool_failures:
            parts.append(f"{self.turn.tool_failures} 次失败")
        if self.turn.files:
            parts.append(f"{self.turn.files} 个文件")
        toggle = QToolButton(body)
        toggle.setObjectName("activityToggle")
        toggle.setCheckable(True)
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        toggle.setText("▸ 过程 · " + " · ".join(parts))
        toggle.toggled.connect(self._on_activity_toggled)
        layout.addWidget(toggle)

        host = QWidget(body)
        host.setObjectName("activityHost")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 2)
        host_layout.setSpacing(6)
        host.setVisible(False)
        layout.addWidget(host)

        self._activity_toggle = toggle
        self._activity_host = host
        self._activity_layout = host_layout

    def _on_activity_toggled(self, checked: bool) -> None:
        if checked and not self._activity_built:
            self._build_activity_rows()
        if self._activity_host is not None:
            self._activity_host.setVisible(checked)
        if self._activity_toggle is not None:
            symbol = "▾" if checked else "▸"
            text = self._activity_toggle.text()
            self._activity_toggle.setText(symbol + text[1:])

    def _build_activity_rows(self) -> None:
        if self._activity_layout is None:
            return
        self._activity_built = True
        for item in self._activity_items[:_ACTIVITY_RENDER_LIMIT]:
            self._activity_layout.addWidget(self._make_activity_row(item))
        dropped = len(self._activity_items) - _ACTIVITY_RENDER_LIMIT
        if dropped > 0 and self._activity_host is not None:
            more = QLabel(
                f"另有 {dropped} 项过程未展示。", self._activity_host
            )
            more.setObjectName("turnMore")
            self._activity_layout.addWidget(more)

    def _make_activity_row(self, item: SessionItem) -> QFrame:
        host = self._activity_host or self
        row = QFrame(host)
        row.setObjectName("activityRow")
        row.setProperty("error", item.error)
        layout = QVBoxLayout(row)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(6)
        if item.kind == "tool":
            name = f"工具 · {item.name}"
        elif item.kind == "result":
            name = f"结果 · {item.name}" if item.name else "工具结果"
        else:
            name = "思考"
        label = QLabel(name, row)
        label.setObjectName("activityName")
        label.setProperty("kind", item.kind)
        head.addWidget(label)
        if item.error:
            error = QLabel("失败", row)
            error.setObjectName("activityError")
            head.addWidget(error)
        head.addStretch(1)
        if item.truncated:
            clipped = QLabel("已截断", row)
            clipped.setObjectName("activityClipped")
            head.addWidget(clipped)
        layout.addLayout(head)

        text = QLabel(item.text or "（无输出）", row)
        text.setObjectName(
            "activityThinking" if item.kind == "thinking" else "activityText"
        )
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(text)
        return row

    def matches(self, query: str) -> bool:
        lowered = query.lower()
        if lowered in self.turn.prompt.lower():
            return True
        return any(
            lowered in item.text.lower() or lowered in item.name.lower()
            for item in self.turn.items
        )

    def set_search(self, query: str) -> None:
        query = query.strip()
        if not query:
            self.setVisible(True)
            self.set_expanded(self.default_expanded)
            return
        matched = self.matches(query)
        self.setVisible(matched)
        if not matched:
            return
        self.set_expanded(True)
        if self._activity_toggle is not None and not self._activity_toggle.isChecked():
            self._activity_toggle.setChecked(True)

    def expand_activity(self) -> None:
        if self._activity_toggle is None:
            return
        if not self._activity_toggle.isChecked():
            self._activity_toggle.setChecked(True)


def _default_action_label(kind: str) -> str:
    return {
        "open": "打开链接",
        "copy": "复制",
        "retry": "重试",
        "path": "打开文件",
        "center": "查看详情",
        "focus": "回到终端",
    }.get(kind, "执行")


class DailyChart(QWidget):
    """Minimal custom-painted bar chart for the last seven days."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict] = []
        self._maximum = 1
        self.setMinimumHeight(172)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, rows: list[dict] | None) -> None:
        self._rows = list(rows or [])[-7:]
        values = [int(row.get("total") or 0) for row in self._rows]
        self._maximum = max(values + [1])
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(10, 10, -10, -8)

        if not self._rows:
            painter.setPen(QColor("#9AA1AC"))
            painter.drawText(
                rect, Qt.AlignmentFlag.AlignCenter, "暂无历史数据"
            )
            painter.end()
            return

        bottom_pad = 24
        top_pad = 18
        chart_height = max(1, rect.height() - bottom_pad - top_pad)
        slot = rect.width() / len(self._rows)
        bar_width = min(34.0, slot * 0.46)

        pen = QPen(QColor("#EFF1F5"), 1)
        painter.setPen(pen)
        for index in range(1, 4):
            y = rect.top() + top_pad + chart_height * index / 4
            painter.drawLine(
                QPointF(rect.left(), y), QPointF(rect.right(), y)
            )

        label_font = painter.font()
        label_font.setPointSizeF(8.0)

        for index, row in enumerate(self._rows):
            total = int(row.get("total") or 0)
            failed = int(row.get("failed") or 0)
            center_x = rect.left() + slot * (index + 0.5)
            height = chart_height * total / self._maximum
            if total:
                height = max(height, 3.0)
            x = center_x - bar_width / 2
            y = rect.top() + top_pad + chart_height - height

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#BFD4F7"))
            painter.drawRoundedRect(
                QRectF(x, y, bar_width, height), 4.0, 4.0
            )

            if failed:
                failed_height = chart_height * failed / self._maximum
                failed_height = max(failed_height, 3.0)
                painter.setBrush(QColor("#F08A8A"))
                painter.drawRoundedRect(
                    QRectF(
                        x,
                        rect.top() + top_pad + chart_height - failed_height,
                        bar_width,
                        failed_height,
                    ),
                    4.0,
                    4.0,
                )

            painter.setFont(label_font)
            if total:
                painter.setPen(QColor("#667085"))
                painter.drawText(
                    QRectF(center_x - slot / 2, y - 17, slot, 14),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    str(total),
                )

            day = str(row.get("day") or "")
            day_label = day[5:] if len(day) >= 10 else day
            painter.setPen(QColor("#9AA1AC"))
            painter.drawText(
                QRectF(
                    center_x - slot / 2,
                    rect.top() + top_pad + chart_height + 5,
                    slot,
                    16,
                ),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                day_label,
            )

        painter.end()


class NotificationWindow(QMainWindow):
    replay_requested = Signal(object)
    quit_requested = Signal()
    ack_requested = Signal(str)
    snooze_requested = Signal(str, int)
    action_requested = Signal(object, object)
    settings_saved = Signal(object)
    center_shown = Signal()
    onboarding_finished = Signal()
    session_refresh_requested = Signal()
    focus_requested = Signal(object)
    update_check_requested = Signal()

    def __init__(
        self,
        config: AppConfig,
        store: NotificationStore,
        logger: logging.Logger,
        config_path: Path | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self._store = store
        self.logger = logger
        self._config_path = Path(config_path) if config_path else None
        self._items: list[Notification] = []
        self._signature: tuple | None = None
        self._filter = "all"
        self._query = ""
        self._search_items: list[Notification] = []
        self._page = "list"
        self._stats: dict = {}
        self._sessions: list[AgentSession] = []
        self._session_scanned_at: datetime | None = None
        self._session_detail_session: AgentSession | None = None
        self._session_transcript: SessionTranscript | None = None
        self._session_transcript_cache: dict[str, SessionTranscript] = {}
        self._agent_availabilities: list[AgentAvailability] = []
        self._agent_cards: list[AgentPickCard] = []
        self._selected_agent_id = ""
        self._launch_records: list[LaunchResult] = []
        self._turn_views: list[SessionTurnView] = []
        self._transcript_base_hint = ""
        self._transcript_hint_timer = QTimer(self)
        self._transcript_hint_timer.setSingleShot(True)
        self._transcript_hint_timer.setInterval(2400)
        self._transcript_hint_timer.timeout.connect(
            self._restore_transcript_hint
        )
        self._shutting_down = False
        self._placed = False
        self._show_animation: QParallelAnimationGroup | None = None
        self._onboarding: OnboardingOverlay | None = None
        self._cards: list[NotificationCard] = []

        self.setWindowTitle("AgentBell 通知中心")
        self.setWindowIcon(make_app_icon())
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMinimumSize(MINIMUM_SIZE)
        self.resize(DEFAULT_SIZE)

        self._central = QWidget(self)
        self._central.setObjectName("centralHost")
        self.setCentralWidget(self._central)
        outer = QVBoxLayout(self._central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        self._root = QFrame(self._central)
        self._root.setObjectName("windowRoot")
        outer.addWidget(self._root)

        shadow = QGraphicsDropShadowEffect(self._root)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(15, 23, 42, 70))
        self._root.setGraphicsEffect(shadow)
        self._shadow = shadow

        layout = QHBoxLayout(self._root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._sidebar = self._build_sidebar()
        layout.addWidget(self._sidebar)

        content = QFrame(self._root)
        content.setObjectName("contentPanel")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        layout.addWidget(content, 1)

        content_layout.addWidget(self._build_topbar(content))

        body = QWidget(content)
        body.setObjectName("bodyHost")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self._stack = QStackedWidget(body)
        self._stack.setObjectName("pageStack")
        self._stack.addWidget(self._build_list_page())
        self._stack.addWidget(self._build_stats_page())
        self._stack.addWidget(self._build_sessions_page())
        self._stack.addWidget(self._build_launcher_page())
        self._toolchain_page = self._build_toolchain_page()
        self._stack.addWidget(self._toolchain_page)
        body_layout.addWidget(self._stack, 1)
        content_layout.addWidget(body, 1)

        self._grip = QSizeGrip(self._root)
        self._grip.setObjectName("sizeGrip")
        self._grip.setFixedSize(16, 16)
        self._grip.raise_()

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(2200)
        self._copy_timer.timeout.connect(self._reset_copy_button)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self._search_timer.timeout.connect(self._perform_search)

        self.setStyleSheet(_STYLESHEET)
        self._sync_window_state()
        self._update_filter_controls()

    # ---------- construction ----------

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(SIDEBAR_WIDTH)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(0)

        brand = QHBoxLayout()
        brand.setContentsMargins(8, 0, 4, 0)
        brand.setSpacing(10)

        mark = QLabel(sidebar)
        mark.setPixmap(make_app_icon().pixmap(32, 32))
        mark.setFixedSize(32, 32)
        brand.addWidget(mark)

        brand_text = QVBoxLayout()
        brand_text.setContentsMargins(0, 0, 0, 0)
        brand_text.setSpacing(1)
        name = QLabel("AgentBell", sidebar)
        name.setObjectName("brandName")
        tagline = QLabel(f"本机通知中心 · v{__version__}", sidebar)
        tagline.setObjectName("brandTagline")
        brand_text.addWidget(name)
        brand_text.addWidget(tagline)
        brand.addLayout(brand_text, 1)
        layout.addLayout(brand)

        layout.addSpacing(22)
        section = QLabel("视图", sidebar)
        section.setObjectName("sectionLabel")
        layout.addWidget(section)
        layout.addSpacing(7)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: dict[str, QPushButton] = {}
        nav_icons = {
            "all": _paint_icon("bell", QColor("#667085"), 16),
            "succeeded": _dot_icon("#2FB980"),
            "failed": _dot_icon("#EF6464"),
            "canceled": _dot_icon("#E3A33B"),
            "running": _dot_icon("#4F8CFF"),
        }
        for key, _label, _sidebar_label in FILTERS:
            button = QPushButton(FILTERS_LABELS[key], sidebar)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setAutoExclusive(False)
            button.setIcon(nav_icons[key])
            button.setIconSize(QSize(16, 16))
            button.setFixedHeight(38)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, value=key: self.set_filter(value)
            )
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            layout.addWidget(button)
            layout.addSpacing(2)

        layout.addSpacing(14)
        tools_section = QLabel("工具", sidebar)
        tools_section.setObjectName("sectionLabel")
        layout.addWidget(tools_section)
        layout.addSpacing(7)

        self._toolchain_button = QPushButton("运行环境", sidebar)
        self._toolchain_button.setObjectName("navButton")
        self._toolchain_button.setCheckable(True)
        self._toolchain_button.setAutoExclusive(False)
        self._toolchain_button.setIcon(
            _paint_icon("download", QColor("#667085"), 16)
        )
        self._toolchain_button.setIconSize(QSize(16, 16))
        self._toolchain_button.setFixedHeight(38)
        self._toolchain_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toolchain_button.setToolTip(
            "把 Node、常用 Agent CLI 与 cc-switch 安装到安装目录，免管理员权限"
        )
        self._toolchain_button.clicked.connect(self._on_toolchain_clicked)
        layout.addWidget(self._toolchain_button)

        self._launcher_button = QPushButton("Agent 启动", sidebar)
        self._launcher_button.setObjectName("navButton")
        self._launcher_button.setCheckable(True)
        self._launcher_button.setAutoExclusive(False)
        self._launcher_button.setIcon(
            _paint_icon("terminal", QColor("#667085"), 16)
        )
        self._launcher_button.setIconSize(QSize(16, 16))
        self._launcher_button.setFixedHeight(38)
        self._launcher_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._launcher_button.setToolTip(
            "检测本机已安装的 Agent，在项目目录里直接打开终端并输入提示词"
        )
        self._launcher_button.clicked.connect(self._on_launcher_clicked)
        layout.addWidget(self._launcher_button)

        self._stats_button = QPushButton("数据统计", sidebar)
        self._stats_button.setObjectName("navButton")
        self._stats_button.setCheckable(True)
        self._stats_button.setAutoExclusive(False)
        self._stats_button.setIcon(_paint_icon("stats", QColor("#667085"), 16))
        self._stats_button.setIconSize(QSize(16, 16))
        self._stats_button.setFixedHeight(38)
        self._stats_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stats_button.clicked.connect(self._on_stats_clicked)
        layout.addWidget(self._stats_button)

        self._sessions_button = QPushButton("Agent 会话", sidebar)
        self._sessions_button.setObjectName("navButton")
        self._sessions_button.setCheckable(True)
        self._sessions_button.setAutoExclusive(False)
        self._sessions_button.setIcon(
            _paint_icon("agents", QColor("#667085"), 16)
        )
        self._sessions_button.setIconSize(QSize(16, 16))
        self._sessions_button.setFixedHeight(38)
        self._sessions_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sessions_button.setToolTip("扫描本机 Claude Code 与 Qoder 的会话")
        self._sessions_button.clicked.connect(self._on_sessions_clicked)
        layout.addWidget(self._sessions_button)

        self.settings_button = QPushButton("偏好设置", sidebar)
        self.settings_button.setObjectName("navButton")
        self.settings_button.setIcon(
            _paint_icon("settings", QColor("#667085"), 16)
        )
        self.settings_button.setIconSize(QSize(16, 16))
        self.settings_button.setFixedHeight(38)
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_button.setToolTip("编辑提醒规则、静音时段、渠道与快捷键")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)

        layout.addStretch(1)

        service = QFrame(sidebar)
        service.setObjectName("serviceCard")
        service_layout = QVBoxLayout(service)
        service_layout.setContentsMargins(13, 12, 13, 12)
        service_layout.setSpacing(5)

        service_title = QHBoxLayout()
        service_title.setContentsMargins(0, 0, 0, 0)
        service_title.setSpacing(6)
        dot = QLabel("●", service)
        dot.setObjectName("serviceDot")
        service_title.addWidget(dot)
        title = QLabel("本地服务运行中", service)
        title.setObjectName("serviceTitle")
        service_title.addWidget(title, 1)
        service_layout.addLayout(service_title)

        self._endpoint_label = QLabel(f"127.0.0.1:{self.config.port}", service)
        self._endpoint_label.setObjectName("serviceEndpoint")
        service_layout.addWidget(self._endpoint_label)

        self._auth_label = QLabel(
            "X-Token 已开启" if self.config.auth_enabled else "X-Token 未开启",
            service,
        )
        self._auth_label.setObjectName("serviceAuth")
        self._auth_label.setProperty(
            "auth", "on" if self.config.auth_enabled else "off"
        )
        service_layout.addWidget(self._auth_label)

        self._hotkey_label = QLabel(
            f"快捷键 {self.config.hotkey}"
            if self.config.hotkey
            else "未设置全局快捷键",
            service,
        )
        self._hotkey_label.setObjectName("serviceHint")
        service_layout.addWidget(self._hotkey_label)

        service_layout.addSpacing(3)
        tray_hint = QLabel("关闭窗口后仍在托盘运行", service)
        tray_hint.setObjectName("serviceHint")
        service_layout.addWidget(tray_hint)
        layout.addWidget(service)

        layout.addSpacing(12)

        hide_button = QPushButton("隐藏到托盘", sidebar)
        hide_button.setObjectName("sideButton")
        hide_button.setFixedHeight(34)
        hide_button.setCursor(Qt.CursorShape.PointingHandCursor)
        hide_button.clicked.connect(self.hide_center)
        layout.addWidget(hide_button)
        layout.addSpacing(4)

        quit_button = QPushButton("退出 AgentBell", sidebar)
        quit_button.setObjectName("quitButton")
        quit_button.setFixedHeight(34)
        quit_button.setCursor(Qt.CursorShape.PointingHandCursor)
        quit_button.clicked.connect(self.quit_requested.emit)
        layout.addWidget(quit_button)

        return sidebar

    def _build_topbar(self, parent: QWidget) -> QWidget:
        topbar = TitleBar(self)
        topbar.setParent(parent)
        topbar.setObjectName("topBar")
        layout = QHBoxLayout(topbar)
        layout.setContentsMargins(22, 0, 12, 0)
        layout.setSpacing(10)

        mark = QLabel(topbar)
        mark.setPixmap(make_app_icon().pixmap(26, 26))
        mark.setFixedSize(26, 26)
        layout.addWidget(mark)

        title = QLabel("通知中心", topbar)
        title.setObjectName("topBarTitle")
        layout.addWidget(title)

        pill = QFrame(topbar)
        pill.setObjectName("statusPill")
        pill.setFixedHeight(24)
        pill_layout = QHBoxLayout(pill)
        pill_layout.setContentsMargins(9, 0, 10, 0)
        pill_layout.setSpacing(5)
        dot = QLabel("●", pill)
        dot.setObjectName("onlineDot")
        pill_layout.addWidget(dot)
        self._status_address = QLabel(
            f"127.0.0.1:{self.config.port} · 运行中", pill
        )
        self._status_address.setObjectName("statusPillText")
        pill_layout.addWidget(self._status_address)
        layout.addWidget(pill)
        layout.addStretch(1)

        self.copy_button = QPushButton("复制 Agent 接入指令", topbar)
        self.copy_button.setObjectName("copyButton")
        self.copy_button.setIcon(_paint_icon("copy", QColor("#FFFFFF"), 16))
        self.copy_button.setIconSize(QSize(16, 16))
        self.copy_button.setFixedSize(186, 34)
        self.copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_button.setToolTip("复制接入指令，粘贴给 Agent 后即可每轮自动推送")
        self.copy_button.setAccessibleName("复制 Agent 接入指令")
        self.copy_button.clicked.connect(self.copy_agent_instructions)
        layout.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignVCenter)

        divider = QFrame(topbar)
        divider.setObjectName("topDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        divider.setFixedHeight(22)
        layout.addSpacing(4)
        layout.addWidget(divider)
        layout.addSpacing(2)

        self._minimize_button = self._make_window_button(
            topbar, "—", "winButton", "最小化", self.showMinimized
        )
        self._maximize_button = self._make_window_button(
            topbar, "□", "winButton", "最大化", self.toggle_maximize
        )
        self._close_button = self._make_window_button(
            topbar, "✕", "closeButton", "关闭到托盘", self.close
        )
        layout.addWidget(self._minimize_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._maximize_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._close_button, 0, Qt.AlignmentFlag.AlignVCenter)

        return topbar

    def _make_window_button(
        self,
        parent: QWidget,
        text: str,
        name: str,
        tooltip: str,
        slot,
    ) -> QToolButton:
        button = QToolButton(parent)
        button.setObjectName(name)
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(38, 32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)

        heading_text = QVBoxLayout()
        heading_text.setContentsMargins(0, 0, 0, 0)
        heading_text.setSpacing(4)
        title = QLabel("通知记录", page)
        title.setObjectName("pageTitle")
        subtitle = QLabel("Agent 每完成一轮任务，都会在这里留下一条记录。", page)
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)

        live = QLabel("●  实时更新", page)
        live.setObjectName("livePill")
        heading.addWidget(live, 0, Qt.AlignmentFlag.AlignVCenter)
        self._total_label = QLabel("共 0 条", page)
        self._total_label.setObjectName("totalLabel")
        heading.addWidget(self._total_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        layout.addSpacing(18)

        toolbar = QWidget(page)
        toolbar.setObjectName("segmentHost")
        toolbar_row = QHBoxLayout(toolbar)
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(12)

        self._segment_bar = QFrame(toolbar)
        self._segment_bar.setObjectName("segmentBar")
        segment_layout = QHBoxLayout(self._segment_bar)
        segment_layout.setContentsMargins(4, 4, 4, 4)
        segment_layout.setSpacing(2)
        self._segment_group = QButtonGroup(self)
        self._segment_group.setExclusive(True)
        self._segment_buttons: dict[str, QPushButton] = {}
        for key, label, _ in FILTERS:
            button = QPushButton(f"{label} 0", self._segment_bar)
            button.setObjectName("segmentButton")
            button.setCheckable(True)
            button.setAutoExclusive(False)
            button.setFixedHeight(30)
            button.setMinimumWidth(62)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, value=key: self.set_filter(value)
            )
            self._segment_group.addButton(button)
            self._segment_buttons[key] = button
            segment_layout.addWidget(button)
        toolbar_row.addWidget(self._segment_bar)
        toolbar_row.addStretch(1)

        search_host = QFrame(toolbar)
        search_host.setObjectName("searchHost")
        search_host.setFixedSize(240, 32)
        search_layout = QHBoxLayout(search_host)
        search_layout.setContentsMargins(10, 0, 6, 0)
        search_layout.setSpacing(6)
        search_icon = QLabel(search_host)
        search_icon.setPixmap(_paint_icon("search", QColor("#8A919D"), 14).pixmap(14, 14))
        search_icon.setFixedSize(14, 14)
        search_layout.addWidget(search_icon)
        self._search_input = QLineEdit(search_host)
        self._search_input.setObjectName("searchInput")
        self._search_input.setPlaceholderText("搜索标题、摘要或来源")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFrame(False)
        self._search_input.setFixedHeight(26)
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.returnPressed.connect(self._perform_search)
        search_layout.addWidget(self._search_input, 1)
        toolbar_row.addWidget(search_host, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(toolbar)

        layout.addSpacing(14)

        self._scroll = QScrollArea(page)
        self._scroll.setObjectName("listArea")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setObjectName("listViewport")

        self._list_host = QWidget()
        self._list_host.setObjectName("listHost")
        self._list_layout = QVBoxLayout(self._list_host)
        self._list_layout.setContentsMargins(0, 0, 6, 0)
        self._list_layout.setSpacing(10)
        self._scroll.setWidget(self._list_host)
        layout.addWidget(self._scroll, 1)

        return page

    def _build_stats_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)

        heading_text = QVBoxLayout()
        heading_text.setContentsMargins(0, 0, 0, 0)
        heading_text.setSpacing(4)
        title = QLabel("数据统计", page)
        title.setObjectName("pageTitle")
        subtitle = QLabel("成功率、耗时与近 7 天的通知量。", page)
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)

        refresh = QPushButton("刷新", page)
        refresh.setObjectName("toolButton")
        refresh.setFixedSize(72, 32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.refresh_stats)
        heading.addWidget(refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        layout.addSpacing(18)

        cards = QHBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(12)
        self._stat_values: dict[str, QLabel] = {}
        for key, caption, accent in (
            ("total", "总通知", "total"),
            ("success", "成功率", "success"),
            ("avg", "平均耗时", "avg"),
            ("awaiting", "待确认", "awaiting"),
        ):
            cards.addWidget(self._make_stat_card(page, key, caption, accent), 1)
        layout.addLayout(cards)

        layout.addSpacing(14)

        chart_card = QFrame(page)
        chart_card.setObjectName("statsCard")
        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(16, 14, 16, 12)
        chart_layout.setSpacing(8)
        chart_title = QLabel("近 7 天通知量", chart_card)
        chart_title.setObjectName("statsTitle")
        chart_layout.addWidget(chart_title)
        self._daily_chart = DailyChart(chart_card)
        chart_layout.addWidget(self._daily_chart)
        layout.addWidget(chart_card)

        layout.addSpacing(14)

        status_card = QFrame(page)
        status_card.setObjectName("statsCard")
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(16, 14, 16, 14)
        status_layout.setSpacing(10)
        status_title = QLabel("状态分布", status_card)
        status_title.setObjectName("statsTitle")
        status_layout.addWidget(status_title)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(8)
        self._stats_status_labels: dict[str, QLabel] = {}
        for key, _label, _sidebar_label in FILTERS:
            if key == "all":
                continue
            chip = QLabel(f"{STATUS_LABELS[key]} 0", status_card)
            chip.setObjectName("statsChip")
            chip.setProperty("status", key)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setFixedHeight(24)
            chips.addWidget(chip)
            self._stats_status_labels[key] = chip
        chips.addStretch(1)

        self._stats_hint = QLabel("", status_card)
        self._stats_hint.setObjectName("statsHint")
        self._stats_hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        chips.addWidget(self._stats_hint)
        status_layout.addLayout(chips)
        layout.addWidget(status_card)

        layout.addStretch(1)
        return page

    def _build_sessions_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._session_view_stack = QStackedWidget(page)
        self._session_view_stack.setObjectName("pageStack")
        self._session_view_stack.addWidget(self._build_session_list())
        self._session_view_stack.addWidget(self._build_session_detail())
        layout.addWidget(self._session_view_stack, 1)

        QTimer.singleShot(0, self._rebuild_session_cards)
        return page

    def _build_launcher_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 20)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)
        heading_text = QVBoxLayout()
        heading_text.setContentsMargins(0, 0, 0, 0)
        heading_text.setSpacing(4)
        title = QLabel("Agent 启动", page)
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "检测本机 Agent；双击卡片可直接启动，也可以选择项目后点「打开终端并开始」。",
            page,
        )
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)
        self._update_button = QPushButton("检查更新", page)
        self._update_button.setObjectName("toolButton")
        self._update_button.setFixedSize(84, 32)
        self._update_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_button.setToolTip("检查 AgentBell 自身的新版本")
        self._update_button.clicked.connect(self.update_check_requested.emit)
        heading.addWidget(self._update_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._agent_link = QPushButton("项目主页", page)
        self._agent_link.setObjectName("toolButton")
        self._agent_link.setFixedSize(84, 32)
        self._agent_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._agent_link.setToolTip("打开当前选中 Agent 的官网或 GitHub 仓库")
        self._agent_link.setEnabled(False)
        self._agent_link.clicked.connect(self._open_selected_agent_page)
        heading.addWidget(self._agent_link, 0, Qt.AlignmentFlag.AlignVCenter)
        refresh = QPushButton("重新检测", page)
        refresh.setObjectName("toolButton")
        refresh.setFixedSize(84, 32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(lambda: self._refresh_agents())
        heading.addWidget(refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        layout.addSpacing(14)

        scroll = QScrollArea(page)
        scroll.setObjectName("listArea")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setObjectName("listHost")
        self._launcher_layout = QVBoxLayout(host)
        self._launcher_layout.setContentsMargins(0, 0, 6, 6)
        self._launcher_layout.setSpacing(14)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        self._launcher_layout.addWidget(
            self._launcher_section(
                host,
                "选择 Agent",
                "已安装的排在前面；未安装的会显示安装命令，安装后点右上角「重新检测」。",
            )
        )

        grid_host = QWidget(host)
        self._agent_grid = QGridLayout(grid_host)
        self._agent_grid.setContentsMargins(0, 0, 0, 0)
        self._agent_grid.setHorizontalSpacing(10)
        self._agent_grid.setVerticalSpacing(10)
        self._agent_grid.setColumnStretch(0, 1)
        self._agent_grid.setColumnStretch(1, 1)
        self._launcher_layout.addWidget(grid_host)

        self._launcher_layout.addWidget(
            self._launcher_section(
                host,
                "项目目录",
                "默认在安装目录的 chat/ 子目录启动（首次启动自动创建），也可以换成本机其他项目。",
            )
        )
        project_panel = QFrame(host)
        project_panel.setObjectName("launchPanel")
        project_layout = QVBoxLayout(project_panel)
        project_layout.setContentsMargins(14, 12, 14, 12)
        project_layout.setSpacing(9)
        project_row = QHBoxLayout()
        project_row.setContentsMargins(0, 0, 0, 0)
        project_row.setSpacing(8)
        self._launcher_project = QLineEdit(project_panel)
        self._launcher_project.setObjectName("launchProject")
        self._launcher_project.setFixedHeight(34)
        self._launcher_project.setPlaceholderText(
            "选择或粘贴项目目录，例如 E:\\work\\demo"
        )
        self._launcher_project.setClearButtonEnabled(True)
        self._launcher_project.setText(str(default_project_dir()))
        project_row.addWidget(self._launcher_project, 1)
        browse = QPushButton("浏览…", project_panel)
        browse.setObjectName("toolButton")
        browse.setFixedSize(76, 34)
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self._browse_launcher_project)
        project_row.addWidget(browse)
        project_layout.addLayout(project_row)

        recent_row = QHBoxLayout()
        recent_row.setContentsMargins(0, 0, 0, 0)
        recent_row.setSpacing(8)
        recent_label = QLabel("最近项目", project_panel)
        recent_label.setObjectName("launchFieldLabel")
        recent_row.addWidget(recent_label)
        self._launcher_recent = QComboBox(project_panel)
        self._launcher_recent.setObjectName("launchRecent")
        self._launcher_recent.setFixedHeight(30)
        self._launcher_recent.setMinimumWidth(240)
        self._launcher_recent.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self._launcher_recent.currentIndexChanged.connect(
            self._on_recent_project_changed
        )
        recent_row.addWidget(self._launcher_recent, 1)
        project_layout.addLayout(recent_row)
        self._launcher_layout.addWidget(project_panel)

        self._launcher_layout.addWidget(
            self._launcher_section(
                host,
                "初始提示词",
                "提示词会作为 Agent 的第一个参数传入，不拼接进命令行；留空则只打开交互界面。",
            )
        )
        prompt_panel = QFrame(host)
        prompt_panel.setObjectName("launchPanel")
        prompt_layout = QVBoxLayout(prompt_panel)
        prompt_layout.setContentsMargins(14, 12, 14, 12)
        prompt_layout.setSpacing(8)
        self._launcher_prompt = QPlainTextEdit(prompt_panel)
        self._launcher_prompt.setObjectName("launchPrompt")
        self._launcher_prompt.setFixedHeight(92)
        self._launcher_prompt.setTabChangesFocus(True)
        self._launcher_prompt.setPlaceholderText(
            "例如：先阅读项目结构，说明当前状态，然后实现……"
        )
        prompt_layout.addWidget(self._launcher_prompt)
        self._launcher_layout.addWidget(prompt_panel)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(10)
        self._launcher_start = QPushButton("打开终端并开始", host)
        self._launcher_start.setObjectName("launchButton")
        self._launcher_start.setFixedSize(150, 38)
        self._launcher_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self._launcher_start.clicked.connect(self._launch_selected_agent)
        action_row.addWidget(self._launcher_start)
        self._launcher_status = QLabel("", host)
        self._launcher_status.setObjectName("launchStatus")
        self._launcher_status.setWordWrap(True)
        self._launcher_status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        action_row.addWidget(self._launcher_status, 1)
        self._launcher_layout.addLayout(action_row)

        self._launcher_layout.addWidget(
            self._launcher_section(
                host,
                "本次打开的终端",
                "从 AgentBell 打开的终端可以一键切回；关闭终端后按钮会失效。",
            )
        )
        self._launch_records_host = QWidget(host)
        self._launch_records_layout = QVBoxLayout(self._launch_records_host)
        self._launch_records_layout.setContentsMargins(0, 0, 0, 0)
        self._launch_records_layout.setSpacing(6)
        self._launcher_layout.addWidget(self._launch_records_host)
        self._launcher_layout.addStretch(1)

        self._refresh_recent_projects()
        self._refresh_launch_records()
        self._refresh_agents(choose=self.config.agent_launcher.last_agent)
        return page

    def _build_toolchain_page(self) -> QWidget:
        page = ToolchainPage(runtime_dir(), self.config.toolchain, self.logger)
        page.changed.connect(self._on_toolchain_changed)
        page.config_patch_requested.connect(self._on_toolchain_patch)
        page.provider_launch_requested.connect(self._launch_with_provider)
        return page

    def _on_toolchain_changed(self) -> None:
        self._refresh_agents()

    def _on_toolchain_patch(self, patch: object) -> None:
        if not isinstance(patch, dict):
            return
        allowed = {"npm_registry", "deepseek_key"}
        updates = {key: value for key, value in patch.items() if key in allowed}
        if not updates:
            return
        toolchain = replace(self.config.toolchain, **updates)
        self.settings_saved.emit(replace(self.config, toolchain=toolchain))

    def _launch_with_provider(self, extra_env: object) -> None:
        if not isinstance(extra_env, dict):
            return
        availability = next(
            (item for item in discover_agents() if item.spec.id == "claude-code"),
            None,
        )
        if availability is None or not availability.installed:
            self._toolchain_page.notify(
                "未检测到 Claude Code，请先在「运行环境」里安装", error=True
            )
            return
        result = launch_agent(
            availability, str(default_project_dir()), "", extra_env=extra_env
        )
        self._toolchain_page.notify(result.message, error=not result.ok)
        if result.ok:
            self._refresh_agents()

    def _launcher_section(
        self, parent: QWidget, title: str, hint: str
    ) -> QWidget:
        host = QWidget(parent)
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        label = QLabel(title, host)
        label.setObjectName("launchSection")
        detail = QLabel(hint, host)
        detail.setObjectName("launchSectionHint")
        detail.setWordWrap(True)
        box.addWidget(label)
        box.addWidget(detail)
        return host

    def _current_agent(self) -> AgentAvailability | None:
        for availability in self._agent_availabilities:
            if availability.spec.id == self._selected_agent_id:
                return availability
        return None

    def _open_selected_agent_page(self) -> None:
        availability = self._current_agent()
        if availability is None:
            return
        url = safe_http_url(availability.spec.project_url)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _refresh_agents(self, choose: str = "") -> None:
        if not hasattr(self, "_agent_grid"):
            return
        preferred = choose or self._selected_agent_id
        while self._agent_grid.count():
            entry = self._agent_grid.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._agent_cards = []
        self._agent_availabilities = discover_agents()
        for index, availability in enumerate(self._agent_availabilities):
            card = AgentPickCard(availability, self._agent_grid.parentWidget())
            card.picked.connect(self._select_agent)
            card.activated.connect(self._activate_agent)
            self._agent_grid.addWidget(card, index // 2, index % 2)
            self._agent_cards.append(card)

        installed = [
            item for item in self._agent_availabilities if item.installed
        ]
        target = next(
            (
                item
                for item in installed
                if item.spec.id == preferred
            ),
            installed[0] if installed else (
                self._agent_availabilities[0] if self._agent_availabilities else None
            ),
        )
        if target is not None:
            self._select_agent(target)
        else:
            self._selected_agent_id = ""
            self._sync_launcher_start()
        if not installed:
            self._set_launcher_status(
                "没有检测到已安装的 Agent，请按卡片提示安装后重新检测。",
                error=True,
            )

    def _activate_agent(self, availability: AgentAvailability) -> None:
        self._select_agent(availability)
        if availability.installed:
            self._launch_selected_agent()

    def _select_agent(self, availability: AgentAvailability) -> None:
        self._selected_agent_id = availability.spec.id
        for card in self._agent_cards:
            card.set_selected(
                card.availability.spec.id == self._selected_agent_id
            )
        self._sync_launcher_start()
        if hasattr(self, "_agent_link"):
            url = safe_http_url(availability.spec.project_url)
            self._agent_link.setEnabled(bool(url))
            self._agent_link.setToolTip(
                url or "该 Agent 没有配置项目主页"
            )
        if availability.installed:
            self._set_launcher_status(
                f"已选择 {availability.spec.name} · {availability.executable}"
            )
        else:
            self._set_launcher_status(
                f"{availability.spec.name} 未安装：{availability.spec.install_hint}",
                error=True,
            )

    def _sync_launcher_start(self) -> None:
        if not hasattr(self, "_launcher_start"):
            return
        availability = self._current_agent()
        enabled = bool(availability and availability.installed)
        self._launcher_start.setEnabled(enabled)
        self._launcher_start.setToolTip(
            "" if enabled else "请先选择一个已安装的 Agent"
        )

    def _set_launcher_status(self, text: str, error: bool = False) -> None:
        if not hasattr(self, "_launcher_status"):
            return
        self._launcher_status.setProperty("state", "error" if error else "info")
        self._launcher_status.setText(text)
        _repolish(self._launcher_status)

    def _refresh_recent_projects(self) -> None:
        if not hasattr(self, "_launcher_recent"):
            return
        projects = list(self.config.agent_launcher.recent_projects)
        self._launcher_recent.blockSignals(True)
        self._launcher_recent.clear()
        self._launcher_recent.addItem("选择最近项目…", "")
        for path in projects:
            self._launcher_recent.addItem(path, path)
        if not projects:
            self._launcher_recent.setEnabled(False)
        else:
            self._launcher_recent.setEnabled(True)
            current = self._launcher_project.text().strip()
            if current:
                index = self._launcher_recent.findData(current)
                if index >= 0:
                    self._launcher_recent.setCurrentIndex(index)
        self._launcher_recent.blockSignals(False)

    def _on_recent_project_changed(self, index: int) -> None:
        if index <= 0 or not hasattr(self, "_launcher_project"):
            return
        path = self._launcher_recent.itemData(index) or ""
        if path:
            self._launcher_project.setText(path)

    def _browse_launcher_project(self) -> None:
        start = self._launcher_project.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择项目目录", start)
        if path:
            self._launcher_project.setText(path)
            self._set_launcher_status("")

    def _launch_selected_agent(self) -> None:
        availability = self._current_agent()
        if availability is None or not availability.installed:
            self._set_launcher_status("请先选择一个已安装的 Agent", error=True)
            return
        project = self._launcher_project.text().strip()
        if not project or not Path(project).expanduser().is_dir():
            self._set_launcher_status("项目目录不存在，请重新选择", error=True)
            self._launcher_project.setFocus()
            return
        prompt = self._launcher_prompt.toPlainText()
        if availability.spec.kind == "desktop" and prompt.strip():
            choice = QMessageBox.question(
                self,
                "桌面应用不支持提示词",
                f"{availability.spec.name} 是桌面应用，AgentBell 只能打开它，"
                "无法把提示词自动填进输入框。\n\n仍要打开吗？",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if choice != QMessageBox.StandardButton.Yes:
                return
        result = launch_agent(availability, project, prompt)
        if not result.ok:
            self._set_launcher_status(result.message, error=True)
            self.logger.warning(
                "启动 Agent 失败 agent=%s：%s", availability.spec.id, result.message
            )
            return
        self._set_launcher_status(result.message)
        self.logger.info(
            "启动 Agent agent=%s project=%s pid=%s prompt=%s",
            availability.spec.id,
            result.working_dir,
            result.pid,
            "yes" if result.prompt_sent else "no",
        )
        self._remember_launch(availability.spec.id, project)
        self._launch_records = ([result] + self._launch_records)[:5]
        self._refresh_launch_records()

    def _remember_launch(self, agent_id: str, project: str) -> None:
        recent = [project] + [
            path
            for path in self.config.agent_launcher.recent_projects
            if path.casefold() != project.casefold()
        ]
        launcher = AgentLauncherConfig(
            recent_projects=tuple(recent[:6]),
            last_agent=agent_id,
        )
        config = replace(self.config, agent_launcher=launcher)
        self.config = config
        if self._config_path is not None:
            try:
                save_config(self._config_path, config)
            except ConfigError as exc:
                self.logger.warning("保存最近项目失败：%s", exc)
        self._refresh_recent_projects()
        self._launcher_recent.setCurrentIndex(
            self._launcher_recent.findData(project)
        )

    def _refresh_launch_records(self) -> None:
        if not hasattr(self, "_launch_records_layout"):
            return
        while self._launch_records_layout.count():
            entry = self._launch_records_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not self._launch_records:
            empty = QLabel("还没有从 AgentBell 打开过终端。", self._launch_records_host)
            empty.setObjectName("launchRecordEmpty")
            self._launch_records_layout.addWidget(empty)
            return
        for result in self._launch_records:
            card = LaunchRecordCard(result, self._launch_records_host)
            card.focus_requested.connect(self.focus_requested.emit)
            self._launch_records_layout.addWidget(card)

    def _focus_session(self, session: AgentSession) -> None:
        query = session.project or Path(session.project_path).name
        if not query:
            self.logger.warning("会话缺少项目名，无法匹配终端窗口")
            return
        self.focus_requested.emit(
            FocusRequest(
                pid=None,
                window_title=query,
                working_dir=session.project_path,
            )
        )

    def _focus_detail_session(self) -> None:
        if self._session_detail_session is not None:
            self._focus_session(self._session_detail_session)

    def _make_search_box(
        self, parent: QWidget, placeholder: str, width: int = 260
    ) -> tuple[QFrame, QLineEdit]:
        host = QFrame(parent)
        host.setObjectName("searchHost")
        host.setFixedSize(width, 32)
        layout = QHBoxLayout(host)
        layout.setContentsMargins(10, 0, 6, 0)
        layout.setSpacing(6)
        icon = QLabel(host)
        icon.setPixmap(
            _paint_icon("search", QColor("#8A919D"), 14).pixmap(14, 14)
        )
        icon.setFixedSize(14, 14)
        layout.addWidget(icon)
        edit = QLineEdit(host)
        edit.setObjectName("searchInput")
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.setFrame(False)
        edit.setFixedHeight(26)
        layout.addWidget(edit, 1)
        return host, edit

    def _build_session_list(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)
        heading_text = QVBoxLayout()
        heading_text.setContentsMargins(0, 0, 0, 0)
        heading_text.setSpacing(4)
        title = QLabel("Agent 会话", page)
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "扫描本机 Claude Code 与 Qoder 的会话，可直接在软件内查看完整记录。",
            page,
        )
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)

        refresh = QPushButton("立即扫描", page)
        refresh.setObjectName("toolButton")
        refresh.setFixedSize(84, 32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.session_refresh_requested.emit)
        heading.addWidget(refresh, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        layout.addSpacing(16)

        toolbar = QWidget(page)
        toolbar_row = QHBoxLayout(toolbar)
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(12)
        self._session_summary = QLabel("尚未扫描", toolbar)
        self._session_summary.setObjectName("sessionSummary")
        toolbar_row.addWidget(self._session_summary, 1)

        search_host, self._session_search = self._make_search_box(
            toolbar, "搜索项目、标题、会话 ID 或路径"
        )
        self._session_search.textChanged.connect(
            lambda _text: self._rebuild_session_cards()
        )
        toolbar_row.addWidget(search_host, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(toolbar)

        layout.addSpacing(14)

        self._session_scroll = QScrollArea(page)
        self._session_scroll.setObjectName("listArea")
        self._session_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._session_scroll.setWidgetResizable(True)
        self._session_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._session_scroll.viewport().setAutoFillBackground(False)
        self._session_host = QWidget()
        self._session_host.setObjectName("listHost")
        self._session_layout = QVBoxLayout(self._session_host)
        self._session_layout.setContentsMargins(0, 0, 6, 0)
        self._session_layout.setSpacing(8)
        self._session_scroll.setWidget(self._session_host)
        layout.addWidget(self._session_scroll, 1)
        return page

    def _build_session_detail(self) -> QWidget:
        page = QWidget()
        page.setObjectName("bodyPanel")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 18, 28, 20)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)

        back = QToolButton(page)
        back.setObjectName("detailIcon")
        back.setIcon(_paint_icon("back", QColor("#5A6472"), 16))
        back.setIconSize(QSize(16, 16))
        back.setFixedSize(30, 30)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setToolTip("返回会话列表")
        back.clicked.connect(self._close_session_view)
        header.addWidget(back, 0, Qt.AlignmentFlag.AlignVCenter)

        self._detail_agent = QLabel("", page)
        self._detail_agent.setObjectName("sessionAgent")
        self._detail_agent.setProperty("agent", "claude")
        self._detail_agent.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_agent.setFixedSize(70, 22)
        header.addWidget(self._detail_agent, 0, Qt.AlignmentFlag.AlignVCenter)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(2)
        self._detail_title = ElidedLabel("", page)
        self._detail_title.setObjectName("detailTitle")
        self._detail_meta = ElidedLabel("", page)
        self._detail_meta.setObjectName("detailMeta")
        title_box.addWidget(self._detail_title)
        title_box.addWidget(self._detail_meta)
        header.addLayout(title_box, 1)

        self._detail_terminal_button = QPushButton("回到终端", page)
        self._detail_terminal_button.setObjectName("detailAction")
        self._detail_terminal_button.setFixedSize(78, 28)
        self._detail_terminal_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self._detail_terminal_button.setToolTip(
            "按项目名匹配终端或编辑器窗口，只切到窗口，不选中标签页"
        )
        self._detail_terminal_button.clicked.connect(
            self._focus_detail_session
        )
        header.addWidget(
            self._detail_terminal_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self._outline_button = QToolButton(page)
        self._outline_button.setObjectName("detailMenu")
        self._outline_button.setText("目录")
        self._outline_button.setFixedSize(58, 28)
        self._outline_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._outline_button.setPopupMode(
            QToolButton.ToolButtonPopupMode.InstantPopup
        )
        self._outline_menu = QMenu(self._outline_button)
        self._outline_button.setMenu(self._outline_menu)
        self._outline_button.setToolTip("按轮次跳转")
        header.addWidget(
            self._outline_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self._detail_copy_button = QPushButton("复制全文", page)
        self._detail_copy_button.setObjectName("detailAction")
        self._detail_copy_button.setFixedSize(72, 28)
        self._detail_copy_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_copy_button.setToolTip("复制整段会话为 Markdown")
        self._detail_copy_button.clicked.connect(
            self._copy_transcript_markdown
        )
        header.addWidget(
            self._detail_copy_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        self._detail_export_button = QPushButton("导出 MD", page)
        self._detail_export_button.setObjectName("detailAction")
        self._detail_export_button.setFixedSize(72, 28)
        self._detail_export_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._detail_export_button.setToolTip("将会话导出为 Markdown 文件")
        self._detail_export_button.clicked.connect(
            self._export_transcript_markdown
        )
        header.addWidget(
            self._detail_export_button, 0, Qt.AlignmentFlag.AlignVCenter
        )

        folder = QToolButton(page)
        folder.setObjectName("detailIcon")
        folder.setIcon(_paint_icon("folder", QColor("#5A6472"), 16))
        folder.setIconSize(QSize(16, 16))
        folder.setFixedSize(30, 30)
        folder.setCursor(Qt.CursorShape.PointingHandCursor)
        folder.setToolTip("打开会话目录")
        folder.clicked.connect(self._open_detail_folder)
        header.addWidget(folder, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header)

        layout.addSpacing(12)

        toolbar = QWidget(page)
        toolbar_row = QHBoxLayout(toolbar)
        toolbar_row.setContentsMargins(0, 0, 0, 0)
        toolbar_row.setSpacing(12)
        self._transcript_hint = QLabel("", toolbar)
        self._transcript_hint.setObjectName("sessionSummary")
        toolbar_row.addWidget(self._transcript_hint, 1)

        search_host, self._transcript_search = self._make_search_box(
            toolbar, "在会话内容中搜索", 280
        )
        self._transcript_search.textChanged.connect(
            self._apply_transcript_search
        )
        toolbar_row.addWidget(search_host, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(toolbar)

        layout.addSpacing(10)

        self._transcript_scroll = QScrollArea(page)
        self._transcript_scroll.setObjectName("listArea")
        self._transcript_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._transcript_scroll.setWidgetResizable(True)
        self._transcript_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._transcript_scroll.viewport().setAutoFillBackground(False)
        self._transcript_host = QWidget()
        self._transcript_host.setObjectName("listHost")
        self._transcript_layout = QVBoxLayout(self._transcript_host)
        self._transcript_layout.setContentsMargins(0, 0, 6, 0)
        self._transcript_layout.setSpacing(8)
        self._transcript_scroll.setWidget(self._transcript_host)
        layout.addWidget(self._transcript_scroll, 1)
        return page

    def _make_stat_card(
        self, parent: QWidget, key: str, caption: str, accent: str
    ) -> QFrame:
        card = QFrame(parent)
        card.setObjectName("statCard")
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        card.setFixedHeight(88)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(2)
        value = QLabel("—", card)
        value.setObjectName("statValue")
        value.setProperty("accent", accent)
        card_layout.addWidget(value)
        label = QLabel(caption, card)
        label.setObjectName("statCaption")
        card_layout.addWidget(label)
        self._stat_values[key] = value
        return card

    # ---------- data / filters ----------

    def refresh_items(self, items: list[Notification]) -> None:
        self._items = list(items)
        signature = tuple(
            (
                item.id,
                item.status,
                item.acknowledged,
                item.occurrence_count,
                item.progress,
                item.updated_at,
            )
            for item in self._items
        )
        if signature == self._signature:
            if self._page == "stats":
                self.refresh_stats()
            return
        self._signature = signature
        if self._query:
            self._search_items = self._store.search(self._query, MAX_SEARCH_RESULTS)
        self._update_counts()
        self._rebuild_cards()
        if self._page == "stats":
            self.refresh_stats()

    def set_filter(self, key: str) -> None:
        if key not in FILTERS_LABELS:
            return
        if self._page != "list":
            self.set_page("list")
        changed = key != self._filter
        self._filter = key
        self._update_filter_controls()
        if changed:
            self._rebuild_cards()

    def set_page(self, page: str) -> None:
        if page not in {"list", "stats", "sessions", "launcher", "toolchain"}:
            return
        changed = page != self._page
        self._page = page
        self._stack.setCurrentIndex(
            {"list": 0, "stats": 1, "sessions": 2, "launcher": 3, "toolchain": 4}[page]
        )
        self._stats_button.blockSignals(True)
        self._stats_button.setChecked(page == "stats")
        self._stats_button.blockSignals(False)
        self._sessions_button.blockSignals(True)
        self._sessions_button.setChecked(page == "sessions")
        self._sessions_button.blockSignals(False)
        self._launcher_button.blockSignals(True)
        self._launcher_button.setChecked(page == "launcher")
        self._launcher_button.blockSignals(False)
        self._toolchain_button.blockSignals(True)
        self._toolchain_button.setChecked(page == "toolchain")
        self._toolchain_button.blockSignals(False)
        self._update_filter_controls()
        if page == "stats":
            self.refresh_stats()
        elif page == "sessions":
            self._update_session_summary()
            self._rebuild_session_cards()
            self.session_refresh_requested.emit()
        elif page == "launcher":
            self._sync_launcher_start()
            self._refresh_launch_records()
        elif page == "toolchain":
            self._toolchain_page.refresh()
        elif changed:
            self._rebuild_cards()

    def _on_stats_clicked(self, checked: bool) -> None:
        self.set_page("stats" if checked else "list")

    def _on_sessions_clicked(self, checked: bool) -> None:
        self.set_page("sessions" if checked else "list")

    def _on_launcher_clicked(self, checked: bool) -> None:
        self.set_page("launcher" if checked else "list")

    def _on_toolchain_clicked(self, checked: bool) -> None:
        self.set_page("toolchain" if checked else "list")

    def _update_filter_controls(self) -> None:
        for key, button in self._nav_buttons.items():
            button.setChecked(self._page == "list" and key == self._filter)
        for key, button in self._segment_buttons.items():
            button.setChecked(key == self._filter)

    def _source_items(self) -> list[Notification]:
        if self._query:
            return list(self._search_items)
        return list(self._items)

    def _update_counts(self) -> None:
        items = self._source_items()
        counts = {
            "all": len(items),
            "succeeded": 0,
            "failed": 0,
            "canceled": 0,
            "running": 0,
        }
        for item in items:
            if item.status in counts:
                counts[item.status] += 1
        for key, label, _ in FILTERS:
            if key in self._segment_buttons:
                self._segment_buttons[key].setText(f"{label} {counts[key]}")
            if key in self._nav_buttons:
                self._nav_buttons[key].setToolTip(f"共 {counts[key]} 条通知")
        if self._query:
            self._total_label.setText(f"搜索到 {len(items)} 条")
        else:
            self._total_label.setText(f"共 {len(items)} 条")

    def _filtered_items(self) -> list[Notification]:
        items = self._source_items()
        if self._filter == "all":
            return items
        return [item for item in items if item.status == self._filter]

    def _clear_cards(self) -> None:
        while self._list_layout.count():
            entry = self._list_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._cards = []

    def _rebuild_cards(self) -> None:
        scrollbar = self._scroll.verticalScrollBar()
        previous = scrollbar.value()
        self._clear_cards()

        filtered = self._filtered_items()
        if not filtered:
            empty = EmptyState(
                bool(self._source_items()),
                parent=self._list_host,
                query=self._query,
            )
            empty.copy_requested.connect(self.copy_agent_instructions)
            empty.reset_filter_requested.connect(self._reset_filters)
            self._list_layout.addWidget(empty, 1)
        else:
            for index, notification in enumerate(filtered[:MAX_VISIBLE_CARDS]):
                card = NotificationCard(
                    notification,
                    self.logger,
                    latest=index == 0,
                    allow_local_paths=self.config.allow_local_paths,
                    parent=self._list_host,
                )
                card.replay_requested.connect(self.replay_requested.emit)
                card.ack_requested.connect(self.ack_requested.emit)
                card.snooze_requested.connect(self.snooze_requested.emit)
                card.action_requested.connect(self.action_requested.emit)
                self._list_layout.addWidget(card)
                self._cards.append(card)
            self._list_layout.addStretch(1)
            if len(filtered) > MAX_VISIBLE_CARDS:
                hint = QLabel(
                    f"仅显示最近 {MAX_VISIBLE_CARDS} 条，共 {len(filtered)} 条。",
                    self._list_host,
                )
                hint.setObjectName("listHint")
                hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._list_layout.addWidget(hint)

        QTimer.singleShot(
            0,
            lambda: scrollbar.setValue(min(previous, scrollbar.maximum())),
        )

    def _on_search_changed(self, _text: str) -> None:
        if not self._search_input.text().strip():
            self._search_timer.stop()
            self._perform_search()
        else:
            self._search_timer.start()

    def _perform_search(self) -> None:
        query = self._search_input.text().strip()
        self._query = query
        if query:
            self._search_items = self._store.search(query, MAX_SEARCH_RESULTS)
        else:
            self._search_items = []
        if self._page != "list":
            self.set_page("list")
        self._update_counts()
        self._rebuild_cards()

    def _reset_filters(self) -> None:
        self._search_timer.stop()
        self._search_input.blockSignals(True)
        self._search_input.clear()
        self._search_input.blockSignals(False)
        self._query = ""
        self._search_items = []
        self._filter = "all"
        if self._page != "list":
            self.set_page("list")
        self._update_counts()
        self._rebuild_cards()
        self._update_filter_controls()

    def refresh_stats(self) -> None:
        if not hasattr(self, "_stat_values"):
            return
        stats = self._store.stats(days=7)
        self._stats = stats
        self._stat_values["total"].setText(str(int(stats.get("total") or 0)))
        rate = stats.get("success_rate")
        self._stat_values["success"].setText(
            "—" if rate is None else f"{float(rate) * 100:.0f}%"
        )
        self._stat_values["avg"].setText(
            format_seconds(stats.get("avg_duration_seconds"))
        )
        self._stat_values["awaiting"].setText(
            str(int(stats.get("awaiting_ack") or 0))
        )
        self._daily_chart.set_data(stats.get("daily") or [])
        for key, label in self._stats_status_labels.items():
            label.setText(f"{STATUS_LABELS[key]} {int(stats.get(key) or 0)}")
        if self.config.history.enabled and self._store.persistent:
            self._stats_hint.setText(
                f"来自本地历史 · 保留 {self.config.history.limit} 条"
            )
        elif self.config.history.enabled:
            self._stats_hint.setText("历史数据库未启用，仅统计本次运行")
        else:
            self._stats_hint.setText("历史记录已关闭，仅统计本次运行")

    # ---------- agent sessions ----------

    def update_sessions(self, sessions: list[AgentSession]) -> None:
        self._sessions = list(sessions)
        self._session_scanned_at = datetime.now().astimezone()
        self._update_session_summary()
        if self._page == "sessions":
            self._rebuild_session_cards()

    def _update_session_summary(self) -> None:
        if not hasattr(self, "_session_summary"):
            return
        if not self.config.agent_sessions.enabled:
            self._session_summary.setText("会话扫描已在偏好设置中关闭")
            return
        if self._session_scanned_at is None:
            self._session_summary.setText("尚未扫描")
            return
        self._session_summary.setText(
            f"共 {len(self._sessions)} 个会话 · 最近扫描 "
            f"{self._session_scanned_at.strftime('%H:%M:%S')}"
        )

    def _filtered_sessions(self) -> list[AgentSession]:
        query = (
            self._session_search.text().strip().lower()
            if hasattr(self, "_session_search")
            else ""
        )
        if not query:
            return list(self._sessions)
        return [
            session
            for session in self._sessions
            if query
            in " ".join(
                (
                    session.project,
                    session.title,
                    session.agent_label,
                    session.session_id,
                    session.project_path,
                    session.path,
                )
            ).lower()
        ]

    def _clear_session_cards(self) -> None:
        while self._session_layout.count():
            entry = self._session_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def _rebuild_session_cards(self) -> None:
        if not hasattr(self, "_session_layout"):
            return
        self._clear_session_cards()
        sessions = self._filtered_sessions()
        if not sessions:
            host = QWidget(self._session_host)
            empty = QVBoxLayout(host)
            empty.setContentsMargins(24, 66, 24, 40)
            empty.setSpacing(8)
            empty.addStretch(1)
            title = QLabel(host)
            title.setObjectName("sessionEmptyTitle")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text = QLabel(host)
            text.setObjectName("sessionEmptyText")
            text.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text.setWordWrap(True)
            if self._session_search.text().strip():
                title.setText("没有匹配的会话")
                text.setText("换一个项目名、会话 ID 或路径关键词试试。")
            elif not self.config.agent_sessions.enabled:
                title.setText("会话扫描已关闭")
                text.setText("可在 偏好设置 → Agent 会话 中重新开启。")
            else:
                title.setText("还没有扫描到会话")
                text.setText(
                    "点击右上角「立即扫描」，这里会按项目列出本机 "
                    "Claude Code 与 Qoder 的会话。"
                )
            empty.addWidget(title)
            empty.addWidget(text)
            empty.addStretch(2)
            self._session_layout.addWidget(host)
            return

        grouped: dict[str, list[AgentSession]] = {}
        for session in sessions:
            grouped.setdefault(session.project or "未知项目", []).append(session)

        for project, items in grouped.items():
            header = QWidget(self._session_host)
            header_row = QHBoxLayout(header)
            header_row.setContentsMargins(2, 8, 2, 2)
            header_row.setSpacing(8)
            name = QLabel(project, header)
            name.setObjectName("sessionGroupTitle")
            if items[0].project_path:
                name.setToolTip(items[0].project_path)
            header_row.addWidget(name)
            count = QLabel(f"{len(items)} 个会话", header)
            count.setObjectName("sessionGroupCount")
            header_row.addWidget(count)
            header_row.addStretch(1)
            self._session_layout.addWidget(header)

            for session in items:
                card = AgentSessionCard(session, self._session_host)
                card.open_requested.connect(self._open_session_folder)
                card.copy_requested.connect(self._copy_session_path)
                card.view_requested.connect(self._open_session_view)
                card.terminal_requested.connect(self._focus_session)
                self._session_layout.addWidget(card)
        self._session_layout.addStretch(1)

    def _session_target(self, session: AgentSession) -> str:
        if session.project_path and Path(session.project_path).exists():
            return session.project_path
        return session.folder

    def _open_session_folder(self, session: AgentSession) -> None:
        target = self._session_target(session)
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))
        self.logger.info("打开会话目录 %s", _clip(target, 200))

    def _copy_session_path(self, session: AgentSession) -> None:
        target = self._session_target(session)
        QGuiApplication.clipboard().setText(target)
        self.logger.info("复制会话路径 %s", _clip(target, 200))

    def _open_session_view(self, session: AgentSession) -> None:
        key = f"{session.path}|{int(session.updated_at.timestamp())}"
        transcript = self._session_transcript_cache.get(key)
        if transcript is None:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                transcript = parse_session_transcript(session)
            except Exception as exc:  # pragma: no cover - defensive
                self.logger.warning(
                    "解析会话记录失败 %s：%s", _clip(session.path, 200), exc
                )
                transcript = SessionTranscript(
                    session=session, note=f"解析会话记录失败：{exc}"
                )
            finally:
                QApplication.restoreOverrideCursor()
            self._session_transcript_cache[key] = transcript
            while len(self._session_transcript_cache) > 6:
                oldest = next(iter(self._session_transcript_cache))
                self._session_transcript_cache.pop(oldest, None)

        self._session_detail_session = session
        self._session_transcript = transcript
        self._detail_agent.setText(session.agent_label)
        self._detail_agent.setProperty("agent", session.agent)
        _repolish(self._detail_agent)
        self._detail_title.set_full_text(session.display_title)
        updated = session.updated_at.astimezone().strftime("%Y-%m-%d %H:%M")
        self._detail_meta.set_full_text(
            f"{session.project} · {session.project_path or session.folder} "
            f"· 更新于 {updated}"
        )

        self._transcript_hint_timer.stop()
        self._transcript_search.blockSignals(True)
        self._transcript_search.clear()
        self._transcript_search.blockSignals(False)
        self._transcript_search.setEnabled(bool(transcript.turns))
        self._render_transcript(transcript)
        self._session_view_stack.setCurrentIndex(1)
        self._transcript_scroll.verticalScrollBar().setValue(0)
        self.logger.info(
            "查看会话记录 %s（%d 轮 / %d 项）",
            _clip(session.display_title, 80),
            transcript.total_turns,
            transcript.total_items,
        )

    def _close_session_view(self) -> None:
        if self._session_view_stack.currentIndex() != 1:
            return
        self._session_view_stack.setCurrentIndex(0)
        self._session_detail_session = None
        self._session_transcript = None
        self._transcript_hint_timer.stop()

    def _clear_transcript_views(self) -> None:
        while self._transcript_layout.count():
            entry = self._transcript_layout.takeAt(0)
            widget = entry.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._turn_views = []

    def _render_transcript(self, transcript: SessionTranscript) -> None:
        self._clear_transcript_views()
        if not transcript.turns:
            box = QWidget(self._transcript_host)
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(24, 66, 24, 40)
            box_layout.setSpacing(8)
            empty = QLabel(
                transcript.note or "该会话没有可展示的对话内容。", box
            )
            empty.setObjectName("sessionEmptyText")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            box_layout.addStretch(1)
            box_layout.addWidget(empty)
            box_layout.addStretch(2)
            self._transcript_layout.addWidget(box)
        else:
            last = len(transcript.turns) - 1
            for index, turn in enumerate(transcript.turns):
                view = SessionTurnView(
                    turn,
                    default_expanded=index == last,
                    parent=self._transcript_host,
                )
                self._transcript_layout.addWidget(view)
                self._turn_views.append(view)
            self._transcript_layout.addStretch(1)

        parts = [
            f"{len(transcript.turns)} 轮",
            f"{transcript.total_items} 项内容",
        ]
        if transcript.total_turns > len(transcript.turns):
            parts.append(f"共 {transcript.total_turns} 轮")
        if transcript.note and transcript.turns:
            parts.append(transcript.note)
        self._transcript_base_hint = " · ".join(parts)
        self._transcript_hint.setText(self._transcript_base_hint)
        self._rebuild_outline()
        has_turns = bool(transcript.turns)
        self._detail_copy_button.setEnabled(has_turns)
        self._detail_export_button.setEnabled(has_turns)

    def _apply_transcript_search(self, text: str) -> None:
        query = text.strip()
        self._transcript_hint_timer.stop()
        matched = 0
        for view in self._turn_views:
            view.set_search(query)
            if query and not view.isHidden():
                matched += 1
        if query:
            self._transcript_hint.setText(
                f"匹配 {matched} / {len(self._turn_views)} 轮"
            )
        else:
            self._transcript_hint.setText(self._transcript_base_hint)

    def _rebuild_outline(self) -> None:
        self._outline_menu.clear()
        if not self._turn_views:
            action = self._outline_menu.addAction("（无内容）")
            action.setEnabled(False)
            self._outline_button.setEnabled(False)
            return
        self._outline_button.setEnabled(True)
        for index, view in enumerate(self._turn_views):
            label = f"{view.turn.index}. {_clip(view.turn.preview, 42)}"
            action = self._outline_menu.addAction(label)
            action.triggered.connect(
                lambda checked=False, i=index: self._scroll_to_turn(i)
            )

    def _scroll_to_turn(self, index: int) -> None:
        if not 0 <= index < len(self._turn_views):
            return
        view = self._turn_views[index]
        view.setVisible(True)
        view.set_expanded(True)
        self._transcript_scroll.ensureWidgetVisible(view, 0, 12)

    def _flash_transcript_hint(self, text: str) -> None:
        self._transcript_hint.setText(text)
        self._transcript_hint_timer.start()

    def _restore_transcript_hint(self) -> None:
        if self._session_transcript is not None:
            self._transcript_hint.setText(self._transcript_base_hint)

    def _copy_transcript_markdown(self) -> None:
        transcript = self._session_transcript
        if transcript is None:
            return
        text = transcript_to_markdown(transcript)
        QGuiApplication.clipboard().setText(text)
        self.logger.info(
            "复制会话 Markdown %s（%d 字符）",
            _clip(transcript.session.display_title, 80),
            len(text),
        )
        self._flash_transcript_hint(f"已复制 Markdown · {len(text)} 字符")

    def _export_transcript_markdown(self) -> None:
        transcript = self._session_transcript
        if transcript is None:
            return
        safe_name = re.sub(
            r'[\\/:*?"<>|]+', "-", transcript.session.display_title
        ).strip(" .")[:60]
        safe_name = safe_name or transcript.session.session_id
        target = Path.home() / "Downloads" / f"{safe_name}.md"
        path, _selected = QFileDialog.getSaveFileName(
            self, "导出会话记录", str(target), "Markdown (*.md)"
        )
        if not path:
            return
        try:
            Path(path).write_text(
                transcript_to_markdown(transcript), encoding="utf-8"
            )
        except OSError as exc:
            self.logger.warning("导出会话失败 %s：%s", _clip(path, 200), exc)
            self._flash_transcript_hint(f"导出失败：{exc}")
            return
        self.logger.info("导出会话 Markdown %s", _clip(path, 200))
        self._flash_transcript_hint(f"已导出：{_clip(path, 90)}")

    def _open_detail_folder(self) -> None:
        if self._session_detail_session is not None:
            self._open_session_folder(self._session_detail_session)

    # ---------- actions ----------

    def copy_agent_instructions(self) -> None:
        text = build_agent_instructions(self.config.port, self.config.token)
        QGuiApplication.clipboard().setText(text)
        self.logger.info(
            "已复制 Agent 接入指令：端口=%d 鉴权=%s 字数=%d",
            self.config.port,
            "开启" if self.config.auth_enabled else "未开启",
            len(text),
        )
        self.copy_button.setText("已复制接入指令")
        self.copy_button.setIcon(_paint_icon("check", QColor("#FFFFFF"), 16))
        self.copy_button.setProperty("copied", True)
        _repolish(self.copy_button)
        self.copy_button.setToolTip("接入指令已复制，直接粘贴给 Agent 即可")
        self._copy_timer.start()

    def _reset_copy_button(self) -> None:
        self.copy_button.setText("复制 Agent 接入指令")
        self.copy_button.setIcon(_paint_icon("copy", QColor("#FFFFFF"), 16))
        self.copy_button.setProperty("copied", False)
        _repolish(self.copy_button)
        self.copy_button.setToolTip(
            "复制接入指令，粘贴给 Agent 后即可每轮自动推送"
        )

    def open_settings(self) -> None:
        if self._shutting_down:
            return
        from .settings import SettingsDialog

        dialog = SettingsDialog(
            self.config,
            self._config_path,
            self.logger,
            parent=self,
        )
        if dialog.exec() and dialog.result_config is not None:
            self.logger.info("设置已保存")
            self.settings_saved.emit(dialog.result_config)

    def apply_config(self, config: AppConfig) -> None:
        self.config = config
        self._endpoint_label.setText(f"127.0.0.1:{config.port}")
        self._status_address.setText(f"127.0.0.1:{config.port} · 运行中")
        self._auth_label.setText(
            "X-Token 已开启" if config.auth_enabled else "X-Token 未开启"
        )
        self._auth_label.setProperty(
            "auth", "on" if config.auth_enabled else "off"
        )
        _repolish(self._auth_label)
        self._hotkey_label.setText(
            f"快捷键 {config.hotkey}" if config.hotkey else "未设置全局快捷键"
        )
        self._signature = None
        self._rebuild_cards()
        self._update_session_summary()
        self._refresh_recent_projects()
        self._sync_launcher_start()
        self._toolchain_page.apply_config(config.toolchain)
        if self._page == "stats":
            self.refresh_stats()
        elif self._page == "sessions":
            self._rebuild_session_cards()

    def show_center(self, animate: bool = False) -> None:
        if self._shutting_down:
            return
        self.refresh_items(self._store.snapshot())
        was_visible = self.isVisible()
        if self.isMinimized():
            self.showNormal()
        self._center_if_needed()
        if not was_visible:
            self.setWindowOpacity(0.0 if animate else 1.0)
        self.show()
        self.raise_()
        self.activateWindow()
        if animate and not was_visible:
            self._play_show_animation()
        elif not animate:
            self.setWindowOpacity(1.0)
        self.center_shown.emit()
        self.logger.info("打开通知中心")

    def _play_show_animation(self) -> None:
        if self._show_animation is not None:
            self._show_animation.stop()
        target = self.pos()
        self.move(target + QPoint(0, 16))

        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(260)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)

        rise = QPropertyAnimation(self, b"pos", self)
        rise.setDuration(260)
        rise.setEasingCurve(QEasingCurve.Type.OutCubic)
        rise.setStartValue(target + QPoint(0, 16))
        rise.setEndValue(target)

        group = QParallelAnimationGroup(self)
        group.addAnimation(fade)
        group.addAnimation(rise)
        group.finished.connect(lambda: self.setWindowOpacity(1.0))
        self._show_animation = group
        group.start()

    def hide_center(self) -> None:
        if self._show_animation is not None:
            self._show_animation.stop()
            self._show_animation = None
            self.setWindowOpacity(1.0)
        if self.isVisible():
            self.hide()
            self.logger.info("通知中心已隐藏到托盘")

    def _center_if_needed(self) -> None:
        if self._placed:
            return
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            self.move(
                available.center().x() - self.width() // 2,
                available.center().y() - self.height() // 2,
            )
        self._placed = True

    def start_onboarding(self) -> OnboardingOverlay | None:
        if self._shutting_down or self._onboarding is not None:
            return self._onboarding
        if not self.isVisible():
            return None
        overlay = OnboardingOverlay(
            self._root,
            hotkey=self.config.hotkey,
            animate=motion_enabled(),
        )
        overlay.setGeometry(self._root.rect())
        overlay.finished.connect(self._finish_onboarding)
        overlay.show()
        overlay.raise_()
        self._onboarding = overlay
        self.logger.info("显示首次启动介绍")
        return overlay

    def _finish_onboarding(self) -> None:
        overlay = self._onboarding
        self._onboarding = None
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()
        self.logger.info("首次启动介绍已完成")
        self.onboarding_finished.emit()

    def toggle_maximize(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _sync_window_state(self) -> None:
        maximized = self.isMaximized()
        self._root.setProperty("maximized", maximized)
        _repolish(self._root)
        margin = 0 if maximized else 12
        self._central.layout().setContentsMargins(margin, margin, margin, margin)
        self._shadow.setEnabled(not maximized)
        self._grip.setVisible(not maximized)
        self._maximize_button.setText("❐" if maximized else "□")
        self._maximize_button.setToolTip("还原窗口" if maximized else "最大化")

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._copy_timer.stop()
        self._search_timer.stop()
        if self._onboarding is not None:
            self._onboarding.hide()
            self._onboarding.deleteLater()
            self._onboarding = None
        self.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_grip"):
            self._grip.move(
                self._root.width() - self._grip.width(),
                self._root.height() - self._grip.height(),
            )
            self._grip.raise_()
        if self._onboarding is not None:
            self._onboarding.setGeometry(self._root.rect())
            self._onboarding.raise_()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "_root"):
            self._sync_window_state()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._sync_window_state()

    def closeEvent(self, event) -> None:
        if self._shutting_down:
            event.accept()
            return
        event.ignore()
        self.hide()
        self.logger.info("通知中心已关闭到托盘")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide_center()
            event.accept()
            return
        super().keyPressEvent(event)


_STYLESHEET = """
QWidget#centralHost {
    background: transparent;
}
QFrame#windowRoot {
    background-color: #FFFFFF;
    border: 1px solid #DDE1E8;
    border-radius: 13px;
}
QFrame#windowRoot[maximized="true"] {
    border-radius: 0px;
    border: none;
}
QFrame#sidebar {
    background-color: #F5F6F8;
    border-top-left-radius: 12px;
    border-bottom-left-radius: 12px;
    border-right: 1px solid #E9EBEF;
}
QFrame#windowRoot[maximized="true"] QFrame#sidebar {
    border-radius: 0px;
}
QWidget#bodyPanel, QWidget#bodyHost, QFrame#contentPanel, QWidget#segmentHost,
QWidget#listHost, QStackedWidget#pageStack {
    background: transparent;
}
QLabel {
    color: #1F2329;
    background: transparent;
}
QLabel#brandName {
    font-size: 16px;
    font-weight: 700;
    color: #161A20;
}
QLabel#brandTagline {
    font-size: 10px;
    color: #8A919D;
}
QLabel#sectionLabel {
    font-size: 10px;
    font-weight: 600;
    color: #9AA1AC;
    padding-left: 10px;
}
QPushButton#navButton {
    background: transparent;
    border: none;
    border-radius: 9px;
    color: #4B5563;
    font-size: 13px;
    text-align: left;
    padding: 0px 10px;
}
QPushButton#navButton:hover {
    background-color: #ECEEF2;
}
QPushButton#navButton:checked {
    background-color: #E7EEFB;
    color: #2F6FF0;
    font-weight: 600;
}
QFrame#serviceCard {
    background-color: #FFFFFF;
    border: 1px solid #E5E8EE;
    border-radius: 12px;
}
QLabel#serviceDot {
    color: #23B26D;
    font-size: 9px;
}
QLabel#serviceTitle {
    font-size: 12px;
    font-weight: 600;
    color: #323A45;
}
QLabel#serviceEndpoint {
    font-family: Consolas, "Cascadia Mono";
    font-size: 11px;
    color: #667085;
    padding-left: 13px;
}
QLabel#serviceAuth {
    font-size: 10px;
    padding-left: 13px;
}
QLabel#serviceAuth[auth="on"] {
    color: #15885C;
}
QLabel#serviceAuth[auth="off"] {
    color: #B7791F;
}
QLabel#serviceHint {
    font-size: 9px;
    color: #9AA1AC;
    padding-left: 13px;
}
QPushButton#sideButton, QPushButton#quitButton, QPushButton#toolButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #5A6472;
    font-size: 12px;
    text-align: left;
    padding: 0px 10px;
}
QPushButton#sideButton:hover, QPushButton#toolButton:hover {
    background-color: #ECEEF2;
}
QPushButton#quitButton:hover {
    background-color: #FBEBEB;
    color: #C24141;
}
QPushButton#toolButton {
    border: 1px solid #E3E7ED;
    background-color: #FFFFFF;
    text-align: center;
}
QFrame#topBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #ECEEF2;
    border-top-right-radius: 12px;
}
QFrame#windowRoot[maximized="true"] QFrame#topBar {
    border-radius: 0px;
}
QLabel#topBarTitle {
    font-size: 16px;
    font-weight: 650;
    color: #161A20;
}
QFrame#statusPill {
    background-color: #F4F6F8;
    border: 1px solid #EDF0F3;
    border-radius: 9px;
}
QLabel#onlineDot {
    color: #23B26D;
    font-size: 8px;
}
QLabel#statusPillText {
    font-size: 10px;
    color: #6B7280;
}
QPushButton#copyButton {
    background-color: #2F6FF0;
    border: none;
    border-radius: 9px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
    padding: 0px 12px;
}
QPushButton#copyButton:hover {
    background-color: #1F5FDF;
}
QPushButton#copyButton:pressed {
    background-color: #1A53C7;
}
QPushButton#copyButton[copied="true"] {
    background-color: #179A62;
}
QFrame#topDivider {
    background-color: #E9ECF0;
    border: none;
    max-width: 1px;
}
QToolButton#winButton, QToolButton#closeButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    color: #5A6472;
    font-size: 13px;
}
QToolButton#winButton:hover {
    background-color: #F0F2F5;
}
QToolButton#closeButton:hover {
    background-color: #E81123;
    color: #FFFFFF;
}
QLabel#pageTitle {
    font-size: 20px;
    font-weight: 700;
    color: #161A20;
}
QLabel#pageSubtitle {
    font-size: 11px;
    color: #8A919D;
}
QLabel#livePill {
    background-color: #E9F8F1;
    border-radius: 9px;
    color: #15885C;
    font-size: 10px;
    padding: 4px 9px;
}
QLabel#totalLabel {
    font-size: 11px;
    color: #9AA1AC;
    padding-left: 2px;
}
QFrame#segmentBar {
    background-color: #F2F3F7;
    border-radius: 10px;
}
QPushButton#segmentButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    color: #6B7280;
    font-size: 12px;
    padding: 0px 10px;
}
QPushButton#segmentButton:hover {
    color: #323A45;
}
QPushButton#segmentButton:checked {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EC;
    color: #1F2329;
    font-weight: 600;
}
QFrame#searchHost {
    background-color: #F5F6FA;
    border: 1px solid #E8EBF0;
    border-radius: 9px;
}
QLineEdit#searchInput {
    background: transparent;
    border: none;
    color: #323A45;
    font-size: 11px;
    selection-background-color: #2F6FF0;
    selection-color: #FFFFFF;
}
QLineEdit#searchInput:focus {
    color: #161A20;
}
QScrollArea#listArea, QWidget#listViewport {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px 0px;
}
QScrollBar::handle:vertical {
    background-color: #D6DAE2;
    border-radius: 3px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background-color: #B9C0CC;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}
QFrame#notificationCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 14px;
}
QFrame#notificationCard:hover {
    border-color: #C7D4EA;
}
QFrame#notificationCard[latest="true"] {
    background-color: #F8FBFF;
    border-color: #BBD1F5;
}
QFrame#notificationCard[priority="critical"] {
    border-color: #F0B4B4;
}
QLabel#cardTitle {
    font-size: 13px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#cardSummary {
    font-size: 11px;
    color: #6B7280;
}
QLabel#cardTime {
    font-size: 10px;
    color: #9AA1AC;
}
QLabel#statusChip {
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#statusChip[status="succeeded"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#statusChip[status="failed"] {
    background-color: #FDECEC;
    color: #C24141;
}
QLabel#statusChip[status="canceled"] {
    background-color: #FDF4E5;
    color: #A16207;
}
QLabel#statusChip[status="running"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#priorityChip {
    border-radius: 8px;
    padding: 1px 8px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#priorityChip[priority="high"] {
    background-color: #FFF4E6;
    color: #B45309;
}
QLabel#priorityChip[priority="critical"] {
    background-color: #FDECEC;
    color: #C24141;
}
QLabel#durationChip, QLabel#sourceChip, QLabel#repeatChip, QLabel#ackChip {
    background-color: #F4F5F8;
    border-radius: 7px;
    color: #6B7280;
    font-size: 10px;
    padding: 1px 7px;
}
QLabel#ackChip[state="pending"] {
    background-color: #FFF4E6;
    color: #B45309;
}
QLabel#ackChip[state="done"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#cardError {
    font-size: 10px;
    color: #D35A5A;
}
QWidget#cardProgress {
    background: transparent;
}
QLabel#cardProgressLabel {
    font-size: 10px;
    color: #667085;
}
QProgressBar#cardProgressBar {
    background-color: #EEF1F6;
    border: none;
    border-radius: 3px;
}
QProgressBar#cardProgressBar::chunk {
    background-color: #5B8DEF;
    border-radius: 3px;
}
QToolButton#cardAction {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 8px;
}
QToolButton#cardAction:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
}
QToolButton#cardAction:pressed {
    background-color: #DFEAFE;
}
QPushButton#cardActionText {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 7px;
    color: #4B5563;
    font-size: 10px;
    padding: 0px 10px;
}
QPushButton#cardActionText:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
    color: #2F6FF0;
}
QToolButton#cardSnooze {
    background-color: #FFFFFF;
    border: 1px solid #E3E7ED;
    border-radius: 7px;
    color: #5A6472;
    font-size: 10px;
    padding: 0px 9px;
}
QToolButton#cardSnooze:hover {
    background-color: #F2F5FA;
}
QToolButton#cardSnooze::menu-indicator {
    image: none;
    width: 0px;
}
QPushButton#cardAck {
    background-color: #2F6FF0;
    border: none;
    border-radius: 7px;
    color: #FFFFFF;
    font-size: 10px;
    font-weight: 600;
    padding: 0px 12px;
}
QPushButton#cardAck:hover {
    background-color: #1F5FDF;
}
QLabel#emptyTitle {
    font-size: 16px;
    font-weight: 650;
    color: #323A45;
}
QLabel#emptyText {
    font-size: 11px;
    color: #8A919D;
}
QLabel#emptyHint {
    font-size: 10px;
    color: #A6ADB8;
}
QPushButton#emptyAction {
    background-color: #2F6FF0;
    border: none;
    border-radius: 9px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
    padding: 0px 16px;
}
QPushButton#emptyAction:hover {
    background-color: #1F5FDF;
}
QPushButton#emptyAction:pressed {
    background-color: #1A53C7;
}
QLabel#listHint {
    font-size: 10px;
    color: #9AA1AC;
    padding: 10px;
}
QFrame#statCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QLabel#statValue {
    font-size: 22px;
    font-weight: 700;
    color: #161A20;
}
QLabel#statValue[accent="success"] {
    color: #15885C;
}
QLabel#statValue[accent="awaiting"] {
    color: #B45309;
}
QLabel#statCaption {
    font-size: 10px;
    color: #8A919D;
}
QFrame#statsCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QLabel#statsTitle {
    font-size: 12px;
    font-weight: 600;
    color: #323A45;
}
QLabel#statsHint {
    font-size: 9px;
    color: #9AA1AC;
}
QLabel#statsChip {
    border-radius: 8px;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 10px;
}
QLabel#statsChip[status="succeeded"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#statsChip[status="failed"] {
    background-color: #FDECEC;
    color: #C24141;
}
QLabel#statsChip[status="canceled"] {
    background-color: #FDF4E5;
    color: #A16207;
}
QLabel#statsChip[status="running"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#sessionSummary {
    font-size: 11px;
    color: #8A919D;
}
QLabel#sessionGroupTitle {
    font-size: 12px;
    font-weight: 650;
    color: #323A45;
}
QLabel#sessionGroupCount {
    font-size: 10px;
    color: #9AA1AC;
}
QFrame#sessionCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QFrame#sessionCard:hover {
    border-color: #C7D4EA;
}
QLabel#sessionAgent {
    border-radius: 7px;
    font-size: 10px;
    font-weight: 600;
}
QLabel#sessionAgent[agent="claude"] {
    background-color: #FDF0E8;
    color: #B45309;
}
QLabel#sessionAgent[agent="qoder"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#sessionTitle {
    font-size: 12px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#sessionTime {
    font-size: 10px;
    color: #9AA1AC;
}
QLabel#sessionPath {
    font-size: 10px;
    color: #6B7280;
}
QLabel#sessionMeta {
    font-size: 10px;
    color: #9AA1AC;
}
QPushButton#sessionView {
    background-color: #2F6FF0;
    border: none;
    border-radius: 7px;
    color: #FFFFFF;
    font-size: 10px;
    font-weight: 600;
}
QPushButton#sessionView:hover {
    background-color: #1F5FDF;
}
QToolButton#sessionIcon {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 8px;
}
QToolButton#sessionIcon:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
}
QFrame#agentPickCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QFrame#agentPickCard:hover {
    border-color: #C7D4EA;
}
QFrame#agentPickCard[selected="true"] {
    border-color: #2F6FF0;
    background-color: #F7FAFF;
}
QFrame#agentPickCard[installed="false"] {
    background-color: #FAFBFC;
}
QLabel#agentPickIcon {
    background-color: #EEF4FF;
    border-radius: 9px;
}
QLabel#agentPickName {
    font-size: 13px;
    font-weight: 650;
    color: #1F2329;
}
QLabel#agentPickStatus {
    border-radius: 7px;
    font-size: 9px;
    font-weight: 600;
    padding: 0px 6px;
}
QLabel#agentPickStatus[installed="true"] {
    background-color: #E9F8F0;
    color: #179A62;
}
QLabel#agentPickStatus[installed="false"] {
    background-color: #F1F2F5;
    color: #8A919D;
}
QLabel#agentPickKind {
    font-size: 9px;
    color: #9AA1AC;
}
QLabel#agentPickHint {
    font-size: 10px;
    color: #6B7280;
}
QLabel#launchSection {
    font-size: 12px;
    font-weight: 650;
    color: #323A45;
}
QLabel#launchSectionHint {
    font-size: 10px;
    color: #9AA1AC;
}
QFrame#launchPanel {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QLabel#launchFieldLabel {
    font-size: 11px;
    color: #6B7280;
}
QLineEdit#launchProject, QComboBox#launchRecent, QPlainTextEdit#launchPrompt {
    background-color: #F9FAFC;
    border: 1px solid #E3E7ED;
    border-radius: 8px;
    color: #1F2329;
    font-size: 12px;
}
QLineEdit#launchProject:focus, QPlainTextEdit#launchPrompt:focus {
    border-color: #9DBBFF;
    background-color: #FFFFFF;
}
QLineEdit#launchProject {
    padding: 0px 10px;
}
QComboBox#launchRecent {
    padding: 0px 8px;
}
QComboBox#launchRecent::drop-down {
    border: none;
    width: 22px;
}
QComboBox#launchRecent QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E3E7ED;
    selection-background-color: #EAF2FF;
    selection-color: #1F2329;
}
QPlainTextEdit#launchPrompt {
    padding: 8px;
}
QPushButton#launchButton {
    background-color: #2F6FF0;
    border: none;
    border-radius: 9px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#launchButton:hover {
    background-color: #1F5FDF;
}
QPushButton#launchButton:disabled {
    background-color: #C9D6EA;
    color: #F3F5F8;
}
QLabel#launchStatus {
    font-size: 10px;
    color: #6B7280;
}
QLabel#launchStatus[state="error"] {
    color: #C24141;
}
QFrame#launchRecord {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 10px;
}
QLabel#launchRecordTitle {
    font-size: 11px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#launchRecordMeta {
    font-size: 10px;
    color: #9AA1AC;
}
QPushButton#launchFocus {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 7px;
    color: #4B5563;
    font-size: 10px;
    padding: 0px 10px;
}
QPushButton#launchFocus:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
    color: #2F6FF0;
}
QPushButton#launchFocus:disabled {
    color: #B4BAC4;
}
QLabel#launchRecordEmpty {
    font-size: 10px;
    color: #9AA1AC;
    padding: 4px 2px;
}
QLabel#detailTitle {
    font-size: 15px;
    font-weight: 650;
    color: #161A20;
}
QLabel#detailMeta {
    font-size: 10px;
    color: #8A919D;
}
QToolButton#detailIcon {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 8px;
}
QToolButton#detailIcon:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
}
QToolButton#detailMenu {
    background-color: #FFFFFF;
    border: 1px solid #E3E7ED;
    border-radius: 7px;
    color: #4B5563;
    font-size: 10px;
}
QToolButton#detailMenu:hover {
    background-color: #F2F5FA;
}
QToolButton#detailMenu::menu-indicator {
    image: none;
    width: 0px;
}
QPushButton#detailAction {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 7px;
    color: #4B5563;
    font-size: 10px;
}
QPushButton#detailAction:hover {
    background-color: #EAF1FF;
    border-color: #C9DBFF;
    color: #2F6FF0;
}
QPushButton#detailAction:disabled {
    color: #B4BAC4;
}
QFrame#turnCard {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QLabel#turnIndex {
    background-color: #EAF2FF;
    border-radius: 6px;
    color: #2F6FF0;
    font-size: 10px;
    font-weight: 600;
}
QLabel#turnPrompt {
    font-size: 12px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#turnMeta {
    font-size: 10px;
    color: #9AA1AC;
}
QLabel#turnArrow {
    color: #98A0AC;
    font-size: 12px;
}
QWidget#turnBody {
    background: transparent;
}
QLabel#turnPromptFull {
    background-color: #F5F7FB;
    border-radius: 8px;
    padding: 8px 10px;
    color: #323A45;
    font-size: 11px;
}
QLabel#turnText {
    color: #2B313B;
    font-size: 11px;
}
QLabel#turnImage {
    color: #8A919D;
    font-size: 10px;
    font-style: italic;
}
QLabel#turnMore {
    color: #9AA1AC;
    font-size: 10px;
}
QToolButton#activityToggle {
    background: transparent;
    border: none;
    color: #5B6B84;
    font-size: 10px;
    text-align: left;
    padding: 2px 0px;
}
QToolButton#activityToggle:hover {
    color: #2F6FF0;
}
QWidget#activityHost {
    background: transparent;
}
QFrame#activityRow {
    background-color: #F8F9FB;
    border: 1px solid #EDEFF3;
    border-radius: 8px;
}
QFrame#activityRow[error="true"] {
    background-color: #FEF6F6;
    border-color: #F3D6D6;
}
QLabel#activityName {
    background-color: #EEF2F8;
    border-radius: 5px;
    padding: 1px 6px;
    color: #5A6472;
    font-size: 9px;
    font-weight: 600;
}
QLabel#activityName[kind="tool"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#activityName[kind="result"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#activityName[kind="thinking"] {
    background-color: #F1EEFA;
    color: #6B4FBB;
}
QLabel#activityError {
    background-color: #FDECEC;
    border-radius: 5px;
    padding: 1px 6px;
    color: #C24141;
    font-size: 9px;
    font-weight: 600;
}
QLabel#activityClipped {
    color: #9AA1AC;
    font-size: 9px;
}
QLabel#activityText {
    font-family: Consolas, "Cascadia Mono";
    color: #3A4350;
    font-size: 10px;
}
QLabel#activityThinking {
    color: #7A8091;
    font-size: 10px;
    font-style: italic;
}
QLabel#sessionEmptyTitle {
    font-size: 16px;
    font-weight: 650;
    color: #323A45;
}
QLabel#sessionEmptyText {
    font-size: 11px;
    color: #8A919D;
}
"""
