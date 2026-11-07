from __future__ import annotations

import asyncio
import logging
import time

import pytest

dbus_next = pytest.importorskip("dbus_next")

from dbus_next import Message, Variant  # noqa: E402

from agentbell import wayland_desktop as wd  # noqa: E402

SESSION = "/org/freedesktop/portal/desktop/session/1_42/agentbell_session"
LOGGER = logging.getLogger("test.wayland")


class FakeBus:
    unique_name = ":1.42"

    def __init__(
        self,
        *,
        response_codes: dict[str, int] | None = None,
        error_member: str = "",
        auto_activate: bool = True,
    ) -> None:
        self.handlers = []
        self.calls = []
        self.disconnected = False
        self.response_codes = response_codes or {}
        self.error_member = error_member
        self.auto_activate = auto_activate

    def add_message_handler(self, handler):
        self.handlers.append(handler)

    def remove_message_handler(self, handler):
        if handler in self.handlers:
            self.handlers.remove(handler)

    def disconnect(self):
        self.disconnected = True

    async def call(self, message):
        self.calls.append(message)
        message.serial = len(self.calls)
        if message.member == self.error_member:
            return Message.new_error(
                message,
                "org.freedesktop.DBus.Error.UnknownMethod",
                "portal is missing",
            )
        if message.member == "CreateSession":
            request = self._request_path(message.body[0]["handle_token"].value)
            self._emit_response(
                request,
                self.response_codes.get("CreateSession", 0),
                {"session_handle": Variant("s", SESSION)},
            )
            return Message.new_method_return(message, "o", [request])
        if message.member == "BindShortcuts":
            request = self._request_path(message.body[3]["handle_token"].value)
            code = self.response_codes.get("BindShortcuts", 0)
            self._emit_response(request, code, {})
            if self.auto_activate and code == 0:
                self._emit_signal(
                    wd.PORTAL_PATH,
                    wd.SHORTCUTS_INTERFACE,
                    "Activated",
                    "osta{sv}",
                    [SESSION, wd.SHORTCUT_ID, 0, {}],
                )
            return Message.new_method_return(message, "o", [request])
        return Message.new_method_return(message)

    def _request_path(self, token):
        return wd.request_path(self.unique_name, token)

    def _emit_response(self, path, code, results):
        self._emit_signal(
            path, wd.REQUEST_INTERFACE, "Response", "ua{sv}", [code, results]
        )

    def _emit_signal(self, path, interface, member, signature, body):
        message = Message.new_signal(path, interface, member, signature, body)
        for handler in list(self.handlers):
            handler(message)


def _factory(bus):
    async def factory():
        return bus

    return factory


def test_request_path_matches_portal_convention():
    assert (
        wd.request_path(":1.42", "agentbell_1")
        == "/org/freedesktop/portal/desktop/request/1_42/agentbell_1"
    )
    assert wd.request_path("", "agentbell_1") == ""


def test_variant_value_unwraps_portal_results():
    assert wd.variant_value(Variant("s", SESSION)) == SESSION
    assert wd.variant_value("plain") == "plain"


def test_portal_client_registers_and_triggers():
    bus = FakeBus()
    activations: list[bool] = []
    stop = asyncio.Event()

    def activated():
        activations.append(True)
        stop.set()

    async def scenario():
        client = wd._PortalClient(
            "Ctrl+Alt+A",
            wd.portal_trigger("Ctrl+Alt+A"),
            activated,
            LOGGER,
            bus_factory=_factory(bus),
        )
        return await asyncio.wait_for(client.run(stop), 5)

    assert asyncio.run(scenario()) is True
    assert activations == [True]
    assert [call.member for call in bus.calls] == [
        "CreateSession",
        "BindShortcuts",
        "Close",
    ]
    create, bind, close = bus.calls
    assert create.destination == wd.PORTAL_SERVICE
    assert create.path == wd.PORTAL_PATH
    assert create.signature == "a{sv}"
    token = create.body[0]["handle_token"].value
    assert token.startswith("agentbell_")
    assert bind.signature == "oa(sa{sv})sa{sv}"
    assert bind.body[0] == SESSION
    shortcut = bind.body[1][0]
    assert shortcut[0] == wd.SHORTCUT_ID
    assert shortcut[1]["preferred_trigger"].value == "CTRL+ALT+a"
    assert close.path == SESSION
    assert close.interface == wd.SESSION_INTERFACE
    assert bus.disconnected


def test_portal_client_survives_missing_portal():
    bus = FakeBus(error_member="CreateSession")
    stop = asyncio.Event()

    async def scenario():
        client = wd._PortalClient(
            "Ctrl+Alt+A",
            "CTRL+ALT+a",
            lambda: None,
            LOGGER,
            bus_factory=_factory(bus),
        )
        return await asyncio.wait_for(client.run(stop), 5)

    assert asyncio.run(scenario()) is False
    assert [call.member for call in bus.calls] == ["CreateSession"]
    assert bus.disconnected


def test_portal_client_reports_denied_binding():
    bus = FakeBus(response_codes={"BindShortcuts": 1})
    stop = asyncio.Event()

    async def scenario():
        client = wd._PortalClient(
            "Ctrl+Alt+A",
            "CTRL+ALT+a",
            lambda: None,
            LOGGER,
            bus_factory=_factory(bus),
        )
        return await asyncio.wait_for(client.run(stop), 5)

    assert asyncio.run(scenario()) is False
    assert [call.member for call in bus.calls] == [
        "CreateSession",
        "BindShortcuts",
        "Close",
    ]
    assert bus.disconnected


def test_portal_client_handles_missing_session_bus():
    async def failing():
        raise OSError("no session bus")

    stop = asyncio.Event()

    async def scenario():
        client = wd._PortalClient(
            "Ctrl+Alt+A", "CTRL+ALT+a", lambda: None, LOGGER, bus_factory=failing
        )
        return await asyncio.wait_for(client.run(stop), 5)

    assert asyncio.run(scenario()) is False


def test_portal_client_filters_activation_by_shortcut_and_session():
    activations: list[int] = []
    client = wd._PortalClient(
        "Ctrl+Alt+A", "CTRL+ALT+a", lambda: activations.append(1), LOGGER
    )
    client._session = SESSION

    def signal(path, shortcut, session):
        return Message.new_signal(
            wd.PORTAL_PATH,
            wd.SHORTCUTS_INTERFACE,
            "Activated",
            "osta{sv}",
            [session, shortcut, 0, {}],
        )

    client._on_message(signal(wd.PORTAL_PATH, "other", SESSION))
    client._on_message(signal(wd.PORTAL_PATH, wd.SHORTCUT_ID, "/other/session"))
    assert activations == []
    client._on_message(signal(wd.PORTAL_PATH, wd.SHORTCUT_ID, SESSION))
    assert activations == [1]


def test_wayland_hotkey_degrades_without_dbus(monkeypatch):
    monkeypatch.setattr(wd, "Message", None)
    monkeypatch.setattr(wd, "MessageBus", None)
    hotkey = wd.WaylandHotkey("Ctrl+Alt+A", LOGGER)
    assert hotkey.start() is False


def test_wayland_hotkey_bridges_portal_and_qt_signals():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance() or QCoreApplication([])
    bus = FakeBus()
    hotkey = wd.WaylandHotkey(
        "Ctrl+Alt+A", LOGGER, bus_factory=_factory(bus)
    )
    received: list[bool] = []
    hotkey.activated.connect(lambda: received.append(True))
    try:
        assert hotkey.start() is True
        deadline = time.monotonic() + 5
        while not received and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
    finally:
        hotkey.stop()
    assert received == [True]
    assert bus.disconnected is True