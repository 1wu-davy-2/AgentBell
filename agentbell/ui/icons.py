from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from ..models import Status

STATUS_COLORS: dict[str, str] = {
    "succeeded": "#38D39F",
    "failed": "#FF6B6B",
    "canceled": "#F0B45A",
    "running": "#4F8CFF",
}

PRIORITY_COLORS: dict[str, str] = {
    "low": "#778192",
    "normal": "#4F8CFF",
    "high": "#F0B45A",
    "critical": "#FF6B6B",
}


def status_color(status: Status) -> QColor:
    return QColor(STATUS_COLORS.get(status, "#4F8CFF"))


def priority_color(priority: str) -> QColor:
    return QColor(PRIORITY_COLORS.get(priority, "#4F8CFF"))


def _bell_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(32.0, 14.0)
    path.cubicTo(23.8, 14.0, 20.8, 20.8, 20.8, 29.4)
    path.cubicTo(20.8, 36.6, 18.1, 38.9, 15.0, 42.0)
    path.lineTo(49.0, 42.0)
    path.cubicTo(45.9, 38.9, 43.2, 36.6, 43.2, 29.4)
    path.cubicTo(43.2, 20.8, 40.2, 14.0, 32.0, 14.0)
    path.closeSubpath()
    return path


def _render_app_icon(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(size / 64.0, size / 64.0)

    background = QLinearGradient(9.0, 3.0, 55.0, 62.0)
    background.setColorAt(0.0, QColor("#5A9BFF"))
    background.setColorAt(1.0, QColor("#6C5CE7"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(background)
    painter.drawEllipse(QRectF(2.0, 2.0, 60.0, 60.0))

    highlight = QColor(255, 255, 255, 28)
    painter.setBrush(highlight)
    painter.drawEllipse(QRectF(9.0, 6.0, 46.0, 34.0))

    painter.setBrush(QColor(10, 20, 45, 55))
    painter.save()
    painter.translate(0.0, 1.4)
    painter.drawPath(_bell_path())
    painter.drawEllipse(QRectF(28.5, 45.3, 7.0, 7.0))
    painter.restore()

    painter.setBrush(QColor(255, 255, 255, 246))
    painter.drawEllipse(QRectF(29.4, 9.4, 5.2, 5.2))
    painter.drawPath(_bell_path())
    painter.drawEllipse(QRectF(28.5, 45.0, 7.0, 7.0))

    painter.end()
    return pixmap


def make_app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_render_app_icon(size))
    return icon


def status_pixmap(status: Status, size: int = 38) -> QPixmap:
    scale = size / 38.0
    pixmap = QPixmap(int(round(size * 2)), int(round(size * 2)))
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(scale, scale)

    accent = status_color(status)
    fill = QColor(accent)
    fill.setAlpha(34)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(fill)
    painter.drawEllipse(QRectF(0.5, 0.5, 37.0, 37.0))

    ring = QColor(accent)
    ring.setAlpha(105)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(ring, 1.2))
    painter.drawEllipse(QRectF(0.8, 0.8, 36.4, 36.4))

    pen = QPen(accent, 2.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    if status == "failed":
        painter.drawLine(QPointF(13.0, 13.0), QPointF(25.0, 25.0))
        painter.drawLine(QPointF(25.0, 13.0), QPointF(13.0, 25.0))
    elif status == "canceled":
        painter.drawLine(QPointF(12.5, 19.0), QPointF(25.5, 19.0))
    elif status == "running":
        painter.drawEllipse(QPointF(19.0, 19.0), 7.0, 7.0)
        painter.drawLine(QPointF(19.0, 15.0), QPointF(19.0, 19.0))
        painter.drawLine(QPointF(19.0, 19.0), QPointF(22.0, 21.0))
    else:
        path = QPainterPath()
        path.moveTo(10.5, 19.6)
        path.lineTo(16.3, 25.2)
        path.lineTo(27.7, 13.2)
        painter.drawPath(path)

    painter.end()
    return pixmap


def make_alert_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = _render_app_icon(size)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        scale = size / 64.0
        painter.setPen(QPen(QColor("#FFFFFF"), max(1.0, 2.0 * scale)))
        painter.setBrush(QColor("#FF4D4F"))
        radius = 15.0 * scale
        center = QPointF(49.0 * scale, 15.0 * scale)
        painter.drawEllipse(center, radius, radius)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
