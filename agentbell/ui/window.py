from __future__ import annotations

import logging
from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
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
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import AppConfig
from ..integration import build_agent_instructions
from ..models import Notification, safe_http_url
from ..store import NotificationStore
from .icons import make_app_icon

SIDEBAR_WIDTH = 232
DEFAULT_SIZE = QSize(1120, 760)
MINIMUM_SIZE = QSize(900, 580)
MAX_VISIBLE_CARDS = 100

FILTERS: tuple[tuple[str, str, str], ...] = (
    ("all", "全部", "全部通知"),
    ("succeeded", "成功", "已完成"),
    ("failed", "失败", "失败"),
    ("canceled", "已取消", "已取消"),
)

_STATUS_TILE_COLORS = {
    "succeeded": ("#E8F8F0", "#C9EEDC", "#15885C"),
    "failed": ("#FDECEC", "#F6D3D3", "#D04646"),
    "canceled": ("#FDF4E5", "#F5E2BF", "#B7791F"),
}


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

    def __init__(self, has_any_records: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 74, 24, 48)
        layout.setSpacing(0)
        layout.addStretch(1)

        icon = QLabel(self)
        icon.setPixmap(make_app_icon().pixmap(64, 64))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(18)
        title = QLabel(
            "没有符合条件的通知" if has_any_records else "还没有通知记录", self
        )
        title.setObjectName("emptyTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        layout.addSpacing(8)
        if has_any_records:
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
        self.action = QPushButton(
            "查看全部通知" if has_any_records else "复制 Agent 接入指令", self
        )
        self.action.setObjectName("emptyAction")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.setFixedHeight(36)
        self.action.setMinimumWidth(170)
        if has_any_records:
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

    def __init__(
        self,
        notification: Notification,
        logger: logging.Logger,
        latest: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.notification = notification
        self._logger = logger
        self._link = safe_http_url(notification.link)
        self.setObjectName("notificationCard")
        self.setProperty("latest", latest)
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

        chip = QLabel(notification.status_label, self)
        chip.setObjectName("statusChip")
        chip.setProperty("status", notification.status)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setFixedHeight(20)
        title_row.addWidget(chip, 0, Qt.AlignmentFlag.AlignVCenter)

        time_label = QLabel(format_received_at(notification.received_at), self)
        time_label.setObjectName("cardTime")
        title_row.addWidget(time_label, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(title_row)

        summary_text = notification.summary
        if not summary_text:
            if notification.status == "failed":
                summary_text = notification.error or "执行失败，未提供更多信息。"
            elif notification.status == "canceled":
                summary_text = "本轮任务已取消。"
            else:
                summary_text = "本轮任务已完成。"
        summary = ElidedLabel(summary_text, self)
        summary.setObjectName("cardSummary")
        body.addWidget(summary)

        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0, 0, 0, 0)
        meta_row.setSpacing(8)

        if notification.duration:
            duration = QLabel(f"耗时 {_clip(notification.duration, 24)}", self)
            duration.setObjectName("durationChip")
            duration.setAlignment(Qt.AlignmentFlag.AlignCenter)
            duration.setFixedHeight(20)
            meta_row.addWidget(duration, 0, Qt.AlignmentFlag.AlignVCenter)

        if notification.status == "failed" and notification.error and notification.summary:
            error = ElidedLabel(f"错误：{notification.error}", self)
            error.setObjectName("cardError")
            meta_row.addWidget(error, 1)
        else:
            meta_row.addStretch(1)
        body.addLayout(meta_row)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        actions.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.view_button: QToolButton | None = None
        if self._link:
            self.view_button = self._make_action(
                "external", "#4F647F", "打开通知中的链接"
            )
            self.view_button.setAccessibleName("打开链接")
            self.view_button.clicked.connect(self._open_link)
            actions.addWidget(self.view_button)

        self.replay_button = self._make_action(
            "bell", "#4F647F", "再次弹出这条提醒"
        )
        self.replay_button.setAccessibleName("再次提醒")
        self.replay_button.clicked.connect(
            lambda: self.replay_requested.emit(self.notification)
        )
        actions.addWidget(self.replay_button)
        root.addLayout(actions)

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


class NotificationWindow(QMainWindow):
    replay_requested = Signal(object)
    quit_requested = Signal()

    def __init__(
        self,
        config: AppConfig,
        store: NotificationStore,
        logger: logging.Logger,
    ) -> None:
        super().__init__()
        self.config = config
        self._store = store
        self.logger = logger
        self._items: list[Notification] = []
        self._signature: tuple[tuple[str, str], ...] | None = None
        self._filter = "all"
        self._shutting_down = False
        self._placed = False
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
        content_layout.addWidget(self._build_body(content), 1)

        self._grip = QSizeGrip(self._root)
        self._grip.setObjectName("sizeGrip")
        self._grip.setFixedSize(16, 16)
        self._grip.raise_()

        self._copy_timer = QTimer(self)
        self._copy_timer.setSingleShot(True)
        self._copy_timer.setInterval(2200)
        self._copy_timer.timeout.connect(self._reset_copy_button)

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

        layout.addSpacing(24)
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

        endpoint = QLabel(f"127.0.0.1:{self.config.port}", service)
        endpoint.setObjectName("serviceEndpoint")
        service_layout.addWidget(endpoint)

        auth = QLabel(
            "X-Token 已开启" if self.config.auth_enabled else "X-Token 未开启",
            service,
        )
        auth.setObjectName("serviceAuth")
        auth.setProperty("auth", "on" if self.config.auth_enabled else "off")
        service_layout.addWidget(auth)

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
        address = QLabel(f"127.0.0.1:{self.config.port} · 运行中", pill)
        address.setObjectName("statusPillText")
        pill_layout.addWidget(address)
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

    def _build_body(self, parent: QWidget) -> QWidget:
        body = QWidget(parent)
        body.setObjectName("bodyPanel")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(28, 22, 28, 24)
        layout.setSpacing(0)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(12)

        heading_text = QVBoxLayout()
        heading_text.setContentsMargins(0, 0, 0, 0)
        heading_text.setSpacing(4)
        title = QLabel("通知记录", body)
        title.setObjectName("pageTitle")
        subtitle = QLabel("Agent 每完成一轮任务，都会在这里留下一条记录。", body)
        subtitle.setObjectName("pageSubtitle")
        heading_text.addWidget(title)
        heading_text.addWidget(subtitle)
        heading.addLayout(heading_text)
        heading.addStretch(1)

        live = QLabel("●  实时更新", body)
        live.setObjectName("livePill")
        heading.addWidget(live, 0, Qt.AlignmentFlag.AlignVCenter)
        self._total_label = QLabel("共 0 条", body)
        self._total_label.setObjectName("totalLabel")
        heading.addWidget(self._total_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(heading)

        layout.addSpacing(18)

        segment_host = QWidget(body)
        segment_host.setObjectName("segmentHost")
        segment_row = QHBoxLayout(segment_host)
        segment_row.setContentsMargins(0, 0, 0, 0)
        segment_row.setSpacing(10)

        self._segment_bar = QFrame(segment_host)
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
            button.setMinimumWidth(66)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda checked=False, value=key: self.set_filter(value)
            )
            self._segment_group.addButton(button)
            self._segment_buttons[key] = button
            segment_layout.addWidget(button)
        segment_row.addWidget(self._segment_bar)
        segment_row.addStretch(1)
        layout.addWidget(segment_host)

        layout.addSpacing(14)

        self._scroll = QScrollArea(body)
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

        return body

    # ---------- data / filters ----------

    def refresh_items(self, items: list[Notification]) -> None:
        self._items = list(items)
        signature = tuple((item.id, item.status) for item in self._items)
        if signature == self._signature:
            return
        self._signature = signature
        self._update_counts()
        self._rebuild_cards()

    def set_filter(self, key: str) -> None:
        if key not in FILTERS_LABELS:
            return
        changed = key != self._filter
        self._filter = key
        self._update_filter_controls()
        if changed:
            self._rebuild_cards()

    def _update_filter_controls(self) -> None:
        for key, button in self._nav_buttons.items():
            button.setChecked(key == self._filter)
        for key, button in self._segment_buttons.items():
            button.setChecked(key == self._filter)

    def _update_counts(self) -> None:
        counts = {"all": len(self._items), "succeeded": 0, "failed": 0, "canceled": 0}
        for item in self._items:
            if item.status in counts:
                counts[item.status] += 1
        for key, label, _ in FILTERS:
            if key in self._segment_buttons:
                self._segment_buttons[key].setText(f"{label} {counts[key]}")
            if key in self._nav_buttons:
                self._nav_buttons[key].setToolTip(f"共 {counts[key]} 条通知")
        self._total_label.setText(f"共 {len(self._items)} 条")

    def _filtered_items(self) -> list[Notification]:
        if self._filter == "all":
            return list(self._items)
        return [item for item in self._items if item.status == self._filter]

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
            empty = EmptyState(bool(self._items), self._list_host)
            empty.copy_requested.connect(self.copy_agent_instructions)
            empty.reset_filter_requested.connect(lambda: self.set_filter("all"))
            self._list_layout.addWidget(empty, 1)
        else:
            for index, notification in enumerate(filtered[:MAX_VISIBLE_CARDS]):
                card = NotificationCard(
                    notification,
                    self.logger,
                    latest=index == 0,
                    parent=self._list_host,
                )
                card.replay_requested.connect(self.replay_requested.emit)
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

    def show_center(self) -> None:
        if self._shutting_down:
            return
        self.refresh_items(self._store.snapshot())
        if self.isMinimized():
            self.showNormal()
        self._center_if_needed()
        self.show()
        self.raise_()
        self.activateWindow()
        self.logger.info("打开通知中心")

    def hide_center(self) -> None:
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
        self.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_grip"):
            self._grip.move(
                self._root.width() - self._grip.width(),
                self._root.height() - self._grip.height(),
            )
            self._grip.raise_()

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


FILTERS_LABELS = {key: sidebar for key, _, sidebar in FILTERS}


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
QWidget#bodyPanel, QFrame#contentPanel, QWidget#segmentHost, QWidget#listHost {
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
QPushButton#sideButton, QPushButton#quitButton {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: #5A6472;
    font-size: 12px;
    text-align: left;
    padding: 0px 10px;
}
QPushButton#sideButton:hover {
    background-color: #ECEEF2;
}
QPushButton#quitButton:hover {
    background-color: #FBEBEB;
    color: #C24141;
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
    padding: 0px 12px;
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
QLabel#durationChip {
    background-color: #F4F5F8;
    border-radius: 7px;
    color: #6B7280;
    font-size: 10px;
    padding: 1px 7px;
}
QLabel#cardError {
    font-size: 10px;
    color: #D35A5A;
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
"""
