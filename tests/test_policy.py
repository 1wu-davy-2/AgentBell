from __future__ import annotations

from datetime import datetime

from agentbell.config import (
    AppConfig,
    ChannelConfig,
    DigestConfig,
    QuietHoursConfig,
    RuleConfig,
)
from agentbell.models import Notification
from agentbell.policy import (
    Presence,
    apply_rules,
    decide,
    in_quiet_hours,
    quiet_hours_end,
    resolve_channels,
)


def make_notification(**overrides) -> Notification:
    values = {
        "id": "id1",
        "title": "生成竞品分析报告",
        "status": "succeeded",
        "summary": "完成",
    }
    values.update(overrides)
    return Notification(**values)


def test_overnight_quiet_hours():
    quiet = QuietHoursConfig(enabled=True, start="22:00", end="08:00")
    assert in_quiet_hours(quiet, datetime(2026, 10, 29, 23, 30))
    assert in_quiet_hours(quiet, datetime(2026, 10, 30, 7, 59))
    assert not in_quiet_hours(quiet, datetime(2026, 10, 30, 12, 0))

    end = quiet_hours_end(quiet, datetime(2026, 10, 29, 23, 30))
    assert end == datetime(2026, 10, 30, 8, 0)


def test_daytime_quiet_hours_and_disabled():
    quiet = QuietHoursConfig(enabled=True, start="12:00", end="13:30")
    assert in_quiet_hours(quiet, datetime(2026, 10, 29, 12, 30))
    assert not in_quiet_hours(quiet, datetime(2026, 10, 29, 11, 59))
    assert not in_quiet_hours(
        QuietHoursConfig(enabled=False, start="12:00", end="13:30"),
        datetime(2026, 10, 29, 12, 30),
    )


def test_apply_rules_matches_and_later_rules_win():
    rules = (
        RuleConfig(
            name="抓取静音",
            source="crawler*",
            priority="low",
            silent=True,
        ),
        RuleConfig(
            name="失败需确认",
            status="failed",
            priority="critical",
            require_ack=True,
            channels=("webhook",),
        ),
    )
    notification = make_notification(
        status="failed",
        source="crawler-bot",
        channel_types=("ntfy",),
    )
    resolved = apply_rules(notification, rules)
    assert resolved.priority == "critical"
    assert resolved.silent is True
    assert resolved.require_ack is True
    assert resolved.rule_name == "抓取静音, 失败需确认"
    assert resolved.channel_types == ("ntfy", "webhook")


def test_apply_rules_skips_unmatched():
    notification = make_notification(source="writer")
    resolved = apply_rules(
        notification,
        (RuleConfig(name="only crawler", source="crawler*", priority="low"),),
    )
    assert resolved is notification


def test_decide_success_popup_toggle_and_running_priority():
    config = AppConfig(success_popup=False)
    success = decide(make_notification(), config, now=datetime(2026, 10, 29, 12, 0))
    assert success.popup is False
    assert success.defer_reason == ""

    failed = decide(
        make_notification(status="failed"), config, now=datetime(2026, 10, 29, 12, 0)
    )
    assert failed.popup is True

    running_low = decide(
        make_notification(status="running"),
        config,
        now=datetime(2026, 10, 29, 12, 0),
    )
    assert running_low.popup is False
    assert running_low.notification.auto_close_seconds == 0

    running_high = decide(
        make_notification(status="running", priority="high"),
        config,
        now=datetime(2026, 10, 29, 12, 0),
    )
    assert running_high.popup is True

    canceled = decide(
        make_notification(status="canceled"), config, now=datetime(2026, 10, 29, 12, 0)
    )
    assert canceled.popup is True
    canceled_low = decide(
        make_notification(status="canceled", priority="low"),
        config,
        now=datetime(2026, 10, 29, 12, 0),
    )
    assert canceled_low.popup is False


def test_quiet_hours_defer_but_critical_can_pass():
    config = AppConfig(quiet_hours=QuietHoursConfig(enabled=True))
    night = datetime(2026, 10, 29, 23, 0)

    normal = decide(make_notification(status="failed"), config, now=night)
    assert normal.popup is False
    assert normal.defer_reason == "quiet_hours"

    critical = decide(
        make_notification(status="failed", priority="critical"),
        config,
        now=night,
    )
    assert critical.popup is True
    assert critical.defer_reason == ""
    assert critical.notification.require_ack is True

    bypass = decide(
        make_notification(status="failed", bypass_quiet_hours=True),
        config,
        now=night,
    )
    assert bypass.popup is True


def test_fullscreen_and_meeting_suppression():
    config = AppConfig(suppress_fullscreen=True)
    noon = datetime(2026, 10, 29, 12, 0)

    fullscreen = decide(
        make_notification(status="failed", priority="critical"),
        config,
        Presence(fullscreen=True),
        now=noon,
    )
    assert fullscreen.popup is False
    assert fullscreen.defer_reason == "fullscreen"

    meeting = decide(
        make_notification(status="failed"),
        config,
        Presence(meeting_process="zoom.exe"),
        now=noon,
    )
    assert meeting.popup is False
    assert meeting.defer_reason == "meeting"

    disabled = decide(
        make_notification(status="failed"),
        AppConfig(suppress_fullscreen=False),
        Presence(fullscreen=True),
        now=noon,
    )
    assert disabled.popup is True


def test_require_ack_default_and_timeout():
    config = AppConfig(require_ack_by_default=True)
    decision = decide(
        make_notification(status="failed"), config, now=datetime(2026, 10, 29, 12, 0)
    )
    assert decision.notification.require_ack is True
    assert decision.notification.auto_close_seconds == 0

    center_only = decide(
        make_notification(),
        AppConfig(success_popup=False, require_ack_by_default=True),
        now=datetime(2026, 10, 29, 12, 0),
    )
    assert center_only.popup is False
    assert center_only.notification.require_ack is False


def test_locked_defers_until_unlock_and_can_be_disabled():
    config = AppConfig(hold_when_locked=True)
    noon = datetime(2026, 10, 29, 12, 0)

    locked = decide(
        make_notification(status="failed"), config, Presence(locked=True), now=noon
    )
    assert locked.popup is False
    assert locked.defer_reason == "locked"

    unlocked = decide(
        make_notification(status="failed"), config, Presence(locked=False), now=noon
    )
    assert unlocked.popup is True
    assert unlocked.defer_reason == ""

    disabled = decide(
        make_notification(status="failed"),
        AppConfig(hold_when_locked=False),
        Presence(locked=True),
        now=noon,
    )
    assert disabled.popup is True


def test_popup_mode_and_skin_resolution():
    noon = datetime(2026, 10, 29, 12, 0)
    config = AppConfig(popup_mode="overlay", popup_skin="ocean")

    decision = decide(make_notification(status="failed"), config, now=noon)
    assert decision.notification.popup_mode == "overlay"
    assert decision.notification.popup_skin == "ocean"
    assert decision.notification.auto_close_seconds == 0

    override = decide(
        make_notification(status="failed", popup_mode="center", popup_skin="amber"),
        config,
        now=noon,
    )
    assert override.notification.popup_mode == "center"
    assert override.notification.popup_skin == "amber"
    assert override.notification.require_ack is True
    assert override.notification.auto_close_seconds == 0

    corner = decide(
        make_notification(status="failed"), AppConfig(popup_mode="corner"), now=noon
    )
    assert corner.notification.require_ack is False
    assert corner.notification.auto_close_seconds == 30


def test_rule_overrides_popup_appearance():
    rules = (
        RuleConfig(name="居中", status="failed", popup_mode="center", popup_skin="light"),
    )
    notification = make_notification(status="failed", popup_mode="corner")
    resolved = apply_rules(notification, rules)
    assert resolved.popup_mode == "center"
    assert resolved.popup_skin == "light"


def test_channel_resolution_respects_presence_and_priority():
    config = AppConfig(
        channels=(
            ChannelConfig(
                type="webhook",
                when_away=True,
                min_priority="high",
                url="https://example.com/hook",
            ),
            ChannelConfig(
                type="ntfy",
                when_away=False,
                min_priority="normal",
                topic="agentbell",
            ),
            ChannelConfig(
                type="bark",
                enabled=False,
                when_away=False,
                device_key="key",
            ),
        )
    )
    failed = make_notification(status="failed", priority="high")
    assert resolve_channels(failed, config, Presence(away=False)) == ("ntfy",)
    assert resolve_channels(failed, config, Presence(away=True)) == (
        "webhook",
        "ntfy",
    )

    success = make_notification(priority="normal")
    assert resolve_channels(success, config, Presence(away=True)) == ("ntfy",)

    restricted = make_notification(status="failed", priority="high", channel_types=("webhook",))
    assert resolve_channels(restricted, config, Presence(away=False)) == ()


def test_digest_config_does_not_affect_decision():
    config = AppConfig(digest=DigestConfig(enabled=True, threshold=2))
    decision = decide(
        make_notification(status="failed"), config, now=datetime(2026, 10, 29, 12, 0)
    )
    assert decision.popup is True
