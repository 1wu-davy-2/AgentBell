from __future__ import annotations

import json

import agentbell.window_focus as window_focus
from agentbell.window_focus import (
    FocusRequest,
    FocusTarget,
    _WindowInfo,
    find_focus_choices,
    parse_focus_value,
)


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
