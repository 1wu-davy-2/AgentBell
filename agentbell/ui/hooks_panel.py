from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..hooks import (
    HookError,
    HookStatus,
    hook_statuses,
    install_hook,
    plan_install,
    plan_uninstall,
    uninstall_hook,
)

CONFIRM = Callable[[str, str, str], bool]


class _HookRow(QFrame):
    install_requested = Signal(str)
    uninstall_requested = Signal(str)

    def __init__(self, status: HookStatus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("toolRow")
        self.agent_id = status.agent.id

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(10)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(2)
        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        name = QLabel(status.agent.name, self)
        name.setObjectName("toolName")
        title_row.addWidget(name)
        support = QLabel(
            "完整" if status.agent.support == "full" else "部分", self
        )
        support.setObjectName("toolChip")
        if status.agent.support != "full":
            support.setProperty("tone", "partial")
        support.setToolTip(status.agent.note)
        title_row.addWidget(support)
        title_row.addStretch(1)
        self._state = QLabel("", self)
        self._state.setObjectName("toolChip")
        title_row.addWidget(self._state)
        text.addLayout(title_row)

        summary = QLabel(status.agent.note, self)
        summary.setObjectName("toolSummary")
        text.addWidget(summary)
        self._path = QLabel("", self)
        self._path.setObjectName("toolMeta")
        self._path.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        text.addWidget(self._path)
        self._problem = QLabel("", self)
        self._problem.setObjectName("toolProblem")
        self._problem.setWordWrap(True)
        self._problem.hide()
        text.addWidget(self._problem)
        layout.addLayout(text, 1)

        self._remove_button = QPushButton("撤销", self)
        self._remove_button.setObjectName("toolAction")
        self._remove_button.setFixedHeight(28)
        self._remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._remove_button.clicked.connect(
            lambda: self.uninstall_requested.emit(self.agent_id)
        )
        self._remove_button.hide()
        layout.addWidget(self._remove_button)

        self._install_button = QPushButton("接入", self)
        self._install_button.setObjectName("toolPrimary")
        self._install_button.setFixedHeight(28)
        self._install_button.setMinimumWidth(72)
        self._install_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_button.clicked.connect(
            lambda: self.install_requested.emit(self.agent_id)
        )
        layout.addWidget(self._install_button)

        self.set_status(status)

    def set_status(self, status: HookStatus) -> None:
        if status.installed:
            state = "已接入"
        elif status.problem:
            state = "需处理"
        elif status.detected:
            state = "未接入"
        else:
            state = "未检测到"
        self._state.setText(state)
        self._state.setProperty("installed", "true" if status.installed else "false")
        self._state.setProperty("state", "error" if status.problem else "ok")
        self._state.style().unpolish(self._state)
        self._state.style().polish(self._state)
        self._state.setToolTip(status.problem)
        self._path.setText(str(status.config_path))
        self._path.setToolTip(str(status.config_path))
        self._problem.setText(status.problem)
        self._problem.setVisible(bool(status.problem))
        self._remove_button.setVisible(status.installed)
        self._install_button.setVisible(not status.installed)
        if status.problem:
            self._install_button.setText("需处理")
        elif status.agent.support == "partial":
            self._install_button.setText("接入结束提醒")
        else:
            self._install_button.setText("接入")
        self._install_button.setEnabled(not bool(status.problem))


class HooksPanel(QWidget):
    status_message = Signal(str, bool)

    def __init__(
        self,
        root: Path,
        logger: logging.Logger,
        parent: QWidget | None = None,
        *,
        home: Path | None = None,
        confirm: CONFIRM | None = None,
    ) -> None:
        super().__init__(parent)
        self._root = Path(root)
        self._logger = logger
        self._home = home
        self._confirm = confirm or self._ask_confirm
        self._rows: dict[str, _HookRow] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        hint = QLabel(
            "接入后可在 Agent 等待确认、等待回答或每轮结束时自动提醒；"
            "写入前会备份原配置，可随时撤销。",
            self,
        )
        hint.setObjectName("toolHint")
        hint.setWordWrap(True)
        header.addWidget(hint, 1)
        self._install_all_button = QPushButton("接入全部", self)
        self._install_all_button.setObjectName("toolPrimary")
        self._install_all_button.setFixedHeight(28)
        self._install_all_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._install_all_button.setToolTip(
            "接入 Claude Code、Gemini CLI 和 Grok；Codex 仅支持结束提醒，请单独接入"
        )
        self._install_all_button.clicked.connect(self._install_all)
        header.addWidget(self._install_all_button)
        layout.addLayout(header)

        for status in self._statuses():
            row = _HookRow(status, self)
            row.install_requested.connect(self._install)
            row.uninstall_requested.connect(self._uninstall)
            self._rows[status.agent.id] = row
            layout.addWidget(row)

        footer = QLabel(
            "所有 Hook 都只调用本机 AgentBell，不会批准权限、自动继续或发送提示词；"
            "Codex 只能感知每轮结束。",
            self,
        )
        footer.setObjectName("toolHint")
        footer.setWordWrap(True)
        layout.addWidget(footer)
        self.refresh()

    def _statuses(self) -> tuple[HookStatus, ...]:
        return hook_statuses(home=self._home, root=self._root)

    def refresh(self) -> None:
        statuses = {status.agent.id: status for status in self._statuses()}
        for agent_id, row in self._rows.items():
            status = statuses.get(agent_id)
            if status is not None:
                row.set_status(status)
        self._install_all_button.setEnabled(
            any(
                status.detected and not status.installed and not status.problem
                for agent_id, status in statuses.items()
                if agent_id != "codex"
            )
        )

    def _ask_confirm(self, title: str, text: str, preview: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(text)
        box.setDetailedText(preview)
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.Yes)
        box.button(QMessageBox.StandardButton.Yes).setText("继续")
        box.button(QMessageBox.StandardButton.No).setText("取消")
        return box.exec() == QMessageBox.StandardButton.Yes

    def _install(self, agent_id: str) -> None:
        try:
            plan = plan_install(agent_id, home=self._home, root=self._root)
        except HookError as exc:
            self.status_message.emit(str(exc), True)
            return
        warnings = "\n".join(plan.warnings)
        text = (
            f"将修改 {plan.agent.name} 的配置：\n{plan.config_path}\n\n"
            "原文件会先备份；只追加带 AgentBell 标记的 Hook。"
        )
        if warnings:
            text += f"\n\n{warnings}"
        if not self._confirm("接入等待提醒", text, plan.preview):
            return
        try:
            result = install_hook(agent_id, home=self._home, root=self._root)
        except HookError as exc:
            self.status_message.emit(str(exc), True)
            return
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("hook install failed")
            self.status_message.emit(f"接入失败：{exc}", True)
            return
        self.refresh()
        self.status_message.emit(result.message, False)

    def _install_all(self) -> None:
        targets = [
            status
            for status in self._statuses()
            if status.agent.support == "full"
            and status.detected
            and not status.installed
            and not status.problem
        ]
        if not targets:
            self.status_message.emit("没有可接入的 Agent 配置目录", True)
            return
        plans = []
        for status in targets:
            try:
                plans.append(plan_install(status.agent.id, home=self._home, root=self._root))
            except HookError as exc:
                self.status_message.emit(str(exc), True)
                return
        preview = "\n\n".join(
            f"== {plan.agent.name} ==\n{plan.preview}" for plan in plans
        )
        text = "将接入：" + "、".join(plan.agent.name for plan in plans)
        text += "\n每个配置文件都会先备份，只追加 AgentBell Hook。"
        if not self._confirm("接入全部提醒", text, preview):
            return
        failures = []
        installed = 0
        for plan in plans:
            try:
                result = install_hook(
                    plan.agent.id, home=self._home, root=self._root
                )
            except Exception as exc:  # noqa: BLE001
                self._logger.exception("hook install failed")
                failures.append(f"{plan.agent.name}：{exc}")
            else:
                if result.changed:
                    installed += 1
        self.refresh()
        if failures:
            self.status_message.emit("；".join(failures), True)
        elif installed:
            self.status_message.emit(f"已接入 {installed} 个 Agent 的提醒", False)
        else:
            self.status_message.emit("所有 Agent 均已接入", False)

    def _uninstall(self, agent_id: str) -> None:
        try:
            plan = plan_uninstall(agent_id, home=self._home, root=self._root)
        except HookError as exc:
            self.status_message.emit(str(exc), True)
            return
        if not self._confirm(
            "撤销提醒接入",
            f"将移除 {plan.agent.name} 配置中的 AgentBell Hook，并先备份原文件。",
            plan.preview,
        ):
            return
        try:
            result = uninstall_hook(agent_id, home=self._home, root=self._root)
        except HookError as exc:
            self.status_message.emit(str(exc), True)
            return
        except Exception as exc:  # noqa: BLE001
            self._logger.exception("hook uninstall failed")
            self.status_message.emit(f"撤销失败：{exc}", True)
            return
        self.refresh()
        self.status_message.emit(result.message, False)
