from __future__ import annotations

from datetime import datetime, timedelta

from agentbell.app import pause_deadline


def test_pause_deadline_disabled_for_non_positive():
    now = datetime.now().astimezone()
    assert pause_deadline(0, now) is None
    assert pause_deadline(-3, now) is None


def test_pause_deadline_minutes():
    now = datetime(2026, 11, 7, 21, 30).astimezone()
    assert pause_deadline(30, now) == now + timedelta(minutes=30)
    assert pause_deadline(60, now) == now + timedelta(hours=1)


def test_pause_deadline_until_morning():
    evening = datetime(2026, 11, 7, 22, 0).astimezone()
    assert pause_deadline(-1, evening) == datetime(
        2026, 11, 8, 8, 0
    ).astimezone()

    early = datetime(2026, 11, 7, 6, 0).astimezone()
    assert pause_deadline(-1, early) == datetime(2026, 11, 7, 8, 0).astimezone()