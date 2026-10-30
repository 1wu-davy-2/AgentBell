from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..config import ToolchainConfig
from ..toolchain import (
    DEEPSEEK_CODEX_TOML,
    NODE_ID,
    NPM_REGISTRY_MIRROR,
    NPM_REGISTRY_OFFICIAL,
    NPM_TOOLS,
    ComponentState,
    Progress,
    ToolchainError,
    ToolchainService,
    deepseek_claude_env,
    protect_secret,
    reveal_secret,
)

CC_SWITCH_URL = "https://github.com/farion1231/cc-switch/releases/latest"

STYLE = """
QFrame#toolRow {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 12px;
}
QLabel#toolName {
    font-size: 12px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#toolSummary {
    font-size: 10px;
    color: #8A919D;
}
QLabel#toolMeta {
    font-size: 10px;
    color: #9AA1AC;
}
QLabel#toolChip {
    font-size: 10px;
    font-weight: 600;
    color: #6B7280;
    background-color: #F3F5F8;
    border-radius: 9px;
    padding: 3px 9px;
}
QLabel#toolChip[installed="true"] {
    color: #1D7A4C;
    background-color: #E8F6EE;
}
QLabel#toolHint {
    font-size: 10px;
    color: #6B7280;
}
QLabel#toolHint[state="error"] {
    color: #C24141;
}
QPushButton#toolAction {
    background-color: #F5F6FA;
    border: 1px solid #EAECF1;
    border-radius: 7px;
    color: #4B5563;
    font-size: 11px;
    padding: 0px 10px;
}
QPushButton#toolAction:hover {
    background-color: #E9EEF8;
    border-color: #D7E2F6;
}
QPushButton#toolAction:disabled {
    color: #B4BAC5;
    background-color: #F7F8FA;
}
QPushButton#toolPrimary {
    background-color: #2F6FF0;
    border: none;
    border-radius: 7px;
    color: #FFFFFF;
    font-size: 11px;
    font-weight: 600;
    padding: 0px 12px;
}
QPushButton#toolPrimary:hover {
    background-color: #1F5FDF;
}
QPushButton#toolPrimary:disabled {
    background-color: #C9D6EA;
    color: #F3F5F8;
}
QLineEdit#toolKey {
    background-color: #F9FAFC;
    border: 1px solid #E3E7ED;
    border-radius: 8px;
    color: #1F2329;
    font-size: 12px;
    padding: 0px 10px;
}
QLineEdit#toolKey:focus {
    border-color: #9DBBFF;
    background-color: #FFFFFF;
}
QComboBox#toolRegistry {
    background-color: #F9FAFC;
    border: 1px solid #E3E7ED;
    border-radius: 8px;
    color: #1F2329;
    font-size: 11px;
    padding: 0px 8px;
}
QComboBox#toolRegistry::drop-down {
    border: none;
    width: 22px;
}
QComboBox#toolRegistry QAbstractItemView {
    background-color: #FFFFFF;
    border: 1px solid #E3E7ED;
    selection-background-color: #EAF2FF;
    selection-color: #1F2329;
}
QProgressBar#toolProgress {
    background-color: #EEF1F6;
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
}
QProgressBar#toolProgress::chunk {
    background-color: #2F6FF0;
    border-radius: 3px;
}
"""


class _JobSignals(QObject):
    progress = Signal(object)
    done = Signal(str)
    failed = Signal(str)


class _ToolRow(QFrame):
    install_requested = Signal(str)
    uninstall_requested = Signal(str)
    open_requested = Signal(str)

    def __init__(
        self,
        component_id: str,
        name: str,
        summary: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toolRow")
        self.component_id = component_id
        self._installed = False
        self._openable = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        self._name = QLabel(name, self)
        self._name.setObjectName("toolName")
        title_row.addWidget(self._name)
        self._chip = QLabel("未安装", self)
        self._chip.setObjectName("toolChip")
        title_row.addWidget(self._chip)
        title_row.addStretch(1)
        text.addLayout(title_row)
        self._summary = QLabel(summary, self)
        self._summary.setObjectName("toolSummary")
        text.addWidget(self._summary)
        self._meta = QLabel("", self)
        self._meta.setObjectName("toolMeta")
        text.addWidget(self._meta)
        layout.addLayout(text, 1)

        self._open_button = QPushButton("打开", self)
        self._open_button.setObjectName("toolAction")
        self._open_button.setFixedHeight(28)
        self._open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_button.clicked.connect(
            lambda: self.open_requested.emit(self.component_id)
        )
        self._open_button.hide()
        layout.addWidget(self._open_button)

        self._remove_button = QPushButton("卸载", self)
        self._remove_button.setObjectName("toolAction")
        self._remove_button.setFixedHeight(28)
        self._remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_button.clicked.connect(
            lambda: self.uninstall_requested.emit(self.component_id)
        )
        self._remove_button.hide()
        layout.addWidget(self._remove_button)

        self._install_button = QPushButton("安装", self)
        self._install_button.setObjectName("toolPrimary")
        self._install_button.setFixedHeight(28)
        self._install_button.setMinimumWidth(64)
        self._install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_button.clicked.connect(
            lambda: self.install_requested.emit(self.component_id)
        )
        layout.addWidget(self._install_button)

    def set_state(self, state: ComponentState | None, busy: bool) -> None:
        installed = bool(state and state.installed)
        self._installed = installed
        self._openable = bool(state and state.path and state.kind in {"app", "runtime"})
        if state is None:
            self._chip.setText("未安装")
        elif installed:
            self._chip.setText(f"v{state.version}" if state.version else "已安装")
        else:
            self._chip.setText("未安装")
        self._chip.setProperty("installed", "true" if installed else "false")
        self._chip.style().unpolish(self._chip)
        self._chip.style().polish(self._chip)
        self._meta.setText(state.path if state and state.path else "")
        self._meta.setToolTip(state.path if state else "")
        self._install_button.setText("重新安装" if installed else "安装")
        self._install_button.setEnabled(not busy)
        self._remove_button.setVisible(installed)
        self._remove_button.setEnabled(not busy)
        self._open_button.setVisible(self._openable)
        self._open_button.setEnabled(not busy)


class _ExternalRow(QFrame):
    def __init__(
        self,
        name: str,
        summary: str,
        url: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("toolRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        self._name = QLabel(name, self)
        self._name.setObjectName("toolName")
        text.addWidget(self._name)
        self._summary = QLabel(summary, self)
        self._summary.setObjectName("toolSummary")
        text.addWidget(self._summary)
        meta = QLabel("GitHub Releases · 便携版", self)
        meta.setObjectName("toolMeta")
        text.addWidget(meta)
        layout.addLayout(text, 1)

        self._download = QPushButton("打开下载页", self)
        self._download.setObjectName("toolAction")
        self._download.setFixedHeight(28)
        self._download.setMinimumWidth(88)
        self._download.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(url))
        )
        layout.addWidget(self._download)


class ToolchainPage(QWidget):
    changed = Signal()
    provider_launch_requested = Signal(dict)
    config_patch_requested = Signal(object)

    def __init__(
        self,
        root: Path,
        config: ToolchainConfig,
        logger: logging.Logger,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("bodyPanel")
        self._root = Path(root)
        self._config = config
        self._logger = logger
        self._service = self._make_service(config)
        self._rows: dict[str, _ToolRow] = {}
        self._busy = False
        self._thread: threading.Thread | None = None
        self._signals = _JobSignals(self)
        self._signals.progress.connect(self._on_progress)
        self._signals.done.connect(self._on_done)
        self._signals.failed.connect(self._on_failed)

        self.setStyleSheet(STYLE)
        self._build()
        self.refresh()

    # ---------- construction ----------

    def _make_service(self, config: ToolchainConfig) -> ToolchainService:
        return ToolchainService(
            self._root, registry=config.npm_registry, logger=self._logger
        )

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 22, 28, 18)
        layout.setSpacing(0)

        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(12)
        title = QLabel("运行环境", self)
        title.setObjectName("pageTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)

        self._registry_box = QComboBox(self)
        self._registry_box.setObjectName("toolRegistry")
        self._registry_box.setFixedSize(112, 30)
        self._registry_box.addItem("官方源", NPM_REGISTRY_OFFICIAL)
        self._registry_box.addItem("国内镜像", NPM_REGISTRY_MIRROR)
        index = self._registry_box.findData(self._config.npm_registry)
        self._registry_box.setCurrentIndex(max(0, index))
        self._registry_box.setToolTip("npm 下载源，切换后对新安装的组件生效")
        self._registry_box.currentIndexChanged.connect(self._on_registry_changed)
        title_row.addWidget(self._registry_box, 0, Qt.AlignmentFlag.AlignVCenter)

        open_root = QPushButton("打开目录", self)
        open_root.setObjectName("toolAction")
        open_root.setFixedSize(84, 32)
        open_root.setCursor(Qt.CursorShape.PointingHandCursor)
        open_root.clicked.connect(self._open_root)
        title_row.addWidget(open_root, 0, Qt.AlignmentFlag.AlignVCenter)

        refresh = QPushButton("重新检测", self)
        refresh.setObjectName("toolAction")
        refresh.setFixedSize(84, 32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.refresh)
        title_row.addWidget(refresh, 0, Qt.AlignmentFlag.AlignVCenter)

        self._install_all_button = QPushButton("一键安装全部", self)
        self._install_all_button.setObjectName("toolPrimary")
        self._install_all_button.setFixedSize(112, 32)
        self._install_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_all_button.setToolTip("依次安装 Node 和 7 个 Agent CLI")
        self._install_all_button.clicked.connect(self._install_all)
        title_row.addWidget(
            self._install_all_button, 0, Qt.AlignmentFlag.AlignVCenter
        )
        heading.addLayout(title_row)

        subtitle = QLabel(
            "把 Node 和 7 个 Agent CLI 装进安装目录的 runtime/，免管理员权限，"
            "不修改系统 PATH；装好后可在「Agent 启动」里直接使用。",
            self,
        )
        subtitle.setObjectName("pageSubtitle")
        subtitle.setWordWrap(True)
        heading.addWidget(subtitle)
        layout.addLayout(heading)

        layout.addSpacing(14)

        scroll = QScrollArea(self)
        scroll.setObjectName("listArea")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setObjectName("listHost")
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 6, 6)
        host_layout.setSpacing(8)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        host_layout.addWidget(self._section(host, "基础环境"))
        node_row = self._add_row(
            host_layout, NODE_ID, "Node 运行环境", "便携 Node.js LTS，Agent CLI 的运行基础"
        )
        node_row.open_requested.connect(self._open_component)
        host_layout.addWidget(node_row)

        host_layout.addSpacing(8)
        host_layout.addWidget(
            self._section(host, "Agent CLI", "全部为官方 npm 包，安装到 runtime/agents。")
        )
        for spec in NPM_TOOLS:
            row = self._add_row(host_layout, spec.id, spec.name, spec.summary)
            host_layout.addWidget(row)

        host_layout.addSpacing(8)
        host_layout.addWidget(
            self._section(
                host,
                "其他工具",
                "cc-switch 为独立便携应用，AgentBell 不代装；点右侧按钮到 GitHub 下载。",
            )
        )
        host_layout.addWidget(
            _ExternalRow(
                "cc-switch",
                "在 Claude Code / Codex 之间切换供应商",
                CC_SWITCH_URL,
                host,
            )
        )

        host_layout.addSpacing(8)
        host_layout.addWidget(
            self._section(
                host,
                "DeepSeek 预设",
                "DeepSeek 没有官方 CLI；把它的 API 作为供应商注入 Claude Code 启动环境。",
            )
        )
        host_layout.addWidget(self._build_provider_panel(host))
        host_layout.addStretch(1)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 8, 0, 0)
        status_row.setSpacing(10)
        self._progress = QProgressBar(self)
        self._progress.setObjectName("toolProgress")
        self._progress.setTextVisible(False)
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.hide()
        status_row.addWidget(self._progress, 2)
        self._status = QLabel("", self)
        self._status.setObjectName("toolHint")
        self._status.setWordWrap(True)
        self._status.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_row.addWidget(self._status, 3)
        layout.addLayout(status_row)

    def _section(self, parent: QWidget, title: str, hint: str = "") -> QWidget:
        host = QWidget(parent)
        box = QVBoxLayout(host)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        label = QLabel(title, host)
        label.setObjectName("toolHint")
        box.addWidget(label)
        if hint:
            detail = QLabel(hint, host)
            detail.setObjectName("toolHint")
            detail.setWordWrap(True)
            box.addWidget(detail)
        return host

    def _add_row(
        self, layout: QVBoxLayout, component_id: str, name: str, summary: str
    ) -> _ToolRow:
        row = _ToolRow(component_id, name, summary)
        row.install_requested.connect(self._install)
        row.uninstall_requested.connect(self._uninstall)
        self._rows[component_id] = row
        return row

    def _build_provider_panel(self, parent: QWidget) -> QWidget:
        panel = QFrame(parent)
        panel.setObjectName("toolRow")
        box = QVBoxLayout(panel)
        box.setContentsMargins(14, 12, 12, 12)
        box.setSpacing(8)

        key_row = QHBoxLayout()
        key_row.setContentsMargins(0, 0, 0, 0)
        key_row.setSpacing(8)
        self._key_input = QLineEdit(panel)
        self._key_input.setObjectName("toolKey")
        self._key_input.setFixedHeight(32)
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("sk-…（DeepSeek API Key，仅保存在本机）")
        self._key_input.setClearButtonEnabled(True)
        key_row.addWidget(self._key_input, 1)

        save = QPushButton("保存", panel)
        save.setObjectName("toolAction")
        save.setFixedSize(64, 32)
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.clicked.connect(self._save_key)
        key_row.addWidget(save)

        clear = QPushButton("清除", panel)
        clear.setObjectName("toolAction")
        clear.setFixedSize(64, 32)
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self._clear_key)
        key_row.addWidget(clear)
        box.addLayout(key_row)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(8)
        self._provider_launch = QPushButton("用 DeepSeek 启动 Claude Code", panel)
        self._provider_launch.setObjectName("toolPrimary")
        self._provider_launch.setFixedHeight(30)
        self._provider_launch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._provider_launch.clicked.connect(self._launch_deepseek)
        action_row.addWidget(self._provider_launch)

        copy_toml = QPushButton("复制 Codex 配置片段", panel)
        copy_toml.setObjectName("toolAction")
        copy_toml.setFixedHeight(30)
        copy_toml.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_toml.clicked.connect(self._copy_codex_toml)
        action_row.addWidget(copy_toml)
        action_row.addStretch(1)
        box.addLayout(action_row)

        self._provider_hint = QLabel("", panel)
        self._provider_hint.setObjectName("toolHint")
        self._provider_hint.setWordWrap(True)
        box.addWidget(self._provider_hint)
        self._sync_provider_hint()
        return panel

    # ---------- state ----------

    def apply_config(self, config: ToolchainConfig) -> None:
        if config.npm_registry != self._config.npm_registry:
            self._service = self._make_service(config)
            index = self._registry_box.findData(config.npm_registry)
            if index >= 0:
                self._registry_box.blockSignals(True)
                self._registry_box.setCurrentIndex(index)
                self._registry_box.blockSignals(False)
        self._config = config
        self._sync_provider_hint()

    def notify(self, message: str, error: bool = False) -> None:
        self._set_status(message, error=error)

    def refresh(self) -> None:
        state = self._service.state()
        self._rows[NODE_ID].set_state(state.node, self._busy)
        for tool in state.tools:
            row = self._rows.get(tool.id)
            if row is not None:
                row.set_state(tool, self._busy)
        if not self._busy:
            installed = sum(
                1 for item in (state.node, *state.tools) if item.installed
            )
            self._set_status(f"已安装 {installed}/8 个组件 · {state.root}")

    def _sync_provider_hint(self) -> None:
        key = reveal_secret(self._config.deepseek_key)
        self._provider_launch.setEnabled(bool(key))
        if key:
            self._provider_hint.setText(
                "已保存 DeepSeek Key；点左侧按钮会用该供应商打开 Claude Code 终端。"
            )
        else:
            self._provider_hint.setText(
                "未保存 Key。保存后可直接用 DeepSeek 启动 Claude Code。"
            )

    # ---------- jobs ----------

    def _install(self, component_id: str) -> None:
        if self._busy:
            return
        label = self._label(component_id)
        if component_id == NODE_ID:
            work: Callable[[Callable[[Progress], None]], str] = (
                lambda report: self._service.install_node(report)
            )
        else:
            work = lambda report: self._service.install_tool(component_id, report)  # noqa: E731
        self._start(f"正在安装 {label}", work)

    def _uninstall(self, component_id: str) -> None:
        if self._busy:
            return
        label = self._label(component_id)
        work = lambda report: self._service.uninstall(component_id, report)  # noqa: E731
        self._start(f"正在卸载 {label}", work)

    def _install_all(self) -> None:
        if self._busy:
            return
        plan = [NODE_ID, *(spec.id for spec in NPM_TOOLS)]

        def work(report: Callable[[Progress], None]) -> str:
            for component_id in plan:
                if component_id == NODE_ID:
                    self._service.install_node(report)
                else:
                    self._service.install_tool(component_id, report)
            return "全部组件安装完成"

        self._start("正在安装全部组件", work)

    def _start(
        self,
        label: str,
        work: Callable[[Callable[[Progress], None]], str],
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._set_busy(True)
        self._set_status(label)

        def report(progress: Progress) -> None:
            self._signals.progress.emit(progress)

        def runner() -> None:
            try:
                message = work(report)
            except ToolchainError as exc:
                self._signals.failed.emit(str(exc))
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("toolchain job failed")
                self._signals.failed.emit(f"操作失败：{exc}")
            else:
                self._signals.done.emit(message)

        self._thread = threading.Thread(target=runner, name="toolchain", daemon=True)
        self._thread.start()

    def _on_progress(self, progress: Progress) -> None:
        detail = f" · {progress.detail}" if progress.detail else ""
        self._set_status(f"{progress.stage}{detail}")
        if progress.percent < 0:
            self._progress.setRange(0, 0)
        else:
            self._progress.setRange(0, 100)
            self._progress.setValue(max(0, min(100, progress.percent)))

    def _on_done(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message)
        self.refresh()
        self.changed.emit()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message, error=True)
        self.refresh()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._progress.setVisible(busy)
        self._install_all_button.setEnabled(not busy)
        self._registry_box.setEnabled(not busy)
        for row in self._rows.values():
            row.setEnabled(not busy)

    def _set_status(self, text: str, error: bool = False) -> None:
        self._status.setText(text)
        self._status.setProperty("state", "error" if error else "ok")
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)

    # ---------- actions ----------

    def _label(self, component_id: str) -> str:
        state = self._service.state().component(component_id)
        return state.name if state is not None else component_id

    def _open_root(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._root)))

    def _open_component(self, component_id: str) -> None:
        state = self._service.state().component(component_id)
        if state is None or not state.path:
            return
        target = Path(state.path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.parent)))

    def _on_registry_changed(self) -> None:
        value = str(self._registry_box.currentData() or NPM_REGISTRY_OFFICIAL)
        if value == self._config.npm_registry:
            return
        self.config_patch_requested.emit({"npm_registry": value})

    def _save_key(self) -> None:
        key = self._key_input.text().strip()
        if not key:
            self._set_status("请先填写 DeepSeek API Key", error=True)
            return
        self._key_input.clear()
        self.config_patch_requested.emit({"deepseek_key": protect_secret(key)})
        self._set_status("DeepSeek Key 已加密保存到本机配置")

    def _clear_key(self) -> None:
        self.config_patch_requested.emit({"deepseek_key": ""})
        self._set_status("已清除 DeepSeek Key")

    def _launch_deepseek(self) -> None:
        key = reveal_secret(self._config.deepseek_key)
        if not key:
            self._set_status("请先保存 DeepSeek API Key", error=True)
            return
        self.provider_launch_requested.emit(deepseek_claude_env(key))

    def _copy_codex_toml(self) -> None:
        QGuiApplication.clipboard().setText(DEEPSEEK_CODEX_TOML)
        self._set_status("Codex 配置片段已复制到剪贴板")
