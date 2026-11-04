from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..models import RUN_EVENT_LABELS, STATUS_LABELS, Notification, RunEvent

_TIMELINE_QSS = """
QDialog#runTimelineDialog {
    background-color: #F6F7FB;
}
QFrame#timelinePanel {
    background-color: #FFFFFF;
    border: 1px solid #E6E8EC;
    border-radius: 14px;
}
QLabel#timelineTitle {
    font-size: 18px;
    font-weight: 700;
    color: #161A20;
}
QLabel#timelineSubtitle {
    font-size: 11px;
    color: #6B7280;
}
QLabel#timelineMetaChip {
    background-color: #F4F5F8;
    border-radius: 8px;
    color: #5A6472;
    font-size: 10px;
    padding: 2px 9px;
}
QScrollArea#timelineScroll {
    background: transparent;
    border: none;
}
QWidget#timelineHost {
    background: transparent;
}
QFrame#timelineLine {
    background-color: #E6E8EC;
    border: none;
}
QLabel#timelineDot {
    border-radius: 5px;
    background-color: #9AA1AC;
}
QLabel#timelineDot[kind="started"] {
    background-color: #2F6FF0;
}
QLabel#timelineDot[kind="progress"] {
    background-color: #7C93B8;
}
QLabel#timelineDot[kind="waiting_input"] {
    background-color: #F59E0B;
}
QLabel#timelineDot[kind="resumed"] {
    background-color: #22A06B;
}
QLabel#timelineDot[kind="finished"] {
    background-color: #15885C;
}
QLabel#timelineRelative {
    font-size: 11px;
    font-weight: 600;
    color: #323A45;
}
QLabel#timelineClock {
    font-size: 9px;
    color: #9AA1AC;
}
QLabel#timelineKind {
    background-color: #F4F5F8;
    border-radius: 7px;
    color: #5A6472;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
}
QLabel#timelineKind[kind="started"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#timelineKind[kind="waiting_input"] {
    background-color: #FFF4E6;
    color: #9A4E05;
}
QLabel#timelineKind[kind="resumed"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#timelineKind[kind="finished"] {
    background-color: #EEF3F0;
    color: #3F6B58;
}
QLabel#timelineStatus {
    border-radius: 7px;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
    background-color: #F4F5F8;
    color: #6B7280;
}
QLabel#timelineStatus[status="succeeded"] {
    background-color: #E8F8F0;
    color: #15885C;
}
QLabel#timelineStatus[status="failed"] {
    background-color: #FDECEC;
    color: #C24141;
}
QLabel#timelineStatus[status="canceled"] {
    background-color: #FDF4E5;
    color: #A16207;
}
QLabel#timelineStatus[status="running"] {
    background-color: #EAF2FF;
    color: #2F6FF0;
}
QLabel#timelineEventTitle {
    font-size: 12px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#timelineEventDetail {
    font-size: 10px;
    color: #6B7280;
}
QLabel#timelineEmpty {
    font-size: 11px;
    color: #8A919D;
}
QPushButton#timelineClose {
    background-color: #FFFFFF;
    border: 1px solid #E3E7ED;
    border-radius: 8px;
    color: #5A6472;
    font-size: 11px;
    padding: 0px 16px;
}
QPushButton#timelineClose:hover {
    background-color: #F2F5FA;
    border-color: #D5DAE3;
}
"""


def _relative(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    if value < 60:
        return f"+{value}s"
    if value < 3600:
        return f"+{value // 60}m{value % 60:02d}s"
    return f"+{value // 3600}h{(value % 3600) // 60:02d}m"


def format_run_span(seconds: float) -> str:
    value = max(0, int(round(seconds)))
    if value < 60:
        return f"{value} 秒"
    if value < 3600:
        return f"{value // 60} 分 {value % 60} 秒"
    return f"{value // 3600} 小时 {(value % 3600) // 60} 分"


class RunTimelineDialog(QDialog):
    """Read-only timeline dialog for one run."""

    def __init__(
        self,
        notification: Notification,
        events: list[RunEvent],
        logger: logging.Logger | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.notification = notification
        self.events = list(events)
        self.event_rows: list[QFrame] = []
        self.empty_label: QLabel | None = None
        self._logger = logger or logging.getLogger("agentbell.timeline")

        self.setObjectName("runTimelineDialog")
        self.setWindowTitle("运行时间线")
        self.setStyleSheet(_TIMELINE_QSS)
        self.setMinimumSize(600, 480)
        self.resize(680, 600)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("timelinePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        outer.addWidget(panel, 1)

        title = QLabel("运行时间线", panel)
        title.setObjectName("timelineTitle")
        layout.addWidget(title)

        subtitle = QLabel(notification.title, panel)
        subtitle.setObjectName("timelineSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        for text in self._meta_texts():
            chip = QLabel(text, panel)
            chip.setObjectName("timelineMetaChip")
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            meta.addWidget(chip)
        meta.addStretch(1)
        layout.addLayout(meta)

        scroll = QScrollArea(panel)
        scroll.setObjectName("timelineScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setObjectName("timelineHost")
        rows = QVBoxLayout(host)
        rows.setContentsMargins(0, 4, 4, 4)
        rows.setSpacing(0)
        scroll.setWidget(host)
        layout.addWidget(scroll, 1)

        if self.events:
            base = self.events[0].occurred_at
            last = len(self.events) - 1
            for index, event in enumerate(self.events):
                rows.addWidget(
                    self._build_row(
                        host, event, event.occurred_at - base, index == last
                    )
                )
            rows.addStretch(1)
        else:
            self.empty_label = QLabel(
                "该运行还没有事件记录。下一次通知会继续补全这条时间线。", host
            )
            self.empty_label.setObjectName("timelineEmpty")
            self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.empty_label.setWordWrap(True)
            rows.addStretch(1)
            rows.addWidget(self.empty_label)
            rows.addStretch(2)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 6, 0, 0)
        footer.addStretch(1)
        close = QPushButton("关闭", panel)
        close.setObjectName("timelineClose")
        close.setFixedSize(76, 30)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

    def _meta_texts(self) -> list[str]:
        texts: list[str] = []
        if self.notification.source:
            texts.append(f"来源 {self.notification.source}")
        if self.notification.session_id:
            texts.append(f"会话 {self.notification.session_id[:8]}")
        texts.append(f"{len(self.events)} 个事件")
        if len(self.events) > 1:
            span = self.events[-1].occurred_at - self.events[0].occurred_at
            texts.append(f"跨度 {format_run_span(span.total_seconds())}")
        return texts

    def _build_row(
        self,
        parent: QWidget,
        event: RunEvent,
        offset: object,
        last: bool,
    ) -> QFrame:
        row = QFrame(parent)
        row.setObjectName("timelineRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        time_box = QVBoxLayout()
        time_box.setContentsMargins(0, 0, 0, 0)
        time_box.setSpacing(1)
        relative = QLabel(
            _relative(offset.total_seconds()) if hasattr(offset, "total_seconds") else "+0s",
            row,
        )
        relative.setObjectName("timelineRelative")
        relative.setAlignment(Qt.AlignmentFlag.AlignRight)
        clock = QLabel(
            event.occurred_at.astimezone().strftime("%H:%M:%S"), row
        )
        clock.setObjectName("timelineClock")
        clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_box.addWidget(relative)
        time_box.addWidget(clock)
        holder = QWidget(row)
        holder.setFixedWidth(78)
        holder.setLayout(time_box)
        layout.addWidget(holder, 0, Qt.AlignmentFlag.AlignTop)

        rail = QWidget(row)
        rail.setFixedWidth(12)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(2, 5, 2, 0)
        rail_layout.setSpacing(0)
        dot = QLabel(rail)
        dot.setObjectName("timelineDot")
        dot.setProperty("kind", event.kind)
        dot.setFixedSize(10, 10)
        rail_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
        if not last:
            line = QFrame(rail)
            line.setObjectName("timelineLine")
            line.setFixedWidth(1)
            rail_layout.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rail, 0)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 14)
        body.setSpacing(3)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(6)
        kind = QLabel(RUN_EVENT_LABELS.get(event.kind, event.kind), row)
        kind.setObjectName("timelineKind")
        kind.setProperty("kind", event.kind)
        kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kind.setFixedHeight(20)
        heading.addWidget(kind)
        if event.status:
            status = QLabel(STATUS_LABELS.get(event.status, event.status), row)
            status.setObjectName("timelineStatus")
            status.setProperty("status", event.status)
            status.setAlignment(Qt.AlignmentFlag.AlignCenter)
            status.setFixedHeight(20)
            heading.addWidget(status)
        if event.agent:
            agent = QLabel(event.agent, row)
            agent.setObjectName("timelineMetaChip")
            agent.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.addWidget(agent)
        heading.addStretch(1)
        body.addLayout(heading)

        if event.title:
            event_title = QLabel(event.title, row)
            event_title.setObjectName("timelineEventTitle")
            event_title.setWordWrap(True)
            body.addWidget(event_title)
        if event.detail:
            detail = QLabel(event.detail, row)
            detail.setObjectName("timelineEventDetail")
            detail.setWordWrap(True)
            body.addWidget(detail)
        layout.addLayout(body, 1)

        self.event_rows.append(row)
        return row
