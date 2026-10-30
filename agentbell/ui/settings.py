from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QPoint, QTime, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    AppConfig,
    ConfigError,
    OverlayAreaConfig,
    config_from_dict,
    config_to_dict,
    save_config,
)
from ..models import (
    OVERLAY_ANCHORS,
    OVERLAY_CARD_WIDTH_DEFAULT,
    OVERLAY_CARD_WIDTH_MAX,
    OVERLAY_CARD_WIDTH_MIN,
    OVERLAY_MARGIN_DEFAULT,
    OVERLAY_MARGIN_MAX,
    OVERLAY_OFFSET_LIMIT,
    POPUP_MODE_LABELS,
    POPUP_MODES,
    POPUP_SKIN_LABELS,
    POPUP_SKINS,
    Notification,
)
from .icons import make_app_icon
from .toast import ToastWindow

_SOUND_KEYS = ("succeeded", "failed", "canceled", "running", "critical")
_SOUND_LABELS = {
    "succeeded": "成功提示音",
    "failed": "失败提示音",
    "canceled": "取消提示音",
    "running": "进行中提示音",
    "critical": "紧急提示音",
}
_TEMPLATE_KEYS = ("succeeded", "failed", "canceled", "running")
_TEMPLATE_LABELS = {
    "succeeded": "成功标题",
    "failed": "失败标题",
    "canceled": "取消标题",
    "running": "进行中标题",
}
_OVERLAY_ANCHOR_LABELS = {
    "center": "居中",
    "top": "上方居中",
    "bottom": "下方居中",
    "left": "左侧居中",
    "right": "右侧居中",
    "top_left": "左上角",
    "top_right": "右上角",
    "bottom_left": "左下角",
    "bottom_right": "右下角",
}

_RULES_EXAMPLE = [
    {
        "name": "失败必须确认",
        "status": "failed",
        "priority": "high",
        "require_ack": True,
    },
    {
        "name": "抓取任务静音",
        "source": "*crawler*",
        "silent": True,
    },
]
_CHANNELS_EXAMPLE = [
    {
        "type": "webhook",
        "url": "https://example.com/hook",
        "when_away": True,
        "min_priority": "high",
    }
]

_DIALOG_QSS = """
QDialog {
    background-color: #FFFFFF;
}
QLabel#dialogTitle {
    font-size: 18px;
    font-weight: 700;
    color: #161A20;
}
QLabel#dialogHint {
    font-size: 11px;
    color: #8A919D;
}
QLabel#editorHint {
    font-size: 10px;
    color: #9AA1AC;
}
QGroupBox {
    border: 1px solid #E6E8EC;
    border-radius: 10px;
    margin-top: 12px;
    padding: 14px 12px 10px 12px;
    font-size: 12px;
    color: #323A45;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0px 4px;
    color: #323A45;
    font-weight: 600;
}
QLineEdit, QSpinBox, QTimeEdit, QPlainTextEdit, QComboBox {
    border: 1px solid #DDE1E8;
    border-radius: 7px;
    padding: 4px 7px;
    font-size: 11px;
    color: #1F2329;
    background-color: #FFFFFF;
    selection-background-color: #2F6FF0;
    selection-color: #FFFFFF;
}
QLineEdit:focus, QSpinBox:focus, QTimeEdit:focus, QPlainTextEdit:focus,
QComboBox:focus {
    border-color: #9DBBF5;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    border: 1px solid #DDE1E8;
    border-radius: 7px;
    background-color: #FFFFFF;
    color: #1F2329;
    selection-background-color: #EAF1FF;
    selection-color: #1F2329;
}
QScrollArea#settingsScroll {
    background-color: #FFFFFF;
    border: none;
}
QWidget#settingsViewport {
    background-color: #FFFFFF;
}
QPlainTextEdit {
    font-family: Consolas, "Cascadia Mono";
    font-size: 10px;
}
QCheckBox {
    font-size: 11px;
    color: #4B5563;
    spacing: 6px;
}
QTabWidget::pane {
    border: 1px solid #E6E8EC;
    border-radius: 10px;
    background-color: #FFFFFF;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    border: none;
    padding: 8px 14px;
    margin-right: 2px;
    font-size: 12px;
    color: #6B7280;
}
QTabBar::tab:selected {
    color: #2F6FF0;
    font-weight: 600;
}
QTabBar::tab:hover {
    color: #323A45;
}
QPushButton#primaryButton {
    background-color: #2F6FF0;
    border: none;
    border-radius: 9px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
    padding: 0px 20px;
}
QPushButton#primaryButton:hover {
    background-color: #1F5FDF;
}
QPushButton#secondaryButton {
    background-color: #FFFFFF;
    border: 1px solid #DDE1E8;
    border-radius: 9px;
    color: #4B5563;
    font-size: 12px;
    padding: 0px 18px;
}
QPushButton#secondaryButton:hover {
    background-color: #F5F6FA;
}
QPushButton#ghostButton {
    background: transparent;
    border: none;
    border-radius: 7px;
    color: #2F6FF0;
    font-size: 10px;
    padding: 0px 8px;
}
QPushButton#ghostButton:hover {
    background-color: #EAF1FF;
}
QPushButton#testButton {
    background-color: #FFFFFF;
    border: 1px solid #2F6FF0;
    border-radius: 8px;
    color: #2F6FF0;
    font-size: 12px;
    padding: 0px 16px;
}
QPushButton#testButton:hover {
    background-color: #EAF1FF;
}
"""


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        config_path: Path | None = None,
        logger: logging.Logger | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self._config_path = Path(config_path) if config_path else None
        self.logger = logger or logging.getLogger("agentbell.settings")
        self.result_config: AppConfig | None = None
        self._preview: ToastWindow | None = None

        self.setWindowTitle("AgentBell 偏好设置")
        self.setWindowIcon(make_app_icon())
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        self.setMinimumSize(760, 620)
        self.resize(780, 660)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel("偏好设置", self)
        title.setObjectName("dialogTitle")
        outer.addWidget(title)
        hint = QLabel(
            "修改后立即生效；监听端口与访问令牌变更需要重启程序。", self
        )
        hint.setObjectName("dialogHint")
        if self._config_path is not None:
            hint.setToolTip(f"配置文件：{self._config_path}")
        outer.addWidget(hint)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(self._scroll_page(self._build_general_tab()), "常规")
        self._tabs.addTab(self._scroll_page(self._build_appearance_tab()), "弹窗外观")
        self._tabs.addTab(self._scroll_page(self._build_policy_tab()), "提醒策略")
        self._tabs.addTab(self._scroll_page(self._build_content_tab()), "模板与声音")
        self._tabs.addTab(self._scroll_page(self._build_agent_tab()), "Agent 会话")
        self._tabs.addTab(self._scroll_page(self._build_rules_tab()), "规则与渠道")
        outer.addWidget(self._tabs, 1)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        self._status_hint = QLabel(
            f"配置文件：{self._config_path}" if self._config_path else "仅校验，不写入文件",
            self,
        )
        self._status_hint.setObjectName("dialogHint")
        buttons.addWidget(self._status_hint, 1)

        self._test_button = QPushButton("测试", self)
        self._test_button.setObjectName("testButton")
        self._test_button.setFixedSize(76, 34)
        self._test_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_button.setToolTip("用当前选择的模式、皮肤和背景图预览弹窗")
        self._test_button.clicked.connect(self._preview_popup)
        buttons.addWidget(self._test_button)

        self._cancel_button = QPushButton("取消", self)
        self._cancel_button.setObjectName("secondaryButton")
        self._cancel_button.setFixedSize(84, 34)
        self._cancel_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_button)

        self._save_button = QPushButton("保存设置", self)
        self._save_button.setObjectName("primaryButton")
        self._save_button.setFixedSize(104, 34)
        self._save_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_button.setDefault(True)
        self._save_button.clicked.connect(self._save)
        buttons.addWidget(self._save_button)
        outer.addLayout(buttons)

        self.setStyleSheet(_DIALOG_QSS)

    # ---------- tabs ----------

    def _scroll_page(self, page: QWidget) -> QScrollArea:
        page.setObjectName("settingsPage")
        palette = page.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#FFFFFF"))
        page.setPalette(palette)
        page.setAutoFillBackground(True)
        area = QScrollArea(self)
        area.setObjectName("settingsScroll")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        area.viewport().setAutoFillBackground(False)
        area.viewport().setObjectName("settingsViewport")
        return area

    def _build_general_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        group = QGroupBox("本地服务", page)
        form = QFormLayout(group)
        form.setContentsMargins(12, 14, 12, 10)
        form.setSpacing(9)

        self._port_spin = QSpinBox(group)
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(self.config.port)
        form.addRow("监听端口", self._port_spin)

        self._token_edit = QLineEdit(self.config.token, group)
        self._token_edit.setPlaceholderText("留空表示不校验 X-Token")
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("访问令牌", self._token_edit)

        self._autostart_check = QCheckBox("登录 Windows 后自动启动", group)
        self._autostart_check.setChecked(self.config.autostart)
        form.addRow("", self._autostart_check)

        self._open_center_check = QCheckBox(
            "启动后自动打开通知中心（带淡入动画）", group
        )
        self._open_center_check.setChecked(self.config.open_center_on_start)
        form.addRow("", self._open_center_check)
        layout.addWidget(group)

        popup = QGroupBox("弹窗行为", page)
        popup_form = QFormLayout(popup)
        popup_form.setContentsMargins(12, 14, 12, 10)
        popup_form.setSpacing(9)

        self._auto_close_spin = QSpinBox(popup)
        self._auto_close_spin.setRange(0, 3600)
        self._auto_close_spin.setSuffix(" 秒")
        self._auto_close_spin.setValue(self.config.auto_close_seconds)
        popup_form.addRow("自动关闭时间", self._auto_close_spin)

        self._cooldown_spin = QSpinBox(popup)
        self._cooldown_spin.setRange(0, 3600)
        self._cooldown_spin.setSuffix(" 秒")
        self._cooldown_spin.setValue(self.config.popup_cooldown_seconds)
        popup_form.addRow("两次弹窗冷却", self._cooldown_spin)

        self._success_popup_check = QCheckBox(
            "成功任务也弹出置顶提醒（关闭后仅进入通知中心）", popup
        )
        self._success_popup_check.setChecked(self.config.success_popup)
        popup_form.addRow("", self._success_popup_check)

        self._require_ack_check = QCheckBox(
            "通知默认需要点击「知道了」才会消失", popup
        )
        self._require_ack_check.setChecked(self.config.require_ack_by_default)
        popup_form.addRow("", self._require_ack_check)

        self._hotkey_edit = QLineEdit(self.config.hotkey, popup)
        self._hotkey_edit.setPlaceholderText("例如 Ctrl+Alt+A，留空禁用")
        popup_form.addRow("全局快捷键", self._hotkey_edit)
        layout.addWidget(popup)

        layout.addStretch(1)
        return page

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        mode_group = QGroupBox("弹出模式", page)
        mode_form = QFormLayout(mode_group)
        mode_form.setContentsMargins(12, 14, 12, 10)
        mode_form.setSpacing(9)

        self._popup_mode_combo = QComboBox(mode_group)
        for key in POPUP_MODES:
            self._popup_mode_combo.addItem(POPUP_MODE_LABELS[key], key)
        index = self._popup_mode_combo.findData(self.config.popup_mode)
        self._popup_mode_combo.setCurrentIndex(max(0, index))
        mode_form.addRow("默认模式", self._popup_mode_combo)

        mode_hint = QLabel(
            "右侧卡片：从屏幕右侧滑入，按倒计时自动关闭。\n"
            "居中确认：屏幕中央弹出，必须点击「知道了」才会消失。\n"
            "全屏遮挡：半透明遮罩铺满屏幕，卡片位置与宽度可在下方设置，需手动确认。",
            mode_group,
        )
        mode_hint.setObjectName("editorHint")
        mode_hint.setWordWrap(True)
        mode_form.addRow("", mode_hint)
        layout.addWidget(mode_group)

        skin_group = QGroupBox("弹窗皮肤", page)
        skin_form = QFormLayout(skin_group)
        skin_form.setContentsMargins(12, 14, 12, 10)
        skin_form.setSpacing(9)
        self._popup_skin_combo = QComboBox(skin_group)
        for key in POPUP_SKINS:
            self._popup_skin_combo.addItem(POPUP_SKIN_LABELS[key], key)
        index = self._popup_skin_combo.findData(self.config.popup_skin)
        self._popup_skin_combo.setCurrentIndex(max(0, index))
        skin_form.addRow("默认皮肤", self._popup_skin_combo)

        skin_hint = QLabel(
            "皮肤决定卡片的底色与文字配色；单个通知或规则可通过 "
            "popup_mode / popup_skin 字段覆盖默认值。",
            skin_group,
        )
        skin_hint.setObjectName("editorHint")
        skin_hint.setWordWrap(True)
        skin_form.addRow("", skin_hint)
        layout.addWidget(skin_group)

        image_group = QGroupBox("全屏背景图", page)
        image_form = QFormLayout(image_group)
        image_form.setContentsMargins(12, 14, 12, 10)
        image_form.setSpacing(9)

        image_row = QWidget(image_group)
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(6)
        self._overlay_image_edit = QLineEdit(self.config.overlay_image, image_row)
        self._overlay_image_edit.setPlaceholderText(
            "留空使用内置渐变；支持 PNG / JPG / BMP / WebP"
        )
        image_layout.addWidget(self._overlay_image_edit, 1)
        self._choose_image_button = QPushButton("选择图片", image_row)
        self._choose_image_button.setObjectName("ghostButton")
        self._choose_image_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._choose_image_button.clicked.connect(self._choose_overlay_image)
        image_layout.addWidget(self._choose_image_button)
        self._clear_image_button = QPushButton("清除", image_row)
        self._clear_image_button.setObjectName("ghostButton")
        self._clear_image_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear_image_button.clicked.connect(
            lambda: self._overlay_image_edit.clear()
        )
        image_layout.addWidget(self._clear_image_button)
        image_form.addRow("背景图片", image_row)

        image_hint = QLabel(
            "图片会按比例铺满整个屏幕并自动裁切，叠加暗色遮罩保证文字可读；"
            "仅在「全屏遮挡」模式下生效。",
            image_group,
        )
        image_hint.setObjectName("editorHint")
        image_hint.setWordWrap(True)
        image_form.addRow("", image_hint)
        layout.addWidget(image_group)

        area_group = QGroupBox("全屏显示区域", page)
        area_form = QFormLayout(area_group)
        area_form.setContentsMargins(12, 14, 12, 10)
        area_form.setSpacing(9)

        self._overlay_anchor_combo = QComboBox(area_group)
        for key in OVERLAY_ANCHORS:
            self._overlay_anchor_combo.addItem(
                _OVERLAY_ANCHOR_LABELS.get(key, key), key
            )
        index = self._overlay_anchor_combo.findData(self.config.overlay_area.anchor)
        self._overlay_anchor_combo.setCurrentIndex(max(0, index))
        area_form.addRow("位置", self._overlay_anchor_combo)

        self._overlay_width_spin = QSpinBox(area_group)
        self._overlay_width_spin.setRange(0, OVERLAY_CARD_WIDTH_MAX)
        self._overlay_width_spin.setSingleStep(20)
        self._overlay_width_spin.setSuffix(" px")
        self._overlay_width_spin.setSpecialValueText(
            f"默认（{OVERLAY_CARD_WIDTH_DEFAULT} px）"
        )
        self._overlay_width_spin.setValue(self.config.overlay_area.width)
        self._overlay_width_spin.valueChanged.connect(self._snap_overlay_width)
        area_form.addRow("卡片宽度", self._overlay_width_spin)

        self._overlay_margin_spin = QSpinBox(area_group)
        self._overlay_margin_spin.setRange(0, OVERLAY_MARGIN_MAX)
        self._overlay_margin_spin.setSuffix(" px")
        self._overlay_margin_spin.setValue(self.config.overlay_area.margin)
        area_form.addRow("与屏幕边缘距离", self._overlay_margin_spin)

        self._overlay_offset_x_spin = QSpinBox(area_group)
        self._overlay_offset_x_spin.setRange(-OVERLAY_OFFSET_LIMIT, OVERLAY_OFFSET_LIMIT)
        self._overlay_offset_x_spin.setSuffix(" px")
        self._overlay_offset_x_spin.setValue(self.config.overlay_area.offset_x)
        area_form.addRow("水平微调", self._overlay_offset_x_spin)

        self._overlay_offset_y_spin = QSpinBox(area_group)
        self._overlay_offset_y_spin.setRange(-OVERLAY_OFFSET_LIMIT, OVERLAY_OFFSET_LIMIT)
        self._overlay_offset_y_spin.setSuffix(" px")
        self._overlay_offset_y_spin.setValue(self.config.overlay_area.offset_y)
        area_form.addRow("垂直微调", self._overlay_offset_y_spin)

        area_hint = QLabel(
            "仅「全屏遮挡」模式生效。卡片高度随内容自动；位置以九宫格为基准，"
            "再用微调移动到任意位置。修改后点击底部「测试」立即预览。",
            area_group,
        )
        area_hint.setObjectName("editorHint")
        area_hint.setWordWrap(True)
        area_form.addRow("", area_hint)
        layout.addWidget(area_group)

        layout.addStretch(1)
        return page

    def _snap_overlay_width(self, value: int) -> None:
        if 0 < value < OVERLAY_CARD_WIDTH_MIN:
            self._overlay_width_spin.setValue(OVERLAY_CARD_WIDTH_MIN)

    def _overlay_area_from_controls(self) -> OverlayAreaConfig:
        return OverlayAreaConfig(
            anchor=self._overlay_anchor_combo.currentData(),
            width=self._overlay_width_spin.value(),
            offset_x=self._overlay_offset_x_spin.value(),
            offset_y=self._overlay_offset_y_spin.value(),
            margin=self._overlay_margin_spin.value(),
        )

    def _choose_overlay_image(self) -> None:
        current = self._overlay_image_edit.text().strip()
        start = current or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择全屏背景图片",
            start,
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp);;所有文件 (*)",
        )
        if path:
            self._overlay_image_edit.setText(path)

    def _build_policy_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        quiet = QGroupBox("免打扰时段", page)
        quiet_layout = QVBoxLayout(quiet)
        quiet_layout.setContentsMargins(12, 14, 12, 10)
        quiet_layout.setSpacing(8)

        self._quiet_enabled_check = QCheckBox(
            "启用免打扰（期间通知只记录，不弹窗）", quiet
        )
        self._quiet_enabled_check.setChecked(self.config.quiet_hours.enabled)
        quiet_layout.addWidget(self._quiet_enabled_check)

        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(8)
        time_row.addWidget(QLabel("开始", quiet))
        self._quiet_start_edit = QTimeEdit(quiet)
        self._quiet_start_edit.setDisplayFormat("HH:mm")
        self._quiet_start_edit.setTime(
            QTime.fromString(self.config.quiet_hours.start, "HH:mm")
        )
        time_row.addWidget(self._quiet_start_edit)
        time_row.addSpacing(12)
        time_row.addWidget(QLabel("结束", quiet))
        self._quiet_end_edit = QTimeEdit(quiet)
        self._quiet_end_edit.setDisplayFormat("HH:mm")
        self._quiet_end_edit.setTime(
            QTime.fromString(self.config.quiet_hours.end, "HH:mm")
        )
        time_row.addWidget(self._quiet_end_edit)
        time_row.addStretch(1)
        quiet_layout.addLayout(time_row)

        self._quiet_critical_check = QCheckBox("紧急通知不受免打扰限制", quiet)
        self._quiet_critical_check.setChecked(
            self.config.quiet_hours.allow_critical
        )
        quiet_layout.addWidget(self._quiet_critical_check)
        layout.addWidget(quiet)

        suppress = QGroupBox("自动抑制", page)
        suppress_form = QFormLayout(suppress)
        suppress_form.setContentsMargins(12, 14, 12, 10)
        suppress_form.setSpacing(9)

        self._fullscreen_check = QCheckBox(
            "全屏应用或会议中暂缓弹窗，结束后补发", suppress
        )
        self._fullscreen_check.setChecked(self.config.suppress_fullscreen)
        suppress_form.addRow("", self._fullscreen_check)

        self._meeting_edit = QLineEdit(
            ", ".join(self.config.meeting_processes), suppress
        )
        self._meeting_edit.setPlaceholderText("zoom.exe, teams.exe")
        suppress_form.addRow("会议进程", self._meeting_edit)

        self._hold_when_locked_check = QCheckBox(
            "锁屏或息屏时保留提醒（弹窗不消失，解锁后继续计时）", suppress
        )
        self._hold_when_locked_check.setChecked(self.config.hold_when_locked)
        suppress_form.addRow("", self._hold_when_locked_check)

        self._away_spin = QSpinBox(suppress)
        self._away_spin.setRange(0, 86400)
        self._away_spin.setSuffix(" 秒")
        self._away_spin.setValue(self.config.away_idle_seconds)
        suppress_form.addRow("离开判定", self._away_spin)
        layout.addWidget(suppress)

        pacing = QGroupBox("聚合与提醒升级", page)
        pacing_form = QFormLayout(pacing)
        pacing_form.setContentsMargins(12, 14, 12, 10)
        pacing_form.setSpacing(9)

        self._digest_check = QCheckBox("短时间多条通知合并为摘要弹窗", pacing)
        self._digest_check.setChecked(self.config.digest.enabled)
        pacing_form.addRow("", self._digest_check)

        self._digest_threshold_spin = QSpinBox(pacing)
        self._digest_threshold_spin.setRange(2, 50)
        self._digest_threshold_spin.setValue(self.config.digest.threshold)
        pacing_form.addRow("聚合阈值（条）", self._digest_threshold_spin)

        self._digest_window_spin = QSpinBox(pacing)
        self._digest_window_spin.setRange(5, 3600)
        self._digest_window_spin.setSuffix(" 秒")
        self._digest_window_spin.setValue(self.config.digest.window_seconds)
        pacing_form.addRow("聚合时间窗口", self._digest_window_spin)

        self._escalation_spin = QSpinBox(pacing)
        self._escalation_spin.setRange(0, 86400)
        self._escalation_spin.setSuffix(" 秒")
        self._escalation_spin.setSpecialValueText("关闭")
        self._escalation_spin.setValue(self.config.escalation.unread_seconds)
        pacing_form.addRow("未确认升级间隔", self._escalation_spin)

        self._escalation_times_spin = QSpinBox(pacing)
        self._escalation_times_spin.setRange(0, 20)
        self._escalation_times_spin.setValue(self.config.escalation.max_times)
        pacing_form.addRow("最多升级次数", self._escalation_times_spin)

        self._flash_check = QCheckBox("升级时闪烁托盘图标", pacing)
        self._flash_check.setChecked(self.config.escalation.flash_tray)
        pacing_form.addRow("", self._flash_check)

        self._escalation_sound_check = QCheckBox("升级时播放提示音", pacing)
        self._escalation_sound_check.setChecked(self.config.escalation.sound)
        pacing_form.addRow("", self._escalation_sound_check)
        layout.addWidget(pacing)

        layout.addStretch(1)
        return page

    def _build_content_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        templates = QGroupBox("弹窗标题模板", page)
        template_form = QFormLayout(templates)
        template_form.setContentsMargins(12, 14, 12, 10)
        template_form.setSpacing(9)
        self._template_edits: dict[str, QLineEdit] = {}
        for key in _TEMPLATE_KEYS:
            edit = QLineEdit(self.config.templates.get(key, ""), templates)
            edit.setPlaceholderText("必须包含 {title} 占位符")
            template_form.addRow(_TEMPLATE_LABELS[key], edit)
            self._template_edits[key] = edit
        layout.addWidget(templates)

        sounds = QGroupBox("状态提示音（WAV 文件，留空不播放）", page)
        sound_layout = QVBoxLayout(sounds)
        sound_layout.setContentsMargins(12, 14, 12, 10)
        sound_layout.setSpacing(7)
        self._sound_edits: dict[str, QLineEdit] = {}
        for key in _SOUND_KEYS:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            label = QLabel(_SOUND_LABELS[key], sounds)
            label.setFixedWidth(84)
            row.addWidget(label)
            edit = QLineEdit(self.config.sounds.get(key, ""), sounds)
            edit.setPlaceholderText("选择 .wav 文件")
            row.addWidget(edit, 1)
            browse = QPushButton("浏览…", sounds)
            browse.setObjectName("secondaryButton")
            browse.setFixedSize(64, 28)
            browse.setCursor(Qt.CursorShape.PointingHandCursor)
            browse.clicked.connect(
                lambda checked=False, target=edit: self._browse_sound(target)
            )
            row.addWidget(browse)
            sound_layout.addLayout(row)
            self._sound_edits[key] = edit
        layout.addWidget(sounds)

        layout.addStretch(1)
        return page

    def _build_agent_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        group = QGroupBox("会话扫描", page)
        form = QFormLayout(group)
        form.setContentsMargins(12, 14, 12, 10)
        form.setSpacing(9)

        self._agent_enabled_check = QCheckBox(
            "扫描本机 Claude Code 与 Qoder 的会话目录", group
        )
        self._agent_enabled_check.setChecked(self.config.agent_sessions.enabled)
        form.addRow("", self._agent_enabled_check)

        self._agent_interval_spin = QSpinBox(group)
        self._agent_interval_spin.setRange(30, 3600)
        self._agent_interval_spin.setSuffix(" 秒")
        self._agent_interval_spin.setValue(
            self.config.agent_sessions.scan_interval_seconds
        )
        form.addRow("扫描间隔", self._agent_interval_spin)

        self._agent_max_spin = QSpinBox(group)
        self._agent_max_spin.setRange(10, 500)
        self._agent_max_spin.setValue(self.config.agent_sessions.max_sessions)
        form.addRow("最多会话数", self._agent_max_spin)

        hint = QLabel(
            "只读取会话文件的名称、项目路径、更新时间与消息条数，"
            "不解析、不上传对话内容。扫描结果展示在通知中心的「Agent 会话」页。",
            group,
        )
        hint.setObjectName("editorHint")
        hint.setWordWrap(True)
        form.addRow("", hint)

        paths = QLabel(
            "扫描位置：~/.claude/projects/*/*.jsonl 与 ~/.qoder/projects/*/*/state.json",
            group,
        )
        paths.setObjectName("editorHint")
        paths.setWordWrap(True)
        form.addRow("", paths)
        layout.addWidget(group)

        layout.addStretch(1)
        return page

    def _build_rules_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        rules_header = QHBoxLayout()
        rules_header.setContentsMargins(0, 0, 0, 0)
        rules_title = QLabel("匹配规则（JSON 数组，从上到下匹配）", page)
        rules_title.setObjectName("dialogHint")
        rules_header.addWidget(rules_title, 1)
        rules_example = QPushButton("填入示例", page)
        rules_example.setObjectName("ghostButton")
        rules_example.setFixedHeight(24)
        rules_example.setCursor(Qt.CursorShape.PointingHandCursor)
        rules_example.clicked.connect(
            lambda: self._fill_example(self._rules_editor, _RULES_EXAMPLE)
        )
        rules_header.addWidget(rules_example)
        layout.addLayout(rules_header)

        self._rules_editor = QPlainTextEdit(page)
        self._rules_editor.setPlaceholderText("[]")
        self._rules_editor.setPlainText(
            json.dumps(config_to_dict(self.config)["rules"], ensure_ascii=False, indent=2)
        )
        layout.addWidget(self._rules_editor, 1)

        hint = QLabel(
            "可用字段：name, source, title_contains, status, priority, silent, "
            "require_ack, auto_close_seconds, bypass_quiet_hours, popup_mode, "
            "popup_skin, channels",
            page,
        )
        hint.setObjectName("editorHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        channels_header = QHBoxLayout()
        channels_header.setContentsMargins(0, 6, 0, 0)
        channels_title = QLabel("外部渠道（JSON 数组，离开电脑时转投）", page)
        channels_title.setObjectName("dialogHint")
        channels_header.addWidget(channels_title, 1)
        channels_example = QPushButton("填入示例", page)
        channels_example.setObjectName("ghostButton")
        channels_example.setFixedHeight(24)
        channels_example.setCursor(Qt.CursorShape.PointingHandCursor)
        channels_example.clicked.connect(
            lambda: self._fill_example(self._channels_editor, _CHANNELS_EXAMPLE)
        )
        channels_header.addWidget(channels_example)
        layout.addLayout(channels_header)

        self._channels_editor = QPlainTextEdit(page)
        self._channels_editor.setPlaceholderText("[]")
        self._channels_editor.setPlainText(
            json.dumps(
                config_to_dict(self.config)["channels"], ensure_ascii=False, indent=2
            )
        )
        layout.addWidget(self._channels_editor, 1)

        channels_hint = QLabel(
            "类型：webhook / feishu / wecom / ntfy / bark / telegram。"
            "字段：type, enabled, when_away, min_priority, url, topic, token, "
            "chat_id, device_key, headers",
            page,
        )
        channels_hint.setObjectName("editorHint")
        channels_hint.setWordWrap(True)
        layout.addWidget(channels_hint)

        return page

    # ---------- actions ----------

    def _browse_sound(self, target: QLineEdit) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self, "选择提示音", "", "WAV 音频 (*.wav);;所有文件 (*.*)"
        )
        if path:
            target.setText(path)

    @staticmethod
    def _fill_example(editor: QPlainTextEdit, payload: list[dict]) -> None:
        editor.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))

    def _preview_popup(self) -> None:
        if self._preview is not None:
            self._preview.close_now()
            self._preview.deleteLater()
            self._preview = None
        notification = Notification(
            id="settings-preview",
            title="弹窗效果预览",
            status="succeeded",
            summary="这是当前选择的模式、皮肤与背景图效果；点击「知道了」关闭预览。",
            source="偏好设置",
            require_ack=True,
        )
        image = self._overlay_image_edit.text().strip()
        area = self._overlay_area_from_controls()
        preview = ToastWindow(
            notification,
            10,
            self.logger,
            templates=self.config.templates,
            popup_mode=self._popup_mode_combo.currentData(),
            popup_skin=self._popup_skin_combo.currentData(),
            overlay_image=image,
            overlay_area=area,
            parent=self,
        )
        preview.dismissed.connect(self._on_preview_dismissed)
        self._preview = preview
        preview.show_at(QPoint(0, 0))
        self.logger.info(
            "设置预览：模式=%s 皮肤=%s 背景图=%s 区域=%s/%s/+%s,+%s",
            preview.popup_mode,
            preview.popup_skin,
            image or "-",
            area.anchor,
            area.width or OVERLAY_CARD_WIDTH_DEFAULT,
            area.offset_x,
            area.offset_y,
        )

    def _on_preview_dismissed(self, notification: Notification, reason: str) -> None:
        preview = self._preview
        self._preview = None
        if preview is not None:
            preview.deleteLater()

    def _read_list(self, editor: QPlainTextEdit, label: str) -> list:
        text = editor.toPlainText().strip() or "[]"
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                f"{label} JSON 格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}"
            ) from exc
        if not isinstance(value, list):
            raise ConfigError(f"{label}部分必须是 JSON 数组")
        return value

    def _collect_config(self) -> AppConfig:
        data = config_to_dict(self.config)
        data.update(
            {
                "port": self._port_spin.value(),
                "token": self._token_edit.text(),
                "auto_close_seconds": self._auto_close_spin.value(),
                "autostart": self._autostart_check.isChecked(),
                "open_center_on_start": self._open_center_check.isChecked(),
                "success_popup": self._success_popup_check.isChecked(),
                "require_ack_by_default": self._require_ack_check.isChecked(),
                "popup_cooldown_seconds": self._cooldown_spin.value(),
                "hotkey": self._hotkey_edit.text(),
                "suppress_fullscreen": self._fullscreen_check.isChecked(),
                "hold_when_locked": self._hold_when_locked_check.isChecked(),
                "away_idle_seconds": self._away_spin.value(),
                "popup_mode": self._popup_mode_combo.currentData(),
                "popup_skin": self._popup_skin_combo.currentData(),
                "overlay_image": self._overlay_image_edit.text().strip(),
                "overlay_area": {
                    "anchor": self._overlay_anchor_combo.currentData(),
                    "width": self._overlay_width_spin.value(),
                    "offset_x": self._overlay_offset_x_spin.value(),
                    "offset_y": self._overlay_offset_y_spin.value(),
                    "margin": self._overlay_margin_spin.value(),
                },
                "agent_sessions": {
                    "enabled": self._agent_enabled_check.isChecked(),
                    "scan_interval_seconds": self._agent_interval_spin.value(),
                    "max_sessions": self._agent_max_spin.value(),
                },
                "meeting_processes": [
                    item.strip()
                    for item in self._meeting_edit.text().split(",")
                    if item.strip()
                ],
                "quiet_hours": {
                    "enabled": self._quiet_enabled_check.isChecked(),
                    "start": self._quiet_start_edit.time().toString("HH:mm"),
                    "end": self._quiet_end_edit.time().toString("HH:mm"),
                    "allow_critical": self._quiet_critical_check.isChecked(),
                },
                "digest": {
                    "enabled": self._digest_check.isChecked(),
                    "threshold": self._digest_threshold_spin.value(),
                    "window_seconds": self._digest_window_spin.value(),
                },
                "escalation": {
                    "unread_seconds": self._escalation_spin.value(),
                    "max_times": self._escalation_times_spin.value(),
                    "flash_tray": self._flash_check.isChecked(),
                    "sound": self._escalation_sound_check.isChecked(),
                },
                "templates": {
                    key: edit.text().strip()
                    for key, edit in self._template_edits.items()
                },
                "sounds": {
                    key: edit.text().strip()
                    for key, edit in self._sound_edits.items()
                },
                "rules": self._read_list(self._rules_editor, "规则"),
                "channels": self._read_list(self._channels_editor, "渠道"),
            }
        )
        config = config_from_dict(data)
        return replace(config, instance_name=self.config.instance_name)

    def _save(self) -> None:
        try:
            config = self._collect_config()
        except ConfigError as exc:
            self._show_error(str(exc))
            return
        if self._config_path is not None:
            try:
                save_config(self._config_path, config)
            except ConfigError as exc:
                self._show_error(str(exc))
                return
            self.logger.info("偏好设置已写入 %s", self._config_path)
        self.result_config = config
        self.accept()

    def _show_error(self, message: str) -> None:
        self.logger.warning("偏好设置校验失败：%s", message)
        if "规则" in message or "渠道" in message:
            self._tabs.setCurrentIndex(5)
        elif "模板" in message or "提示音" in message or "sounds" in message:
            self._tabs.setCurrentIndex(3)
        elif "agent_sessions" in message:
            self._tabs.setCurrentIndex(4)
        elif "overlay_image" in message:
            self._tabs.setCurrentIndex(1)
        else:
            self._tabs.setCurrentIndex(0)
        QMessageBox.warning(self, "配置无效", message)
