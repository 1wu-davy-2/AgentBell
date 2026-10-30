from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import OverlayAreaConfig
from ..models import (
    OVERLAY_ANCHOR_LABELS,
    OVERLAY_CARD_WIDTH_DEFAULT,
    OVERLAY_CARD_WIDTH_MAX,
    OVERLAY_CARD_WIDTH_MIN,
    overlay_anchor_for_rect,
    overlay_anchor_origin,
    overlay_effective_margin,
)
from .icons import status_pixmap
from .toast import OverlayBackdrop, overlay_palette


class _GuideOverlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect()
        pen = QPen(QColor(255, 255, 255, 36), 1, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        for index in (1, 2):
            x = rect.width() * index / 3
            y = rect.height() * index / 3
            painter.drawLine(int(x), 0, int(x), rect.height())
            painter.drawLine(0, int(y), rect.width(), int(y))
        painter.end()


class OverlayAreaEditor(QDialog):
    area_saved = Signal(object)

    def __init__(
        self,
        area: OverlayAreaConfig,
        image_path: str = "",
        skin: str = "midnight",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._area = area
        self._palette = overlay_palette(skin)
        self.result_area: OverlayAreaConfig | None = None
        self._placed = False
        self._dragging = False
        self._drag_offset = QPoint()
        self._hint_update_scheduled = False

        self.setWindowTitle("调整全屏显示区域")
        self.setModal(True)
        self.setCursor(Qt.CursorShape.ArrowCursor)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._backdrop = OverlayBackdrop(image_path, self._palette, self)
        outer.addWidget(self._backdrop)

        self._guide = _GuideOverlay(self._backdrop)
        self._card = self._build_card()
        self._bar = self._build_bar()
        self._card.installEventFilter(self)
        self._apply_style()

    # ---------- construction ----------

    def _build_card(self) -> QFrame:
        palette = self._palette
        card = QFrame(self._backdrop)
        card.setObjectName("editorCard")
        card.setCursor(Qt.CursorShape.OpenHandCursor)
        card.setToolTip("按住拖动卡片")

        root = QVBoxLayout(card)
        root.setContentsMargins(18, 14, 18, 12)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        icon = QLabel(card)
        icon.setFixedSize(34, 34)
        icon.setPixmap(status_pixmap("succeeded", 34))
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        title = QLabel("通知预览 · 拖动卡片", card)
        title.setObjectName("editorCardTitle")
        title.setWordWrap(True)
        header.addWidget(title, 1)
        root.addLayout(header)

        summary = QLabel(
            "按住卡片拖到想要的位置；上方按钮可取消或保存。", card
        )
        summary.setObjectName("editorCardSummary")
        summary.setWordWrap(True)
        root.addWidget(summary)

        meta = QLabel("AgentBell · 预览内容仅用于定位", card)
        meta.setObjectName("editorCardMeta")
        root.addWidget(meta)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 2, 0, 0)
        actions.setSpacing(8)
        actions.addStretch(1)
        view = QLabel("查看", card)
        view.setObjectName("editorCardButton")
        view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        view.setFixedSize(62, 26)
        actions.addWidget(view)
        ack = QLabel("知道了", card)
        ack.setObjectName("editorCardButton")
        ack.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ack.setFixedSize(70, 26)
        actions.addWidget(ack)
        root.addLayout(actions)

        for child in card.findChildren(QWidget):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        card.setStyleSheet(
            f"""
            QFrame#editorCard {{
                background-color: {palette['card']};
                border: 1px solid {palette['border']};
                border-radius: 16px;
            }}
            QLabel {{
                background: transparent;
                color: {palette['text']};
                font-size: 12px;
            }}
            QLabel#editorCardTitle {{
                color: {palette['title']};
                font-size: 14px;
                font-weight: 600;
            }}
            QLabel#editorCardSummary {{
                color: {palette['text']};
            }}
            QLabel#editorCardMeta {{
                color: {palette['muted']};
                font-size: 11px;
            }}
            QLabel#editorCardButton {{
                background-color: {palette['button_bg']};
                border: 1px solid {palette['button_border']};
                border-radius: 7px;
                color: {palette['title']};
                font-size: 11px;
            }}
            """
        )
        return card

    def _build_bar(self) -> QFrame:
        bar = QFrame(self._backdrop)
        bar.setObjectName("editorBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)

        self._hint = QLabel("拖动卡片调整位置", bar)
        self._hint.setObjectName("editorHintLabel")
        layout.addWidget(self._hint)

        cancel = QPushButton("取消", bar)
        cancel.setObjectName("editorCancel")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setFixedSize(64, 28)
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)

        save = QPushButton("保存位置", bar)
        save.setObjectName("editorSave")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setFixedSize(86, 28)
        save.clicked.connect(self._save)
        layout.addWidget(save)
        bar.adjustSize()
        return bar

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QFrame#editorBar {
                background-color: rgba(12, 16, 24, 225);
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 12px;
            }
            QLabel#editorHintLabel {
                background: transparent;
                border: none;
                color: #E8EDF5;
                font-size: 12px;
            }
            QPushButton#editorSave {
                background-color: #2F6FF0;
                border: none;
                border-radius: 7px;
                color: #FFFFFF;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton#editorSave:hover {
                background-color: #4F86FF;
            }
            QPushButton#editorCancel {
                background: transparent;
                border: 1px solid rgba(255, 255, 255, 56);
                border-radius: 7px;
                color: #D8DEE9;
                font-size: 12px;
            }
            QPushButton#editorCancel:hover {
                background-color: rgba(255, 255, 255, 24);
            }
            """
        )

    # ---------- fullscreen lifecycle ----------

    def open_fullscreen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())
        self.showFullScreen()
        self._place_initial_card()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._layout_editor)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        QTimer.singleShot(0, self._layout_editor)

    def _layout_editor(self) -> None:
        bounds = self._backdrop.rect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return
        self._guide.setGeometry(bounds)
        self._guide.lower()
        if not self._placed:
            self._place_initial_card()
        else:
            self._clamp_card()
        self._place_bar()
        self._card.raise_()
        self._bar.raise_()

    def _place_bar(self) -> None:
        bounds = self._backdrop.rect()
        self._bar.adjustSize()
        width = min(self._bar.width(), max(1, bounds.width() - 24))
        self._bar.setFixedWidth(width)
        x = max(0, (bounds.width() - width) // 2)
        self._bar.move(x, 22)

    def _configured_width(self, bounds: QRect) -> int:
        width = self._area.width or OVERLAY_CARD_WIDTH_DEFAULT
        width = max(OVERLAY_CARD_WIDTH_MIN, min(OVERLAY_CARD_WIDTH_MAX, width))
        margin = overlay_effective_margin(
            self._area.margin, bounds.width(), bounds.height()
        )
        return min(width, max(1, bounds.width() - margin * 2))

    def _place_initial_card(self) -> None:
        bounds = self._backdrop.rect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return
        width = self._configured_width(bounds)
        self._card.setFixedWidth(width)
        layout = self._card.layout()
        if layout is not None:
            layout.activate()
        height = self._card.heightForWidth(width)
        if height <= 0:
            height = self._card.sizeHint().height()
        height = max(80, min(height, bounds.height()))
        margin = overlay_effective_margin(
            self._area.margin, bounds.width(), bounds.height()
        )
        x, y = overlay_anchor_origin(
            self._area.anchor,
            bounds.width(),
            bounds.height(),
            width,
            height,
            margin,
        )
        x += self._area.offset_x
        y += self._area.offset_y
        x = max(0, min(x, bounds.width() - width))
        y = max(0, min(y, bounds.height() - height))
        self._card.setGeometry(QRect(x, y, width, height))
        self._placed = True
        self._update_hint()

    def _clamp_card(self) -> None:
        bounds = self._backdrop.rect()
        card = self._card
        x = max(0, min(card.x(), bounds.width() - card.width()))
        y = max(0, min(card.y(), bounds.height() - card.height()))
        if (x, y) != (card.x(), card.y()):
            card.move(x, y)
        self._update_hint()

    # ---------- dragging ----------

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self._card:
            kind = event.type()
            if (
                kind == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._dragging = True
                self._drag_offset = event.globalPosition().toPoint() - self._card.mapToGlobal(
                    QPoint(0, 0)
                )
                self._card.setCursor(Qt.CursorShape.ClosedHandCursor)
                return True
            if kind == QEvent.Type.MouseMove and self._dragging:
                self._move_card(event)
                return True
            if (
                kind == QEvent.Type.MouseButtonRelease
                and self._dragging
                and event.button() == Qt.MouseButton.LeftButton
            ):
                self._dragging = False
                self._card.setCursor(Qt.CursorShape.OpenHandCursor)
                self._update_hint()
                return True
        return super().eventFilter(watched, event)

    def _move_card(self, event: QMouseEvent) -> None:
        bounds = self._backdrop.rect()
        point = self._backdrop.mapFromGlobal(
            event.globalPosition().toPoint()
        ) - self._drag_offset
        x = max(0, min(point.x(), bounds.width() - self._card.width()))
        y = max(0, min(point.y(), bounds.height() - self._card.height()))
        self._card.move(x, y)
        self._schedule_hint_update()

    def _schedule_hint_update(self) -> None:
        if self._hint_update_scheduled:
            return
        self._hint_update_scheduled = True
        QTimer.singleShot(40, self._update_hint)

    def _update_hint(self) -> None:
        self._hint_update_scheduled = False
        bounds = self._backdrop.rect()
        if bounds.width() <= 0:
            return
        margin = overlay_effective_margin(
            self._area.margin, bounds.width(), bounds.height()
        )
        anchor, offset_x, offset_y = overlay_anchor_for_rect(
            bounds.width(),
            bounds.height(),
            self._card.x(),
            self._card.y(),
            self._card.width(),
            self._card.height(),
            margin,
            self._area.anchor,
        )
        label = OVERLAY_ANCHOR_LABELS.get(anchor, anchor)
        self._hint.setText(
            f"{self._card.x()}, {self._card.y()} px"
            f" · 宽 {self._card.width()} px"
            f" · {label} {offset_x:+d}/{offset_y:+d}"
        )

    # ---------- saving ----------

    def _save(self) -> None:
        bounds = self._backdrop.rect()
        if bounds.width() <= 0:
            self.reject()
            return
        margin = overlay_effective_margin(
            self._area.margin, bounds.width(), bounds.height()
        )
        anchor, offset_x, offset_y = overlay_anchor_for_rect(
            bounds.width(),
            bounds.height(),
            self._card.x(),
            self._card.y(),
            self._card.width(),
            self._card.height(),
            margin,
            self._area.anchor,
        )
        self.result_area = replace(
            self._area,
            anchor=anchor,
            offset_x=offset_x,
            offset_y=offset_y,
        )
        self.area_saved.emit(self.result_area)
        self.accept()
