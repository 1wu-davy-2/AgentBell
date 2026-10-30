from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .icons import mark_pixmap
from .logo import LogoMark

AUTO_ADVANCE_MS = 4600


def onboarding_steps(hotkey: str = "Ctrl+Alt+A") -> tuple[tuple[str, str, str], ...]:
    hotkey = hotkey.strip()
    fourth = (
        f"窗口收进托盘，本机服务继续跑。{hotkey} 把窗口叫回来。"
        if hotkey
        else "窗口收进托盘，本机服务继续跑。点托盘图标把窗口叫回来。"
    )
    return (
        (
            "只读",
            "只带走元数据",
            "扫描本机上 Claude Code 与 Qoder 的会话。路径、条数和体积会留下，"
            "只有点「查看记录」时才会在本机解析对话内容。",
        ),
        (
            "通知",
            "一轮任务，一声铃",
            "每次做完一轮，这里多一条记录。完成、失败、取消和进行中，用颜色分开。",
        ),
        (
            "会话",
            "文件还在你的盘上",
            "会话按项目归在一起。可以直接打开目录、查看完整记录，也可以把路径复制走。",
        ),
        ("常驻", "关窗之后，服务还在", fourth),
    )


class _StepPills(QWidget):
    clicked = Signal(int)

    def __init__(self, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._count = count
        self._step = 0
        self._progress = 0.0
        self.setFixedSize(112, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("onboardPills")

    def set_state(self, step: int, progress: float) -> None:
        self._step = max(0, min(self._count - 1, int(step)))
        self._progress = max(0.0, min(1.0, float(progress)))
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        x = 0.0
        y = (self.height() - 6.0) / 2.0
        for index in range(self._count):
            width = 40.0 if index == self._step else 16.0
            rect = QRectF(x, y, width, 6.0)
            if index < self._step:
                painter.setBrush(QColor("#2F6BFF"))
                painter.drawRoundedRect(rect, 3.0, 3.0)
            elif index > self._step:
                painter.setBrush(QColor("#E4E7EE"))
                painter.drawRoundedRect(rect, 3.0, 3.0)
            else:
                painter.setBrush(QColor("#E4E7EE"))
                painter.drawRoundedRect(rect, 3.0, 3.0)
                if self._progress > 0:
                    filled = QRectF(x, y, width * self._progress, 6.0)
                    painter.setBrush(QColor("#2F6BFF"))
                    painter.drawRoundedRect(filled, 3.0, 3.0)
            x += width + 8.0
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        offset = 0.0
        for index in range(self._count):
            width = 40.0 if index == self._step else 16.0
            if offset <= x <= offset + width:
                self.clicked.emit(index)
                return
            offset += width + 8.0


def _label(text: str, name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _panel(parent: QWidget) -> tuple[QFrame, QVBoxLayout]:
    panel = QFrame(parent)
    panel.setObjectName("onboardPanel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(7)
    return panel, layout


def _scan_visual(parent: QWidget) -> QWidget:
    panel, layout = _panel(parent)
    layout.addWidget(_label("Claude Code · 会话 8a797da2", "onboardMuted", panel))
    for name, value in (
        ("路径", r"E:\code_repo\argus"),
        ("条数", "1598 条记录"),
        ("体积", "64.8 MB"),
    ):
        row = QFrame(panel)
        row.setObjectName("onboardRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(10, 7, 10, 7)
        row_layout.setSpacing(8)
        left = _label(name, "onboardMuted", row)
        right = _label(value, "onboardValue", row)
        right.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right.setWordWrap(False)
        row_layout.addWidget(left)
        row_layout.addWidget(right, 1)
        layout.addWidget(row)
    layout.addSpacing(2)
    layout.addWidget(_label("✓  不解析对话内容", "onboardOk", panel))
    layout.addStretch(1)
    return panel


def _note_visual(parent: QWidget, animate: bool) -> tuple[QWidget, LogoMark]:
    container = QWidget(parent)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 4, 6, 0)
    layout.setSpacing(6)
    logo = LogoMark(64, 34, animate=animate)
    layout.addWidget(logo, 0, Qt.AlignmentFlag.AlignRight)
    note = QFrame(container)
    note.setObjectName("onboardNote")
    note_layout = QHBoxLayout(note)
    note_layout.setContentsMargins(12, 12, 12, 12)
    note_layout.setSpacing(10)
    tick = _label("✓", "onboardTick", note)
    tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
    tick.setFixedSize(38, 38)
    note_layout.addWidget(tick, 0, Qt.AlignmentFlag.AlignTop)
    text = QVBoxLayout()
    text.setContentsMargins(0, 0, 0, 0)
    text.setSpacing(3)
    text.addWidget(_label("同步 API 版本号并提交", "onboardNoteTitle", note))
    text.addWidget(_label("已完成 · 今天 12:52", "onboardMuted", note))
    note_layout.addLayout(text, 1)
    layout.addWidget(note)
    layout.addStretch(1)
    return container, logo


def _path_visual(parent: QWidget) -> QWidget:
    panel, layout = _panel(parent)
    layout.addWidget(_label("Claude Code", "onboardWarn", panel))
    layout.addWidget(_label("会话 8a797da2", "onboardNoteTitle", panel))
    path = _label(r"E:\code_repo\argus", "onboardMuted", panel)
    path.setWordWrap(False)
    layout.addWidget(path)
    layout.addSpacing(6)
    buttons = QHBoxLayout()
    buttons.setContentsMargins(0, 0, 0, 0)
    buttons.setSpacing(7)
    open_button = _label("打开目录", "onboardFakePrimary", panel)
    open_button.setAlignment(Qt.AlignmentFlag.AlignCenter)
    open_button.setFixedSize(74, 28)
    copy_button = _label("复制路径", "onboardFakeGhost", panel)
    copy_button.setAlignment(Qt.AlignmentFlag.AlignCenter)
    copy_button.setFixedSize(74, 28)
    buttons.addWidget(open_button)
    buttons.addWidget(copy_button)
    buttons.addStretch(1)
    layout.addLayout(buttons)
    layout.addStretch(1)
    return panel


def _tray_visual(parent: QWidget, hotkey: str) -> QWidget:
    panel, layout = _panel(parent)
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(8)
    mini = QFrame(panel)
    mini.setObjectName("onboardNote")
    mini_layout = QHBoxLayout(mini)
    mini_layout.setContentsMargins(9, 7, 9, 7)
    mini_layout.setSpacing(6)
    mini_mark = QLabel(mini)
    mini_mark.setPixmap(mark_pixmap(20))
    mini_mark.setFixedSize(20, 20)
    mini_layout.addWidget(mini_mark)
    mini_layout.addWidget(_label("通知中心", "onboardValue", mini))
    top.addWidget(mini, 1)
    tray = QFrame(panel)
    tray.setObjectName("onboardTrayPill")
    tray_layout = QHBoxLayout(tray)
    tray_layout.setContentsMargins(7, 5, 11, 5)
    tray_layout.setSpacing(6)
    tray_mark = QLabel(tray)
    tray_mark.setPixmap(mark_pixmap(18))
    tray_mark.setFixedSize(18, 18)
    tray_layout.addWidget(tray_mark)
    tray_layout.addWidget(_label("托盘", "onboardMuted", tray))
    top.addWidget(tray, 0)
    layout.addLayout(top)
    layout.addStretch(1)
    layout.addWidget(_label("快捷键把窗口叫回来", "onboardMuted", panel))
    keys = [part.strip() for part in hotkey.split("+") if part.strip()] or ["托盘图标"]
    key_row = QHBoxLayout()
    key_row.setContentsMargins(0, 0, 0, 0)
    key_row.setSpacing(5)
    for key in keys[:4]:
        cap = _label(key, "onboardKey", panel)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setWordWrap(False)
        cap.setMinimumWidth(36)
        cap.setFixedHeight(24)
        key_row.addWidget(cap)
    key_row.addStretch(1)
    layout.addLayout(key_row)
    return panel


class OnboardingOverlay(QWidget):
    finished = Signal()

    def __init__(
        self,
        parent: QWidget,
        *,
        hotkey: str = "Ctrl+Alt+A",
        animate: bool = True,
        auto: bool = True,
    ) -> None:
        super().__init__(parent)
        self._steps = onboarding_steps(hotkey)
        self._hotkey = hotkey
        self._animate = animate
        self._step = 0
        self._auto = auto
        self._done = False
        self.setObjectName("onboardingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.setInterval(AUTO_ADVANCE_MS)
        self._auto_timer.timeout.connect(self._advance_auto)

        self._progress_anim = QVariantAnimation(self)
        self._progress_anim.setStartValue(0.0)
        self._progress_anim.setEndValue(1.0)
        self._progress_anim.setDuration(AUTO_ADVANCE_MS)
        self._progress_anim.valueChanged.connect(self._on_progress)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        self._card = self._build_card()
        row.addWidget(self._card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self.setStyleSheet(_STYLE)
        self._sync()

    # ---------- construction ----------

    def _build_card(self) -> QFrame:
        card = QFrame(self)
        card.setObjectName("onboardCard")
        card.setMinimumWidth(720)
        card.setMaximumWidth(800)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(44)
        shadow.setOffset(0, 12)
        shadow.setColor(QColor(15, 23, 42, 70))
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        self._pills = _StepPills(len(self._steps), card)
        self._pills.clicked.connect(self.go_to_step)
        header.addWidget(self._pills)
        self._count_label = _label("1 / 4", "onboardMuted", card)
        self._count_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._count_label.setWordWrap(False)
        header.addWidget(self._count_label, 1)
        layout.addLayout(header)
        layout.addSpacing(18)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(24)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(0)
        self._kicker = _label("", "onboardKicker", card)
        self._kicker.setWordWrap(False)
        left.addWidget(self._kicker)
        left.addSpacing(4)
        self._title = _label("", "onboardTitle", card)
        left.addWidget(self._title)
        left.addSpacing(7)
        self._body = _label("", "onboardBody", card)
        self._body.setMinimumHeight(52)
        left.addWidget(self._body)
        left.addStretch(1)
        left.addSpacing(14)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(6)
        self._prev = QPushButton("上一步", card)
        self._prev.setObjectName("onboardGhost")
        self._prev.setFixedSize(76, 32)
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.clicked.connect(self.previous_step)
        self._next = QPushButton("下一步", card)
        self._next.setObjectName("onboardPrimary")
        self._next.setFixedSize(112, 32)
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.clicked.connect(self.next_step)
        self._skip = QPushButton("跳过介绍", card)
        self._skip.setObjectName("onboardLink")
        self._skip.setFixedHeight(32)
        self._skip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip.clicked.connect(self.skip)
        self._auto_button = QPushButton("暂停", card)
        self._auto_button.setObjectName("onboardFaint")
        self._auto_button.setFixedHeight(32)
        self._auto_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._auto_button.clicked.connect(self.toggle_auto)
        for button in (self._prev, self._next, self._skip, self._auto_button):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        buttons.addWidget(self._prev)
        buttons.addWidget(self._next)
        buttons.addSpacing(4)
        buttons.addWidget(self._skip)
        buttons.addWidget(self._auto_button, 1, Qt.AlignmentFlag.AlignRight)
        left.addLayout(buttons)
        body.addLayout(left, 1)

        self._visuals = QStackedWidget(card)
        self._visuals.setObjectName("onboardVisuals")
        self._visuals.setFixedWidth(290)
        self._visuals.setMinimumHeight(232)
        self._visuals.addWidget(_scan_visual(self._visuals))
        note, self._note_logo = _note_visual(self._visuals, self._animate)
        self._visuals.addWidget(note)
        self._visuals.addWidget(_path_visual(self._visuals))
        self._visuals.addWidget(_tray_visual(self._visuals, self._hotkey))
        body.addWidget(self._visuals, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(body)
        return card

    # ---------- state ----------

    @property
    def current_step(self) -> int:
        return self._step

    @property
    def step_count(self) -> int:
        return len(self._steps)

    @property
    def auto_playing(self) -> bool:
        return self._auto

    def showEvent(self, event) -> None:  # noqa: N802
        if self.parentWidget() is not None:
            self.setGeometry(self.parentWidget().rect())
        super().showEvent(event)
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self._done:
            self._restart_auto()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._auto_timer.stop()
        self._progress_anim.stop()
        super().hideEvent(event)

    def go_to_step(self, index: int) -> None:
        index = max(0, min(self.step_count - 1, int(index)))
        self._step = index
        self._sync()
        self._restart_auto()
        if index == 1 and self._animate and self.isVisible():
            self._note_logo.chime()

    def next_step(self) -> None:
        if self._step >= self.step_count - 1:
            self._complete()
            return
        self.go_to_step(self._step + 1)

    def previous_step(self) -> None:
        if self._step > 0:
            self.go_to_step(self._step - 1)

    def skip(self) -> None:
        self._complete()

    def toggle_auto(self) -> None:
        self._auto = not self._auto
        self._auto_button.setText("暂停" if self._auto else "继续播放")
        self._restart_auto()

    def _sync(self) -> None:
        kicker, title, body = self._steps[self._step]
        self._kicker.setText(kicker)
        self._title.setText(title)
        self._body.setText(body)
        self._count_label.setText(f"{self._step + 1} / {self.step_count}")
        self._visuals.setCurrentIndex(self._step)
        self._prev.setEnabled(self._step > 0)
        last = self._step == self.step_count - 1
        self._next.setText("进入通知中心" if last else "下一步")
        if not self._auto:
            self._pills.set_state(self._step, 1.0)
        else:
            self._pills.set_state(self._step, 0.0)

    def _restart_auto(self) -> None:
        self._auto_timer.stop()
        self._progress_anim.stop()
        if not self._auto:
            self._pills.set_state(self._step, 1.0)
            return
        self._pills.set_state(self._step, 0.0)
        self._progress_anim.start()
        self._auto_timer.start()

    def _advance_auto(self) -> None:
        if not self._auto:
            return
        if self._step >= self.step_count - 1:
            self._complete()
        else:
            self.go_to_step(self._step + 1)

    def _on_progress(self, value) -> None:
        self._pills.set_state(self._step, float(value))

    def _complete(self) -> None:
        if self._done:
            return
        self._done = True
        self._auto_timer.stop()
        self._progress_anim.stop()
        self.hide()
        self.finished.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        event.accept()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.skip()
            return
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.next_step()
            return
        if key == Qt.Key.Key_Left:
            self.previous_step()
            return
        super().keyPressEvent(event)


_STYLE = """
QWidget#onboardingOverlay {
    background-color: rgba(28, 33, 43, 58);
}
QFrame#onboardCard {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EE;
    border-radius: 16px;
}
QLabel#onboardKicker {
    background: transparent;
    color: #2F6BFF;
    font-size: 11px;
    font-weight: 600;
}
QLabel#onboardTitle {
    background: transparent;
    color: #1C212B;
    font-size: 22px;
    font-weight: 600;
}
QLabel#onboardBody {
    background: transparent;
    color: #667085;
    font-size: 12px;
}
QLabel#onboardMuted {
    background: transparent;
    color: #98A2B3;
    font-size: 11px;
}
QLabel#onboardValue {
    background: transparent;
    color: #1C212B;
    font-size: 11px;
}
QLabel#onboardOk {
    background: transparent;
    color: #178A52;
    font-size: 11px;
}
QLabel#onboardWarn {
    background: transparent;
    color: #B57614;
    font-size: 11px;
}
QFrame#onboardPanel {
    background-color: #F4F6F9;
    border: 1px solid #E4E7EE;
    border-radius: 12px;
}
QFrame#onboardRow {
    background-color: #FFFFFF;
    border: 1px solid #EDF0F4;
    border-radius: 8px;
}
QFrame#onboardNote {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EE;
    border-radius: 11px;
}
QLabel#onboardTick {
    background-color: #E5F6ED;
    color: #178A52;
    border-radius: 9px;
    font-size: 16px;
    font-weight: 600;
}
QLabel#onboardNoteTitle {
    background: transparent;
    color: #1C212B;
    font-size: 12px;
    font-weight: 600;
}
QFrame#onboardTrayPill {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EE;
    border-radius: 13px;
}
QLabel#onboardFakePrimary {
    background-color: #2F6BFF;
    color: #FFFFFF;
    border-radius: 7px;
    font-size: 11px;
    font-weight: 600;
}
QLabel#onboardFakeGhost {
    background-color: #FFFFFF;
    color: #1C212B;
    border: 1px solid #E4E7EE;
    border-radius: 7px;
    font-size: 11px;
}
QLabel#onboardKey {
    background-color: #FFFFFF;
    color: #1C212B;
    border: 1px solid #E4E7EE;
    border-radius: 6px;
    font-size: 11px;
}
QPushButton#onboardPrimary {
    background-color: #2F6BFF;
    border: none;
    border-radius: 7px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#onboardPrimary:hover {
    background-color: #4F86FF;
}
QPushButton#onboardGhost {
    background-color: transparent;
    border: 1px solid #E4E7EE;
    border-radius: 7px;
    color: #667085;
    font-size: 12px;
}
QPushButton#onboardGhost:hover {
    background-color: #F4F6F9;
}
QPushButton#onboardGhost:disabled {
    color: #C3CAD4;
    border-color: #EDF0F4;
}
QPushButton#onboardLink {
    background: transparent;
    border: none;
    color: #667085;
    font-size: 12px;
}
QPushButton#onboardLink:hover {
    color: #1C212B;
}
QPushButton#onboardFaint {
    background: transparent;
    border: none;
    color: #98A2B3;
    font-size: 12px;
}
QPushButton#onboardFaint:hover {
    color: #667085;
}
"""
