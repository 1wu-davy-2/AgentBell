from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal

from agentbell import hotkey as hotkey_module
from agentbell import linux_desktop, wayland_desktop
from agentbell.hotkey import parse_hotkey
from agentbell.macos_desktop import parse_macos_hotkey


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


def test_parse_macos_hotkey_maps_carbon_modifiers_and_keycodes():
    assert parse_macos_hotkey("Cmd+Shift+A") == (0x0100 | 0x0200, 0)
    assert parse_macos_hotkey("Ctrl+Alt+A") == (0x1000 | 0x0800, 0)
    assert parse_macos_hotkey("Cmd+F12") == (0x0100, 111)
    assert parse_macos_hotkey("Option+Space") == (0x0800, 49)
    assert parse_macos_hotkey("Ctrl+Return") == (0x1000, 36)
    assert parse_macos_hotkey("Meta+PageUp") == (0x0100, 116)


def test_parse_macos_hotkey_rejects_invalid_specs():
    assert parse_macos_hotkey("") is None
    assert parse_macos_hotkey("A") is None
    assert parse_macos_hotkey("Cmd") is None
    assert parse_macos_hotkey("Cmd+A+B") is None
    assert parse_macos_hotkey("Cmd+Unknown") is None


class _FakePortalHotkey(QObject):
    activated = Signal()

    def __init__(self, spec, logger, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True
        return True

    def stop(self):
        self.stopped = True


def test_linux_wayland_uses_portal_hotkey(monkeypatch):
    monkeypatch.setattr(linux_desktop, "is_wayland", lambda: True)
    monkeypatch.setattr(wayland_desktop, "WaylandHotkey", _FakePortalHotkey)
    hotkey = hotkey_module.GlobalHotkey("Ctrl+Alt+A", logging.getLogger("test"))
    assert hotkey._register_linux() is True
    grabber = hotkey._linux
    assert isinstance(grabber, _FakePortalHotkey)
    assert grabber.started is True
    assert hotkey.registered is True
    triggered = []
    hotkey.activated.connect(lambda: triggered.append(True))
    grabber.activated.emit()
    assert triggered == [True]
    hotkey.unregister()
    assert grabber.stopped is True
    assert hotkey._linux is None


def test_linux_wayland_rejects_invalid_hotkey(monkeypatch):
    monkeypatch.setattr(linux_desktop, "is_wayland", lambda: True)
    created = []

    def fake_portal(spec, logger, parent=None):
        created.append(spec)
        return _FakePortalHotkey(spec, logger, parent)

    monkeypatch.setattr(wayland_desktop, "WaylandHotkey", fake_portal)
    hotkey = hotkey_module.GlobalHotkey("Hyper+A", logging.getLogger("test"))
    assert hotkey._register_linux() is False
    assert created == []
