from __future__ import annotations

import pytest

from agentbell import presence


def _exercise_macos(monkeypatch):
    monkeypatch.setattr(presence, "_IS_MACOS", True)
    monkeypatch.setattr(presence, "_IS_WINDOWS", False)
    monkeypatch.setattr(presence, "_IS_LINUX", False)


def test_macos_presence_delegates_to_desktop_backend(monkeypatch):
    _exercise_macos(monkeypatch)
    monkeypatch.setattr(presence.macos_desktop, "idle_seconds", lambda: 42.5)
    monkeypatch.setattr(
        presence.macos_desktop, "foreground_process_name", lambda: "safari"
    )
    monkeypatch.setattr(
        presence.macos_desktop, "foreground_fullscreen", lambda: True
    )
    monkeypatch.setattr(presence.macos_desktop, "session_locked", lambda: True)

    assert presence.idle_seconds() == 42.5
    assert presence.foreground_window_class() == "safari"
    assert presence.foreground_process_name() == "safari"
    assert presence.foreground_is_fullscreen() is True
    assert presence.session_locked() is True


def test_macos_presence_failures_are_safe(monkeypatch):
    _exercise_macos(monkeypatch)

    def boom():
        raise RuntimeError("backend unavailable")

    monkeypatch.setattr(presence.macos_desktop, "idle_seconds", boom)
    monkeypatch.setattr(presence.macos_desktop, "foreground_process_name", boom)
    monkeypatch.setattr(presence.macos_desktop, "foreground_fullscreen", boom)
    monkeypatch.setattr(presence.macos_desktop, "session_locked", boom)

    assert presence.idle_seconds() == 0.0
    assert presence.foreground_window_class() == ""
    assert presence.foreground_process_name() == ""
    assert presence.foreground_is_fullscreen() is False
    assert presence.session_locked() is False


@pytest.mark.parametrize(
    ("foreground", "expected"),
    [
        ("zoom.us", "zoom.us"),
        ("microsoft teams", "microsoft teams"),
        ("facetime", "facetime"),
        ("safari", ""),
    ],
)
def test_macos_meeting_process_matching(monkeypatch, foreground, expected):
    _exercise_macos(monkeypatch)
    monkeypatch.setattr(
        presence.macos_desktop, "foreground_process_name", lambda: foreground
    )
    processes = ("zoom", "microsoft teams", "facetime")

    assert presence.active_meeting_process(processes) == expected