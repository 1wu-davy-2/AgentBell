from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from .icons import MARK_INK, MARK_PRIMARY, mark_pixmap
from .motion import motion_enabled

_CHIME_MS = 1400
_RING_START_MS = (180, 360)
_RING_MS = 900
_SWING_START_MS = 200
_SWING_MS = 780
_SWING_STEPS = (
    (0.0, 0.0),
    (0.18, 8.0),
    (0.40, -6.0),
    (0.62, 3.0),
    (0.80, -1.5),
    (1.0, 0.0),
)


def _swing_angle(elapsed_ms: float) -> float:
    if elapsed_ms <= _SWING_START_MS:
        return 0.0
    t = min(1.0, (elapsed_ms - _SWING_START_MS) / _SWING_MS)
    for (t0, a0), (t1, a1) in zip(_SWING_STEPS, _SWING_STEPS[1:]):
        if t <= t1:
            span = t1 - t0
            ratio = 0.0 if span <= 0 else (t - t0) / span
            eased = ratio * ratio * (3.0 - 2.0 * ratio)
            return a0 + (a1 - a0) * eased
    return 0.0


class LogoMark(QWidget):
    def __init__(
        self,
        widget_size: int = 160,
        mark_size: int | None = None,
        *,
        primary: str = MARK_PRIMARY,
        ink: str = MARK_INK,
        animate: bool | None = None,
        interactive: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedSize(widget_size, widget_size)
        self._mark_size = max(8, mark_size or int(widget_size * 0.58))
        self._primary = primary
        self._ink = ink
        self._animate = motion_enabled() if animate is None else animate
        self._pixmap = mark_pixmap(
            self._mark_size * 2,
            primary=self._primary,
            ink=self._ink,
        )
        self._progress = 0.0
        self._chime: QVariantAnimation | None = None
        self.setObjectName("logoMark")
        self.setAccessibleName("AgentBell 标志")
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("点一下，看启动时的那一声")

    def set_colors(self, primary: str, ink: str = MARK_INK) -> None:
        self._primary = primary
        self._ink = ink
        self._pixmap = mark_pixmap(
            self._mark_size * 2,
            primary=self._primary,
            ink=self._ink,
        )
        self.update()

    def chime(self) -> None:
        if not self._animate:
            self.update()
            return
        if self._chime is not None:
            previous = self._chime
            self._chime = None
            previous.stop()
            previous.deleteLater()
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(float(_CHIME_MS))
        animation.setDuration(_CHIME_MS)
        animation.valueChanged.connect(self._on_chime_value)
        animation.finished.connect(self._on_chime_finished)
        self._chime = animation
        animation.start()

    def _on_chime_value(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _on_chime_finished(self) -> None:
        animation = self._chime
        self._progress = 0.0
        self._chime = None
        if animation is not None:
            animation.deleteLater()
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        self._paint_rings(painter, center)

        target = QRectF(
            center.x() - self._mark_size / 2.0,
            center.y() - self._mark_size / 2.0,
            self._mark_size,
            self._mark_size,
        )
        angle = _swing_angle(self._progress)
        if angle:
            painter.save()
            origin = QPointF(center.x(), target.top() + self._mark_size * 0.42)
            painter.translate(origin)
            painter.rotate(angle)
            painter.translate(-origin)
        painter.drawPixmap(
            target,
            self._pixmap,
            QRectF(0.0, 0.0, float(self._pixmap.width()), float(self._pixmap.height())),
        )
        if angle:
            painter.restore()
        painter.end()

    def _paint_rings(self, painter: QPainter, center: QPointF) -> None:
        if self._progress <= 0:
            return
        for start in _RING_START_MS:
            local = (self._progress - start) / _RING_MS
            if local <= 0.0 or local >= 1.0:
                continue
            scale = 0.92 + 0.83 * local
            alpha = int(round(115 * (1.0 - local)))
            if alpha <= 0:
                continue
            color = QColor(self._primary)
            color.setAlpha(alpha)
            diameter = self._mark_size * scale
            rect = QRectF(
                center.x() - diameter / 2.0,
                center.y() - diameter / 2.0,
                diameter,
                diameter,
            )
            pen = QPen(color, max(1.2, self._mark_size / 48.0))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chime()
        super().mousePressEvent(event)
