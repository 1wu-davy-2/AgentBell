from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .logo import LogoMark
from .motion import motion_enabled

_FINISH_MS = 2200
_LINE_AT_MS = (0, 680, 1360)
_PROGRESS_DELAY_MS = 120
_PROGRESS_MS = 1900


def splash_lines(port: int, first_run: bool, open_center: bool = True) -> tuple[str, str, str]:
    if first_run:
        third = "准备第一次介绍"
    elif open_center:
        third = "正在打开通知中心"
    else:
        third = "AgentBell 已在托盘运行"
    return "正在唤起本机服务", f"127.0.0.1:{port} · 已连接", third


class SplashWindow(QWidget):
    finished = Signal()

    def __init__(
        self,
        port: int,
        *,
        first_run: bool = False,
        open_center: bool = True,
        animate: bool | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.SplashScreen
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(520, 410)
        self._lines = splash_lines(port, first_run, open_center)
        self._animate = motion_enabled() if animate is None else animate
        self._line_index = 0
        self._started = False
        self._finished = False
        self._elapsed = QElapsedTimer()
        self._tick = QTimer(self)
        self._tick.setInterval(30)
        self._tick.timeout.connect(self._on_tick)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 26)
        outer.setSpacing(0)

        card = QFrame(self)
        card.setObjectName("splashCard")
        outer.addWidget(card)

        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(15, 23, 42, 54))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 20, 28, 22)
        layout.setSpacing(0)
        layout.addStretch(1)

        self.logo = LogoMark(160, 92, animate=self._animate)
        layout.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("AgentBell", card)
        title.setObjectName("splashTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(2)
        layout.addWidget(title)

        tagline = QLabel(f"本机通知中心 · v{__version__}", card)
        tagline.setObjectName("splashTagline")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(2)
        layout.addWidget(tagline)

        layout.addSpacing(22)
        self._progress = QProgressBar(card)
        self._progress.setObjectName("splashProgress")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedSize(184, 3)
        layout.addWidget(self._progress, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(12)
        self._line_label = QLabel(self._lines[0], card)
        self._line_label.setObjectName("splashLine")
        self._line_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._line_label.setFixedHeight(20)
        layout.addWidget(self._line_label)
        layout.addStretch(1)

        self.setStyleSheet(
            """
            QFrame#splashCard {
                background-color: #FFFFFF;
                border: 1px solid #E4E7EE;
                border-radius: 18px;
            }
            QLabel#splashTitle {
                background: transparent;
                color: #1C212B;
                font-size: 26px;
                font-weight: 600;
            }
            QLabel#splashTagline {
                background: transparent;
                color: #667085;
                font-size: 11px;
            }
            QLabel#splashLine {
                background: transparent;
                color: #667085;
                font-size: 12px;
            }
            QProgressBar#splashProgress {
                background-color: #E4E7EE;
                border: none;
                border-radius: 1px;
            }
            QProgressBar#splashProgress::chunk {
                background-color: #2F6BFF;
                border-radius: 1px;
            }
            """
        )

    @property
    def lines(self) -> tuple[str, str, str]:
        return self._lines

    @property
    def current_line(self) -> str:
        return self._line_label.text()

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                area.center().x() - self.width() // 2,
                area.center().y() - self.height() // 2,
            )
        super().showEvent(event)
        if not self._started:
            self._start()

    def _start(self) -> None:
        self._started = True
        self._elapsed.start()
        self._tick.start()
        self.logo.chime()

    def _on_tick(self) -> None:
        self._apply_elapsed(self._elapsed.elapsed())

    def _apply_elapsed(self, elapsed: int) -> None:
        progress = (elapsed - _PROGRESS_DELAY_MS) / _PROGRESS_MS
        self._progress.setValue(int(max(0.0, min(1.0, progress)) * 100))

        index = 0
        for order, at in enumerate(_LINE_AT_MS):
            if elapsed >= at:
                index = order
        if index != self._line_index:
            self._line_index = index
            self._line_label.setText(self._lines[index])

        if elapsed >= _FINISH_MS:
            self.finish()

    def finish(self) -> None:
        if self._finished:
            return
        self._finished = True
        self._tick.stop()
        self._progress.setValue(100)
        self._line_label.setText(self._lines[2])
        self.finished.emit()
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._tick.stop()
        super().closeEvent(event)
