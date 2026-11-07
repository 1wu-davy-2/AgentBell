from __future__ import annotations

import os
import plistlib
import sys

import pytest

from agentbell import macos_desktop as md


def test_parse_window_list_skips_own_pid_and_bad_rows():
    own_pid = os.getpid()
    text = "\n".join(
        [
            "10\tTerminal\tdemo — zsh",
            f"{own_pid}\tAgentBell\tself",
            "11\tiTerm2\t  spaced   title  ",
            "12\tSafari\t",
            "not-a-pid\tX\tY",
        ]
    )
    windows = md._parse_window_list(text)
    assert windows == [
        md.MacWindow(pid=10, app="Terminal", title="demo — zsh"),
        md.MacWindow(pid=11, app="iTerm2", title="spaced title"),
    ]


def test_parse_process_table_and_ancestors():
    table = md._parse_process_table(
        "  13012  12304 /usr/local/bin/claude\n"
        "  12304      1 /Applications/Utilities/Terminal.app/Contents/MacOS/Terminal\n"
        "     1      0 /sbin/launchd\n"
        "bad row\n"
    )
    assert table[13012] == (12304, "/usr/local/bin/claude")
    assert md.process_ancestors(13012, table) == [13012, 12304, 1]
    assert md.process_ancestors(999, table) == [999]


def test_app_label_maps_bundles_and_cli_names():
    assert (
        md.app_label(
            "/Applications/Visual Studio Code.app/Contents/MacOS/Electron"
        )
        == "VS Code"
    )
    assert (
        md.app_label("/Applications/iTerm2.app/Contents/MacOS/iTerm2")
        == "iTerm2"
    )
    assert md.app_label("/usr/local/bin/claude") == "Claude Code"
    assert md.app_label("/opt/homebrew/bin/codex") == "Codex"
    assert md.app_label("/usr/bin/python3") == ""


def test_is_terminal_app_normalizes_names():
    assert md.is_terminal_app("Terminal") is True
    assert md.is_terminal_app("iTerm2") is True
    assert md.is_terminal_app("Visual Studio Code") is True
    assert md.is_terminal_app("Safari") is False


def test_parse_lsappinfo_and_clean_name():
    info = md._parse_lsappinfo(
        'Application{ "LSDisplayName"="Safari" "pid"=321 '
        '"ASN"="ASN:0x0-0x1c01c" }'
    )
    assert info == {"name": "Safari", "pid": "321", "asn": "ASN:0x0-0x1c01c"}
    assert md._clean_app_name("  Safari.app ") == "Safari"


def test_foreground_app_uses_lsappinfo(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, timeout=4.0):
        calls.append(list(command))
        if command[:2] == ["lsappinfo", "front"]:
            return "ASN:0x0-0x1c01c"
        return '"LSDisplayName"="Safari" "pid"=321 "ASN"="ASN:0x0-0x1c01c"'

    monkeypatch.setattr(md, "_run", fake_run)
    assert md.foreground_app() == ("Safari", 321)
    assert calls[0] == ["lsappinfo", "front"]


def test_foreground_app_falls_back_to_osascript(monkeypatch):
    def fake_run(command, timeout=4.0):
        if command[0] == "lsappinfo":
            return ""
        return 'Safari, 321'

    monkeypatch.setattr(md, "_run", fake_run)
    assert md.foreground_app() == ("Safari", 321)
    assert md.foreground_process_name() == "safari"


def test_foreground_fullscreen_queries_accessibility(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(command, timeout=4.0):
        captured.append(list(command))
        return "true\n"

    monkeypatch.setattr(md, "foreground_app", lambda: ("Safari", 321))
    monkeypatch.setattr(md, "_run", fake_run)
    assert md.foreground_fullscreen() is True
    assert "AXFullScreen" in captured[0][2]
    assert captured[0][-1] == "321"


def test_foreground_fullscreen_without_pid(monkeypatch):
    monkeypatch.setattr(md, "foreground_app", lambda: ("", 0))
    assert md.foreground_fullscreen() is False


def test_idle_seconds_prefers_core_graphics(monkeypatch):
    class Graphics:
        @staticmethod
        def CGEventSourceSecondsSinceLastEventType(_source, _event):
            return 12.5

    monkeypatch.setattr(md, "_core_graphics", lambda: Graphics)
    assert md.idle_seconds() == 12.5


def test_idle_seconds_falls_back_to_ioreg(monkeypatch):
    monkeypatch.setattr(md, "_core_graphics", lambda: None)
    monkeypatch.setattr(
        md,
        "_run",
        lambda command, timeout=4.0: '"HIDIdleTime" = 5000000000',
    )
    assert md.idle_seconds() == 5.0


def test_session_locked_prefers_session_dictionary(monkeypatch):
    monkeypatch.setattr(md, "_session_dictionary_bool", lambda key: True)
    assert md.session_locked() is True
    monkeypatch.setattr(md, "_session_dictionary_bool", lambda key: None)
    monkeypatch.setattr(md, "_ioreg_screen_locked", lambda: True)
    assert md.session_locked() is True


def test_ioreg_screen_locked_parses_plist_and_text(monkeypatch):
    data = plistlib.dumps(
        {"IOConsoleUsers": [{"CGSSessionScreenIsLocked": True}]}
    ).decode("utf-8")
    monkeypatch.setattr(md, "_run", lambda command, timeout=4.0: data)
    assert md._ioreg_screen_locked() is True

    def text_run(value):
        return lambda command, timeout=4.0: (
            "" if "-a" in command else value
        )

    monkeypatch.setattr(
        md, "_run", text_run('"CGSSessionScreenIsLocked" = Yes')
    )
    assert md._ioreg_screen_locked() is True

    monkeypatch.setattr(
        md, "_run", text_run('"CGSSessionScreenIsLocked" = No')
    )
    assert md._ioreg_screen_locked() is False


def test_window_list_uses_script(monkeypatch):
    captured: list[list[str]] = []

    def fake_run(command, timeout=4.0):
        captured.append(list(command))
        return "10\tTerminal\tdemo\n"

    monkeypatch.setattr(md, "_run", fake_run)
    assert md.window_list() == [md.MacWindow(10, "Terminal", "demo")]
    assert captured[0][0] == "osascript"
    assert "application process" in captured[0][2]


def test_client_pid_parses_lsof_output(monkeypatch):
    own_pid = os.getpid()
    text = "\n".join(
        [
            f"p{own_pid}",
            "n127.0.0.1:54321->127.0.0.1:8765",
            "p1234",
            "n127.0.0.1:55000->127.0.0.1:8765",
            "n127.0.0.1:54321->127.0.0.1:8765",
            "p2345",
            "n127.0.0.1:56000->127.0.0.1:8765",
        ]
    )
    monkeypatch.setattr(md, "_run", lambda command, timeout=4.0: text)
    assert md.client_pid(54321, 8765) == 1234
    assert md.client_pid(99999, 8765) is None
    assert md.client_pid(0) is None


def test_activate_requires_matching_foreground(monkeypatch):
    monkeypatch.setattr(md, "_execute", lambda command, timeout=4.0: (True, "ok"))
    monkeypatch.setattr(md, "_wait_for_front", lambda pid, timeout=1.2: True)
    assert md.activate(321, "demo", "Terminal") is True
    assert md.activate(0, "demo", "Terminal") is False

    monkeypatch.setattr(md, "_wait_for_front", lambda pid, timeout=1.2: False)
    assert md.activate(321, "demo", "") is False


def test_accessibility_permission_probe_is_safe_off_macos():
    if sys.platform == "darwin":
        pytest.skip("macOS loads the real Accessibility framework")
    assert md.accessibility_trusted() is None