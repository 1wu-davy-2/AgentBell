from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

import agentbell.window_focus as window_focus
from agentbell.macos_desktop import MacWindow
from agentbell.window_focus import (
    FocusRequest,
    FocusTarget,
    _WindowInfo,
    find_focus_choices,
    parse_focus_value,
)


@pytest.fixture(autouse=True)
def _exercise_windows_paths(monkeypatch):
    if os.name != "nt":
        monkeypatch.setattr(window_focus, "_IS_LINUX", False)
        monkeypatch.setattr(window_focus, "_IS_MACOS", False)


def test_parse_focus_value_reads_pid_title_and_cwd():
    target = parse_focus_value(
        json.dumps(
            {
                "pid": 4321,
                "window_title": "Windows Terminal",
                "working_dir": "E:\\work\\demo",
            }
        )
    )

    assert target is not None
    assert target.pid == 4321
    assert target.window_title == "Windows Terminal"
    assert target.working_dir == "E:\\work\\demo"


def test_parse_focus_value_sanitizes_text():
    target = parse_focus_value(
        '{"pid": 12, "window_title": "  A\\u0000 B  ", "working_dir": "E:\\\\x"}'
    )

    assert target is not None
    assert target.window_title == "A B"
    assert target.working_dir == "E:\\x"


def test_parse_focus_value_requires_pid_or_title():
    assert parse_focus_value('{"working_dir":"E:\\\\x"}') is None


def test_parse_focus_value_rejects_bad_input():
    assert parse_focus_value("") is None
    assert parse_focus_value("not json") is None
    assert parse_focus_value("[]") is None
    assert parse_focus_value('{"pid": -5}') is None
    assert parse_focus_value('{"pid": 99999999999}') is None

    coerced = parse_focus_value('{"pid": true, "window_title": "x"}')
    assert coerced is not None
    assert coerced.pid is None
    assert coerced.window_title == "x"


def test_focus_request_value_round_trip():
    request = FocusRequest(
        pid=4321,
        window_title="demo — Windows Terminal",
        working_dir="E:\\work\\demo",
    )

    target = parse_focus_value(request.to_value())

    assert target == FocusTarget(
        pid=4321,
        window_title="demo — Windows Terminal",
        working_dir="E:\\work\\demo",
    )


def _window(
    pid: int,
    title: str,
    exe: str = "windowsterminal.exe",
    class_name: str = "CASCADIA_HOSTING_WINDOW_CLASS",
) -> _WindowInfo:
    return _WindowInfo(
        handle=pid * 10,
        pid=pid,
        title=title,
        class_name=class_name,
        exe=exe,
    )


def test_find_focus_choices_filters_sorts_and_dedupes(monkeypatch):
    windows = [
        _window(1, "demo — Windows Terminal"),
        _window(2, "demo", exe="conhost.exe", class_name="ConsoleWindowClass"),
        _window(3, "Something else - demo project", exe="odd.exe"),
        _window(4, "demo", exe="chrome.exe", class_name="Chrome_WidgetWin_1"),
        _window(5, "demo", exe="code.exe", class_name="Chrome_WidgetWin_1"),
        _window(2, "demo", exe="conhost.exe", class_name="ConsoleWindowClass"),
        _window(6, "other"),
    ]
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: {})
    monkeypatch.setattr(window_focus, "_collect_windows", lambda table: windows)

    choices = find_focus_choices("demo")

    assert [choice.title for choice in choices] == [
        "demo",
        "demo",
        "demo — Windows Terminal",
        "Something else - demo project",
    ]
    assert [choice.pid for choice in choices] == [2, 5, 1, 3]
    target = parse_focus_value(choices[0].value)
    assert target == FocusTarget(pid=2, window_title="demo", working_dir="")


def test_find_focus_choices_requires_query_and_windows(monkeypatch):
    assert find_focus_choices("") == []
    assert find_focus_choices("   ") == []

    monkeypatch.setattr(window_focus, "_IS_WINDOWS", False)
    assert find_focus_choices("demo") == []


def test_find_focus_choices_respects_limit(monkeypatch):
    windows = [_window(index, f"demo {index}") for index in range(1, 6)]
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: {})
    monkeypatch.setattr(window_focus, "_collect_windows", lambda table: windows)

    assert len(find_focus_choices("demo", limit=2)) == 2


def test_snapshot_focus_binds_host_window_pid(monkeypatch):
    windows = [
        _window(12304, "Qoder", exe="qoder.exe", class_name="Chrome_WidgetWin_1")
    ]
    table = {
        13012: (12304, "claude.exe"),
        12304: (21016, "qoder.exe"),
        21016: (0, "qoder.exe"),
    }
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: table)
    monkeypatch.setattr(window_focus, "_collect_windows", lambda value: windows)

    choice = window_focus.snapshot_focus(13012)

    assert choice is not None
    assert choice.pid == 12304
    assert choice.title == "Qoder"
    target = parse_focus_value(choice.value)
    assert target == FocusTarget(pid=12304, window_title="Qoder", working_dir="")


def test_snapshot_focus_returns_none_when_window_absent(monkeypatch):
    table = {13012: (12304, "claude.exe")}
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: table)
    monkeypatch.setattr(
        window_focus, "_collect_windows", lambda value: [_window(999, "other")]
    )

    assert window_focus.snapshot_focus(13012) is None
    assert window_focus.snapshot_focus(0) is None

    monkeypatch.setattr(window_focus, "_IS_WINDOWS", False)
    assert window_focus.snapshot_focus(13012) is None


def test_select_owner_pid_matches_local_and_remote_ports():
    entries = [
        (50000, 8765, 4),
        (50001, 8765, 13012),
        (50002, 9000, 22000),
    ]

    assert window_focus._select_owner_pid(entries, 50001, 8765) == 13012
    assert window_focus._select_owner_pid(entries, 50002, None) == 22000
    assert window_focus._select_owner_pid(entries, 50001, 9000) is None
    assert window_focus._select_owner_pid(entries, 59999, None) is None


def test_decode_net_port():
    assert window_focus._decode_net_port(0x6975) == 0x7569
    assert window_focus._decode_net_port(0x1F90) == 0x901F


def test_sender_label_prefers_agent_process(monkeypatch):
    table = {
        13012: (12000, "node.exe"),
        12000: (12304, "qoder.exe"),
        12304: (0, "qoder.exe"),
    }
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: table)
    monkeypatch.setattr(
        window_focus,
        "_collect_windows",
        lambda value: [
            _window(12304, "Qoder", exe="qoder.exe", class_name="Chrome_WidgetWin_1")
        ],
    )

    assert window_focus.sender_label(13012) == "Qoder"


def test_sender_label_detects_agent_binary(monkeypatch):
    table = {
        13012: (12304, "claude.exe"),
        12304: (0, "qoder.exe"),
    }
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: table)
    monkeypatch.setattr(window_focus, "_collect_windows", lambda value: [])

    assert window_focus.sender_label(13012) == "Claude Code"


def test_sender_label_falls_back_to_host_window(monkeypatch):
    table = {
        13012: (12304, "powershell.exe"),
        12304: (0, "explorer.exe"),
    }
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", True)
    monkeypatch.setattr(window_focus, "_process_table", lambda: table)
    monkeypatch.setattr(
        window_focus,
        "_collect_windows",
        lambda value: [
            _window(12304, "Qoder", exe="qoder.exe", class_name="Chrome_WidgetWin_1")
        ],
    )

    assert window_focus.sender_label(13012) == "Qoder"


def test_sender_label_handles_missing_and_off_windows(monkeypatch):
    assert window_focus.sender_label(0) == ""

    monkeypatch.setattr(window_focus, "_IS_WINDOWS", False)
    assert window_focus.sender_label(13012) == ""


class _FakeUser32:
    def __init__(
        self,
        *,
        clean: bool = False,
        attach: bool = False,
        switch: bool = False,
        alt: bool = False,
        raised: bool = True,
    ) -> None:
        self.foreground = 111
        self.clean = clean
        self.attach = attach
        self.switch = switch
        self.alt = alt
        self.raised = raised
        self.calls: list[object] = []
        self._attached = False
        self._alt_down = False

    def IsIconic(self, handle):
        return False

    def ShowWindow(self, handle, command):
        self.calls.append("ShowWindow")
        return True

    def BringWindowToTop(self, handle):
        self.calls.append("BringWindowToTop")
        return True

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, handle, pid):
        return {111: 11, 222: 22}.get(handle, 0)

    def AttachThreadInput(self, first, second, attach):
        self.calls.append(("AttachThreadInput", first, second, attach))
        self._attached = attach
        return True

    def SetForegroundWindow(self, handle):
        self.calls.append("SetForegroundWindow")
        if self.clean or (self.attach and self._attached) or (self.alt and self._alt_down):
            self.foreground = handle
            return True
        return False

    def SetFocus(self, handle):
        self.calls.append("SetFocus")
        return handle

    def SwitchToThisWindow(self, handle, flag):
        self.calls.append("SwitchToThisWindow")
        if self.switch:
            self.foreground = handle

    def keybd_event(self, vk, scan, flags, extra):
        self.calls.append(("keybd_event", vk, flags))
        if vk == window_focus._VK_MENU:
            self._alt_down = flags == 0

    def SetWindowPos(self, *args):
        self.calls.append("SetWindowPos")
        return self.raised


def _fake_activation(monkeypatch, **options) -> _FakeUser32:
    fake = _FakeUser32(**options)
    monkeypatch.setattr(window_focus, "_user32", fake)
    monkeypatch.setattr(
        window_focus, "_kernel32", SimpleNamespace(GetCurrentThreadId=lambda: 99)
    )
    return fake


def test_activate_window_uses_clean_foreground_first(monkeypatch):
    fake = _fake_activation(monkeypatch, clean=True)

    assert window_focus._activate_window(222) == (True, True)
    assert "AttachThreadInput" not in str(fake.calls)
    assert "SwitchToThisWindow" not in fake.calls


def test_activate_window_attaches_foreground_and_target_threads(monkeypatch):
    fake = _fake_activation(monkeypatch, attach=True)

    assert window_focus._activate_window(222) == (True, True)
    attaches = [call for call in fake.calls if isinstance(call, tuple)]
    assert ("AttachThreadInput", 11, 99, True) in attaches
    assert ("AttachThreadInput", 22, 99, True) in attaches
    assert ("AttachThreadInput", 11, 99, False) in attaches
    assert ("AttachThreadInput", 22, 99, False) in attaches


def test_activate_window_falls_back_to_switch_then_alt(monkeypatch):
    fake = _fake_activation(monkeypatch, switch=True)

    assert window_focus._activate_window(222) == (True, True)
    assert "SwitchToThisWindow" in fake.calls
    assert not any(
        isinstance(call, tuple) and call[0] == "keybd_event" for call in fake.calls
    )

    alt_fake = _fake_activation(monkeypatch, alt=True)
    assert window_focus._activate_window(222) == (True, True)
    assert "SwitchToThisWindow" in alt_fake.calls
    alt_calls = [
        call
        for call in alt_fake.calls
        if isinstance(call, tuple) and call[0] == "keybd_event"
    ]
    assert alt_calls[0][2] == 0
    assert alt_calls[-1][2] == window_focus._KEYEVENTF_KEYUP


def test_activate_window_reports_raised_when_focus_is_denied(monkeypatch):
    fake = _fake_activation(monkeypatch, raised=False)

    assert window_focus._activate_window(222) == (False, False)
    assert fake.calls[-1] == "SetWindowPos"

    raised_fake = _fake_activation(monkeypatch, raised=True)
    assert window_focus._activate_window(222) == (False, True)
    assert raised_fake.calls[-1] == "SetWindowPos"


def _exercise_macos(monkeypatch):
    monkeypatch.setattr(window_focus, "_IS_WINDOWS", False)
    monkeypatch.setattr(window_focus, "_IS_LINUX", False)
    monkeypatch.setattr(window_focus, "_IS_MACOS", True)


def test_find_focus_choices_macos_filters_terminal_apps(monkeypatch):
    _exercise_macos(monkeypatch)
    monkeypatch.setattr(window_focus.macos_desktop, "process_table", lambda: {})
    monkeypatch.setattr(
        window_focus.macos_desktop,
        "window_list",
        lambda: [
            MacWindow(10, "Terminal", "demo — zsh"),
            MacWindow(11, "Google Chrome", "demo docs"),
            MacWindow(12, "iTerm2", "other"),
        ],
    )

    choices = find_focus_choices("demo")

    assert [choice.title for choice in choices] == ["demo — zsh"]
    assert choices[0].pid == 10
    assert choices[0].executable == "terminal"


def test_snapshot_focus_macos_resolves_terminal_ancestor(monkeypatch):
    _exercise_macos(monkeypatch)
    table = {
        13012: (12304, "/bin/zsh"),
        12304: (
            100,
            "/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
        ),
        100: (1, "/sbin/launchd"),
    }
    monkeypatch.setattr(window_focus.macos_desktop, "process_table", lambda: table)
    monkeypatch.setattr(
        window_focus.macos_desktop, "window_list", lambda: []
    )

    choice = window_focus.snapshot_focus(13012)

    assert choice is not None
    assert choice.pid == 12304
    assert choice.title == ""
    target = parse_focus_value(choice.value)
    assert target == FocusTarget(pid=12304, window_title="", working_dir="")
    assert window_focus.snapshot_focus(0) is None


def test_focus_terminal_macos_activates_resolved_window(monkeypatch):
    _exercise_macos(monkeypatch)
    table = {
        13012: (12304, "/bin/zsh"),
        12304: (
            100,
            "/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
        ),
    }
    monkeypatch.setattr(window_focus.macos_desktop, "process_table", lambda: table)
    monkeypatch.setattr(
        window_focus.macos_desktop,
        "window_list",
        lambda: [MacWindow(12304, "Terminal", "demo — zsh")],
    )
    calls = []
    monkeypatch.setattr(
        window_focus.macos_desktop,
        "activate",
        lambda pid, title="", app_name="": calls.append((pid, title, app_name))
        or True,
    )

    value = FocusRequest(
        pid=13012, window_title="demo — zsh", working_dir="/tmp/demo"
    ).to_value()
    result = window_focus.focus_terminal(value)

    assert result.ok is True
    assert result.message == "demo — zsh"
    assert calls == [(12304, "demo — zsh", "Terminal")]


def test_focus_terminal_macos_reports_accessibility_permission(monkeypatch):
    _exercise_macos(monkeypatch)
    table = {
        13012: (12304, "/bin/zsh"),
        12304: (
            100,
            "/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
        ),
    }
    monkeypatch.setattr(window_focus.macos_desktop, "process_table", lambda: table)
    monkeypatch.setattr(
        window_focus.macos_desktop,
        "window_list",
        lambda: [MacWindow(12304, "Terminal", "demo — zsh")],
    )
    monkeypatch.setattr(
        window_focus.macos_desktop, "activate", lambda *args: False
    )
    monkeypatch.setattr(
        window_focus.macos_desktop, "accessibility_trusted", lambda: False
    )

    result = window_focus.focus_terminal('{"pid": 13012, "window_title": "demo — zsh"}')

    assert result.ok is False
    assert "辅助功能" in result.message


def test_sender_label_macos_prefers_agent_binary(monkeypatch):
    _exercise_macos(monkeypatch)
    table = {
        13012: (12304, "/usr/local/bin/claude"),
        12304: (
            100,
            "/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal",
        ),
        100: (1, "/sbin/launchd"),
    }
    monkeypatch.setattr(window_focus.macos_desktop, "process_table", lambda: table)

    assert window_focus.sender_label(13012) == "Claude Code"


def test_client_pid_macos_skips_self(monkeypatch):
    _exercise_macos(monkeypatch)
    monkeypatch.setattr(
        window_focus.macos_desktop, "client_pid", lambda local, remote: 13012
    )
    assert window_focus.client_pid(8765, 54321) == 13012
    assert window_focus.client_pid(0, 54321) is None

    monkeypatch.setattr(
        window_focus.macos_desktop, "client_pid", lambda local, remote: None
    )
    assert window_focus.client_pid(8765) is None


def test_focus_terminal_wayland_explains_limitation(monkeypatch):
    from agentbell import linux_desktop

    monkeypatch.setattr(window_focus, "_IS_MACOS", False)
    monkeypatch.setattr(window_focus, "_IS_LINUX", True)
    monkeypatch.setattr(linux_desktop, "x11_available", lambda: False)
    monkeypatch.setattr(linux_desktop, "is_wayland", lambda: True)
    result = window_focus.focus_terminal(
        json.dumps(
            {
                "pid": 1234,
                "window_title": "Terminal",
                "working_dir": "/tmp/demo",
            }
        )
    )
    assert result.ok is False
    assert "Wayland" in result.message
    assert "任务栏" in result.message
