from __future__ import annotations

from agentbell.hotkey import parse_hotkey


def test_parse_hotkey_common_combinations():
    assert parse_hotkey("Ctrl+Alt+A") == (0x0002 | 0x0001, ord("A"))
    assert parse_hotkey("control+shift+space") == (0x0002 | 0x0004, 0x20)
    assert parse_hotkey("Win+F12") == (0x0008, 0x6F + 12)
    assert parse_hotkey(" Alt + Z ") == (0x0001, ord("Z"))


def test_parse_hotkey_rejects_invalid_specs():
    assert parse_hotkey("") is None
    assert parse_hotkey("A") is None
    assert parse_hotkey("Ctrl+Alt") is None
    assert parse_hotkey("Ctrl+A+B") is None
    assert parse_hotkey("Ctrl+Unknown") is None
