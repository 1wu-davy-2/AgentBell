from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
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

MARK_PRIMARY = "#2F6BFF"
MARK_INK = "#FFFFFF"
MARK_MONO_PRIMARY = "#1C212B"

_MARK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
  <circle cx="32" cy="32" r="32" fill="{primary}"/>
  <path fill="{ink}" d="M19.2 28.4A12.8 12.8 0 0 1 44.8 28.4L52 39.2H12Z"/>
  <circle cx="32" cy="49.6" r="4.2" fill="{ink}"/>
</svg>"""


def status_color(status: Status) -> QColor:
    return QColor(STATUS_COLORS.get(status, "#4F8CFF"))


def priority_color(priority: str) -> QColor:
    return QColor(PRIORITY_COLORS.get(priority, "#4F8CFF"))


def mark_svg(primary: str = MARK_PRIMARY, ink: str = MARK_INK) -> str:
    return _MARK_SVG.format(primary=primary, ink=ink)


def _mark_bell_path() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(19.2, 28.4)
    path.arcTo(QRectF(19.2, 15.6, 25.6, 25.6), 180.0, -180.0)
    path.lineTo(52.0, 39.2)
    path.lineTo(12.0, 39.2)
    path.closeSubpath()
    return path


def mark_pixmap(
    size: int,
    *,
    primary: str = MARK_PRIMARY,
    ink: str = MARK_INK,
    ratio: float = 1.0,
) -> QPixmap:
    pixel = max(1, int(round(size * ratio)))
    pixmap = QPixmap(pixel, pixel)
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(pixel / 64.0, pixel / 64.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(primary))
    painter.drawEllipse(QRectF(0.0, 0.0, 64.0, 64.0))
    painter.setBrush(QColor(ink))
    painter.drawPath(_mark_bell_path())
    painter.drawEllipse(QRectF(27.8, 45.4, 8.4, 8.4))
    painter.end()
    return pixmap


def _render_app_icon(size: int) -> QPixmap:
    return mark_pixmap(size)


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
