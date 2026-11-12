from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt, QTimer
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

from ..models import (
    RUN_EVENT_LABELS,
    STATUS_LABELS,
    Notification,
    RunEvent,
    duration_to_seconds,
)

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
QLabel#timelineHint {
    font-size: 10px;
    color: #8A919D;
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
QLabel#sessionRoundTime {
    font-size: 11px;
    font-weight: 600;
    color: #3A4552;
}
QLabel#sessionRoundDate {
    font-size: 9px;
    color: #9AA1AC;
}
QFrame#sessionRoundCard {
    background-color: #FFFFFF;
    border: 1px solid #E9ECF2;
    border-radius: 12px;
}
QFrame#sessionRoundCard[latest="true"] {
    background-color: #FCFDFF;
    border-color: #C9DAF6;
}
QLabel#sessionRoundIndex {
    background-color: #EDF3FC;
    border-radius: 7px;
    color: #33517A;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
}
QLabel#sessionRoundTitle {
    font-size: 13px;
    font-weight: 600;
    color: #1F2329;
}
QLabel#sessionRoundSummary {
    font-size: 11px;
    color: #5F6875;
}
QLabel#sessionAutoChip {
    background-color: #FFF6E8;
    border-radius: 7px;
    color: #96631A;
    font-size: 10px;
    font-weight: 600;
    padding: 1px 8px;
}
QPushButton#sessionRoundToggle {
    background-color: #F4F6FA;
    border: 1px solid #E3E7ED;
    border-radius: 6px;
    color: #4C5663;
    font-size: 10px;
    padding: 0px 10px;
}
QPushButton#sessionRoundToggle:hover {
    background-color: #EDF1F7;
    border-color: #D5DAE3;
}
QFrame#sessionEventHost {
    background-color: #F8F9FC;
    border: 1px solid #EEF1F6;
    border-radius: 10px;
}
QLabel#sessionRailDot {
    border-radius: 5px;
    background-color: #9AA1AC;
}
QLabel#sessionRailDot[status="succeeded"] {
    background-color: #15885C;
}
QLabel#sessionRailDot[status="failed"] {
    background-color: #C24141;
}
QLabel#sessionRailDot[status="canceled"] {
    background-color: #B7791F;
}
QLabel#sessionRailDot[status="running"] {
    background-color: #2F6FF0;
}
QFrame#sessionRailLine {
    background-color: #E6E8EC;
    border: none;
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

        if len(self.events) == 1:
            hint = QLabel(
                "本次运行只收到 1 个事件，无法计算相对耗时与跨度。", panel
            )
            hint.setObjectName("timelineHint")
            hint.setWordWrap(True)
            layout.addWidget(hint)

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
            show_relative = len(self.events) > 1
            for index, event in enumerate(self.events):
                rows.addWidget(
                    self._build_row(
                        host,
                        event,
                        event.occurred_at - base,
                        index == last,
                        show_relative=show_relative,
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
        duration_seconds = duration_to_seconds(self.notification.duration)
        if duration_seconds is not None:
            texts.append(f"耗时 {format_run_span(duration_seconds)}")
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
        show_relative: bool = True,
    ) -> QFrame:
        row = _build_event_row(parent, event, offset, last, show_relative)
        self.event_rows.append(row)
        return row


def _build_event_row(
    parent: QWidget,
    event: RunEvent,
    offset: object,
    last: bool,
    show_relative: bool = True,
) -> QFrame:
    row = QFrame(parent)
    row.setObjectName("timelineRow")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(12)

    time_box = QVBoxLayout()
    time_box.setContentsMargins(0, 0, 0, 0)
    time_box.setSpacing(1)
    relative_text = (
        _relative(offset.total_seconds())
        if show_relative and hasattr(offset, "total_seconds")
        else ""
    )
    relative = QLabel(relative_text, row)
    relative.setObjectName("timelineRelative")
    relative.setVisible(show_relative)
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
    return row


@dataclass(frozen=True, slots=True)
class SessionRound:
    notification: Notification
    events: list[RunEvent]


def _round_summary_text(notification: Notification) -> str:
    if notification.summary:
        return notification.summary
    if notification.status == "failed":
        return notification.error or "执行失败，未提供更多信息。"
    if notification.status == "canceled":
        return "本轮任务已取消。"
    if notification.status == "running":
        return "本轮任务正在进行中。"
    return "本轮任务已完成。"


class SessionTimelineDialog(QDialog):
    """Read-only history stream that stitches one session's rounds together."""

    def __init__(
        self,
        title: str,
        rounds: list[SessionRound],
        logger: logging.Logger | None = None,
        parent: QWidget | None = None,
        *,
        session_id: str = "",
        agent: str = "",
        project: str = "",
    ) -> None:
        super().__init__(parent)
        self.title_text = title
        self.session_id = session_id
        self.agent = agent
        self.project = project
        self.rounds = sorted(
            rounds, key=lambda item: item.notification.received_at
        )
        self.round_cards: list[QFrame] = []
        self.round_event_hosts: list[QFrame] = []
        self.round_toggle_buttons: list[QPushButton] = []
        self.event_rows: list[QFrame] = []
        self.empty_label: QLabel | None = None
        self._logger = logger or logging.getLogger("agentbell.timeline")

        self.setObjectName("runTimelineDialog")
        self.setWindowTitle("会话历史流")
        self.setStyleSheet(_TIMELINE_QSS)
        self.setMinimumSize(660, 520)
        self.resize(760, 680)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(0)

        panel = QFrame(self)
        panel.setObjectName("timelinePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(10)
        outer.addWidget(panel, 1)

        heading = QLabel("会话历史流", panel)
        heading.setObjectName("timelineTitle")
        layout.addWidget(heading)

        subtitle = QLabel(title or "未命名会话", panel)
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

        hint = QLabel(
            "每一轮通知按时间排列；展开单轮可查看开始、进展与完成事件。",
            panel,
        )
        hint.setObjectName("timelineHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._scroll = QScrollArea(panel)
        self._scroll.setObjectName("timelineScroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        host.setObjectName("timelineHost")
        rows = QVBoxLayout(host)
        rows.setContentsMargins(0, 4, 4, 4)
        rows.setSpacing(8)
        self._scroll.setWidget(host)
        layout.addWidget(self._scroll, 1)

        if self.rounds:
            latest_with_events = max(
                (
                    index
                    for index, item in enumerate(self.rounds)
                    if item.events
                ),
                default=-1,
            )
            for index, item in enumerate(self.rounds):
                rows.addWidget(
                    self._build_round(
                        host,
                        index,
                        item,
                        expanded=index == latest_with_events,
                    )
                )
            rows.addStretch(1)
            QTimer.singleShot(0, self._scroll_to_latest)
        else:
            self.empty_label = QLabel(
                "该会话还没有关联的通知。完成一轮任务后，历史流会自动汇总到这里。",
                host,
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
        if self.agent:
            texts.append(self.agent)
        if self.project:
            texts.append(f"项目 {self.project}")
        if self.session_id:
            texts.append(f"会话 {self.session_id[:8]}")
        texts.append(f"{len(self.rounds)} 轮")
        finals = [
            item.notification
            for item in self.rounds
            if item.notification.status in {"succeeded", "failed", "canceled"}
        ]
        if finals:
            succeeded = sum(
                1 for item in finals if item.status == "succeeded"
            )
            texts.append(f"成功率 {round(succeeded * 100 / len(finals))}%")
        if len(self.rounds) > 1:
            start = self.rounds[0].notification.received_at
            end = max(
                item.notification.effective_updated_at for item in self.rounds
            )
            if end > start:
                texts.append(
                    f"跨度 {format_run_span((end - start).total_seconds())}"
                )
        auto = sum(
            1
            for item in self.rounds
            if item.notification.metadata.get("session_link") == "auto"
        )
        if auto:
            texts.append(f"自动关联 {auto}")
        return texts

    def _build_round(
        self,
        parent: QWidget,
        index: int,
        item: SessionRound,
        *,
        expanded: bool,
    ) -> QWidget:
        notification = item.notification
        latest = index == len(self.rounds) - 1
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        time_box = QVBoxLayout()
        time_box.setContentsMargins(0, 2, 0, 0)
        time_box.setSpacing(1)
        clock = QLabel(
            notification.received_at.astimezone().strftime("%H:%M"), row
        )
        clock.setObjectName("sessionRoundTime")
        clock.setAlignment(Qt.AlignmentFlag.AlignRight)
        day = QLabel(
            notification.received_at.astimezone().strftime("%m-%d"), row
        )
        day.setObjectName("sessionRoundDate")
        day.setAlignment(Qt.AlignmentFlag.AlignRight)
        time_box.addWidget(clock)
        time_box.addWidget(day)
        holder = QWidget(row)
        holder.setFixedWidth(52)
        holder.setLayout(time_box)
        layout.addWidget(holder, 0, Qt.AlignmentFlag.AlignTop)

        rail = QWidget(row)
        rail.setFixedWidth(12)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(2, 7, 2, 0)
        rail_layout.setSpacing(0)
        dot = QLabel(rail)
        dot.setObjectName("sessionRailDot")
        dot.setProperty("status", notification.status)
        dot.setFixedSize(10, 10)
        rail_layout.addWidget(dot, 0, Qt.AlignmentFlag.AlignHCenter)
        if not latest:
            line = QFrame(rail)
            line.setObjectName("sessionRailLine")
            line.setFixedWidth(1)
            rail_layout.addWidget(line, 1, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(rail, 0)

        card = QFrame(row)
        card.setObjectName("sessionRoundCard")
        card.setProperty("latest", latest)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 11, 14, 11)
        card_layout.setSpacing(5)

        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(6)
        badge = QLabel(f"第 {index + 1} 轮", card)
        badge.setObjectName("sessionRoundIndex")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(20)
        heading.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)

        round_title = QLabel(notification.title or "未命名任务", card)
        round_title.setObjectName("sessionRoundTitle")
        round_title.setWordWrap(True)
        heading.addWidget(round_title, 1)

        status = QLabel(
            STATUS_LABELS.get(notification.status, notification.status), card
        )
        status.setObjectName("timelineStatus")
        status.setProperty("status", notification.status)
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status.setFixedHeight(20)
        heading.addWidget(status, 0, Qt.AlignmentFlag.AlignTop)

        if notification.metadata.get("session_link") == "auto":
            auto = QLabel("自动关联", card)
            auto.setObjectName("sessionAutoChip")
            auto.setAlignment(Qt.AlignmentFlag.AlignCenter)
            auto.setFixedHeight(20)
            auto.setToolTip(
                "这条通知未显式上报 session_id，由 Agent 与项目目录唯一匹配得到"
            )
            heading.addWidget(auto, 0, Qt.AlignmentFlag.AlignTop)

        if notification.duration:
            duration = QLabel(f"耗时 {notification.duration}", card)
            duration.setObjectName("timelineMetaChip")
            duration.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading.addWidget(duration, 0, Qt.AlignmentFlag.AlignTop)
        card_layout.addLayout(heading)

        summary = QLabel(_round_summary_text(notification), card)
        summary.setObjectName("sessionRoundSummary")
        summary.setWordWrap(True)
        card_layout.addWidget(summary)

        event_host = QFrame(card)
        event_host.setObjectName("sessionEventHost")
        event_layout = QVBoxLayout(event_host)
        event_layout.setContentsMargins(8, 6, 8, 2)
        event_layout.setSpacing(0)
        if item.events:
            base = item.events[0].occurred_at
            last = len(item.events) - 1
            show_relative = len(item.events) > 1
            for event_index, event in enumerate(item.events):
                event_row = _build_event_row(
                    event_host,
                    event,
                    event.occurred_at - base,
                    event_index == last,
                    show_relative=show_relative,
                )
                event_layout.addWidget(event_row)
                self.event_rows.append(event_row)
            event_host.setVisible(expanded)
            toggle = QPushButton(card)
            toggle.setObjectName("sessionRoundToggle")
            toggle.setFixedHeight(24)
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            count = len(item.events)
            toggle.setText("收起事件" if expanded else f"展开事件 {count}")
            toggle.clicked.connect(
                lambda checked=False, host=event_host, button=toggle, size=count: (
                    self._toggle_events(host, button, size)
                )
            )
            card_layout.addWidget(
                toggle, 0, Qt.AlignmentFlag.AlignLeft
            )
            self.round_toggle_buttons.append(toggle)
        else:
            empty = QLabel("未记录运行事件。", card)
            empty.setObjectName("timelineHint")
            card_layout.addWidget(empty)
        card_layout.addWidget(event_host)

        layout.addWidget(card, 1)
        self.round_cards.append(card)
        self.round_event_hosts.append(event_host)
        return row

    def _toggle_events(
        self, host: QFrame, button: QPushButton, count: int
    ) -> None:
        visible = host.isHidden()
        host.setVisible(visible)
        button.setText("收起事件" if visible else f"展开事件 {count}")

    def _scroll_to_latest(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
