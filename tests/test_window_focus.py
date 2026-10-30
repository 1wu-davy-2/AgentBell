from __future__ import annotations

import json

from agentbell.window_focus import parse_focus_value


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
