from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .icons import MARK_MONO_PRIMARY, make_app_icon, mark_pixmap, mark_svg
from .logo import LogoMark
from .motion import motion_enabled

_SIZES = (16, 24, 32, 48, 64)


def _label(text: str, name: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _size_tile(size: int, parent: QWidget) -> QFrame:
    tile = QFrame(parent)
    tile.setObjectName("aboutTile")
    tile.setFixedSize(92, 94)
    layout = QVBoxLayout(tile)
    layout.setContentsMargins(8, 12, 8, 8)
    layout.setSpacing(6)
    mark = QLabel(tile)
    mark.setPixmap(mark_pixmap(size))
    mark.setFixedSize(size, size)
    layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
    layout.addStretch(1)
    caption = _label(str(size), "aboutTileCaption", tile)
    caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(caption)
    return tile


def _variant_tile(title: str, caption: str, mono: bool, parent: QWidget) -> QFrame:
    tile = QFrame(parent)
    tile.setObjectName("aboutTile")
    layout = QHBoxLayout(tile)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(12)
    mark = QLabel(tile)
    mark.setPixmap(
        mark_pixmap(
            48,
            primary=MARK_MONO_PRIMARY if mono else "#2F6BFF",
            ink="#FFFFFF",
        )
    )
    mark.setFixedSize(48, 48)
    layout.addWidget(mark, 0, Qt.AlignmentFlag.AlignVCenter)
    text = QVBoxLayout()
    text.setContentsMargins(0, 0, 0, 0)
    text.setSpacing(3)
    text.addWidget(_label(title, "aboutTileTitle", tile))
    text.addWidget(_label(caption, "aboutMuted", tile))
    layout.addLayout(text, 1)
    return tile


class AboutDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        animate: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self._animate = motion_enabled() if animate is None else animate
        self.setWindowTitle("关于 AgentBell")
        self.setWindowIcon(make_app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(640, 540)
        self.resize(700, 580)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 18)
        outer.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(18)
        logo_col = QVBoxLayout()
        logo_col.setContentsMargins(0, 0, 0, 0)
        logo_col.setSpacing(0)
        self.logo = LogoMark(132, 76, animate=self._animate, interactive=True)
        logo_col.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignHCenter)
        hint = _label("点一下，重听启动铃声", "aboutMuted", self)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(False)
        logo_col.addWidget(hint)
        header.addLayout(logo_col)

        text = QVBoxLayout()
        text.setContentsMargins(0, 8, 0, 0)
        text.setSpacing(3)
        name = _label("AgentBell", "aboutName", self)
        name.setWordWrap(False)
        text.addWidget(name)
        text.addWidget(_label(f"本机通知中心 · v{__version__}", "aboutMuted", self))
        text.addSpacing(8)
        text.addWidget(
            _label(
                "只监听 127.0.0.1，通知和 Agent 会话都留在本机。",
                "aboutBody",
                self,
            )
        )
        text.addStretch(1)
        header.addLayout(text, 1)

        replay = QPushButton("重响", self)
        replay.setObjectName("aboutSecondary")
        replay.setFixedSize(76, 32)
        replay.setCursor(Qt.CursorShape.PointingHandCursor)
        replay.clicked.connect(self.logo.chime)
        header.addWidget(replay, 0, Qt.AlignmentFlag.AlignTop)
        outer.addLayout(header)
        outer.addSpacing(18)

        heading = _label("一只铃，分开的铃舌", "aboutHeading", self)
        outer.addWidget(heading)
        outer.addSpacing(5)
        outer.addWidget(
            _label(
                "圆形底用在窗口、桌面快捷方式和托盘。铃身和铃舌留出空隙，"
                "缩到 16 像素仍然是一只铃，而不是一个圆点。",
                "aboutBody",
                self,
            )
        )
        outer.addSpacing(16)

        sizes_title = _label("尺寸", "aboutSection", self)
        outer.addWidget(sizes_title)
        sizes = QHBoxLayout()
        sizes.setContentsMargins(0, 0, 0, 0)
        sizes.setSpacing(8)
        for size in _SIZES:
            sizes.addWidget(_size_tile(size, self))
        sizes.addStretch(1)
        outer.addSpacing(7)
        outer.addLayout(sizes)
        outer.addSpacing(14)

        variants = QHBoxLayout()
        variants.setContentsMargins(0, 0, 0, 0)
        variants.setSpacing(8)
        variants.addWidget(
            _variant_tile("彩色", "默认。蓝底白铃。", False, self), 1
        )
        variants.addWidget(
            _variant_tile("单色", "文档或反白场景，把圆形改成墨色。", True, self), 1
        )
        outer.addLayout(variants)
        outer.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(8)
        self._status = _label("", "aboutMuted", self)
        footer.addWidget(self._status, 1)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(3600)
        self._status_timer.timeout.connect(lambda: self._status.setText(""))
        save = QPushButton("保存 SVG…", self)
        save.setObjectName("aboutSecondary")
        save.setFixedSize(104, 34)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._choose_svg)
        footer.addWidget(save)
        close = QPushButton("关闭", self)
        close.setObjectName("aboutPrimary")
        close.setFixedSize(84, 34)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        outer.addLayout(footer)

        self.setStyleSheet(_STYLE)

    def export_svg(self, path: Path) -> None:
        target = Path(path)
        target.write_text(mark_svg() + "\n", encoding="utf-8")

    def _choose_svg(self) -> None:
        default = str(Path.home() / "agentbell-mark.svg")
        path, _ = QFileDialog.getSaveFileName(
            self, "保存 AgentBell 标志", default, "SVG 图像 (*.svg)"
        )
        if not path:
            return
        if not path.lower().endswith(".svg"):
            path += ".svg"
        try:
            self.export_svg(Path(path))
        except OSError as exc:
            QMessageBox.warning(
                self, "保存失败", f"无法写入标志文件：\n{exc}"
            )
            return
        self._status.setText(f"已保存到 {path}")
        self._status_timer.start()


_STYLE = """
QDialog {
    background-color: #FFFFFF;
}
QLabel#aboutName {
    background: transparent;
    color: #1C212B;
    font-size: 24px;
    font-weight: 600;
}
QLabel#aboutHeading {
    background: transparent;
    color: #1C212B;
    font-size: 15px;
    font-weight: 600;
}
QLabel#aboutSection {
    background: transparent;
    color: #1C212B;
    font-size: 12px;
    font-weight: 600;
}
QLabel#aboutBody {
    background: transparent;
    color: #667085;
    font-size: 12px;
}
QLabel#aboutMuted {
    background: transparent;
    color: #98A2B3;
    font-size: 11px;
}
QLabel#aboutTileTitle {
    background: transparent;
    color: #1C212B;
    font-size: 12px;
    font-weight: 600;
}
QLabel#aboutTileCaption {
    background: transparent;
    color: #98A2B3;
    font-size: 10px;
}
QFrame#aboutTile {
    background-color: #F4F6F9;
    border: 1px solid #E4E7EE;
    border-radius: 11px;
}
QPushButton#aboutPrimary {
    background-color: #2F6BFF;
    border: none;
    border-radius: 7px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
}
QPushButton#aboutPrimary:hover {
    background-color: #4F86FF;
}
QPushButton#aboutSecondary {
    background-color: #FFFFFF;
    border: 1px solid #E4E7EE;
    border-radius: 7px;
    color: #1C212B;
    font-size: 12px;
}
QPushButton#aboutSecondary:hover {
    background-color: #F4F6F9;
}
"""
