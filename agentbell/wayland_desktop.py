from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import Awaitable, Callable

from PySide6.QtCore import QObject, Signal

from .linux_desktop import portal_trigger

try:
    from dbus_next import Message, MessageType, Variant
    from dbus_next.aio import MessageBus
except Exception:  # pragma: no cover - optional dependency
    Message = None
    MessageType = None
    Variant = None
    MessageBus = None

PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
PORTAL_PATH = "/org/freedesktop/portal/desktop"
SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts"
REQUEST_INTERFACE = "org.freedesktop.portal.Request"
SESSION_INTERFACE = "org.freedesktop.portal.Session"
SHORTCUT_ID = "agentbell-open-center"
SHORTCUT_DESCRIPTION = "打开 AgentBell 通知中心"
CREATE_TIMEOUT = 10.0
BIND_TIMEOUT = 180.0

PortalHandler = Callable[[object], bool]


class PortalError(RuntimeError):
    pass


def dbus_available() -> bool:
    return Message is not None and MessageBus is not None


async def open_session_bus():
    bus = MessageBus()
    return await bus.connect()


def request_path(unique_name: str, token: str) -> str:
    sender = (unique_name or "").lstrip(":").replace(".", "_")
    if not sender or not token:
        return ""
    return f"/org/freedesktop/portal/desktop/request/{sender}/{token}"


def variant_value(value):
    if Variant is not None and isinstance(value, Variant):
        return value.value
    return value


class _PortalClient:
    """XDG GlobalShortcuts client driven by its own asyncio loop."""

    def __init__(
        self,
        spec: str,
        trigger: str,
        on_activated: Callable[[], None],
        logger: logging.Logger,
        bus_factory: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        self._spec = spec
        self._trigger = trigger
        self._on_activated = on_activated
        self._logger = logger
        self._bus_factory = bus_factory or open_session_bus
        self._bus = None
        self._session = ""
        self._pending: dict[str, asyncio.Future] = {}
        self._seen: dict[str, tuple[int, dict]] = {}
        self._sequence = 0

    async def run(self, stop: asyncio.Event) -> bool:
        try:
            bus = await self._bus_factory()
        except Exception as exc:
            self._logger.warning(
                "Wayland 全局快捷键不可用：无法连接会话 D-Bus（%s）", exc
            )
            return False
        self._bus = bus
        bus.add_message_handler(self._on_message)
        registration = asyncio.create_task(self._register())
        stopper = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait(
                {registration, stopper}, return_when=asyncio.FIRST_COMPLETED
            )
            if registration in done:
                try:
                    await registration
                except PortalError as exc:
                    self._logger.warning("Wayland 全局快捷键注册失败：%s", exc)
                    return False
                except Exception as exc:
                    self._logger.warning(
                        "Wayland 全局快捷键注册失败（%s）", exc
                    )
                    return False
                self._logger.info(
                    "Wayland 全局快捷键已通过 XDG 门户注册：%s", self._spec
                )
            await stopper
            return True
        finally:
            if not registration.done():
                registration.cancel()
                try:
                    await registration
                except BaseException:
                    pass
            if not stopper.done():
                stopper.cancel()
                try:
                    await stopper
                except BaseException:
                    pass
            await self._close()

    async def _register(self) -> None:
        self._session = await self._create_session()
        await self._bind()

    async def _create_session(self) -> str:
        token = self._token("create")
        future = self._expect(token)
        reply = await self._bus.call(
            self._message(
                PORTAL_PATH,
                SHORTCUTS_INTERFACE,
                "CreateSession",
                "a{sv}",
                [
                    {
                        "handle_token": Variant("s", token),
                        "session_handle_token": Variant("s", f"{token}_session"),
                    }
                ],
            )
        )
        self._check_reply(reply, "创建全局快捷键会话")
        future = self._adopt(self._body_path(reply), future)
        results = await self._response(
            future, "创建全局快捷键会话", CREATE_TIMEOUT
        )
        session = str(variant_value(results.get("session_handle")) or "")
        if not session.startswith("/"):
            raise PortalError("门户没有返回有效的会话句柄")
        return session

    async def _bind(self) -> None:
        token = self._token("bind")
        future = self._expect(token)
        shortcut = [
            SHORTCUT_ID,
            {
                "description": Variant("s", SHORTCUT_DESCRIPTION),
                "preferred_trigger": Variant("s", self._trigger),
            },
        ]
        reply = await self._bus.call(
            self._message(
                PORTAL_PATH,
                SHORTCUTS_INTERFACE,
                "BindShortcuts",
                "oa(sa{sv})sa{sv}",
                [
                    self._session,
                    [shortcut],
                    "",
                    {"handle_token": Variant("s", token)},
                ],
            )
        )
        self._check_reply(reply, "绑定全局快捷键")
        future = self._adopt(self._body_path(reply), future)
        await self._response(future, "绑定全局快捷键", BIND_TIMEOUT)

    async def _close(self) -> None:
        bus = self._bus
        session = self._session
        self._bus = None
        self._session = ""
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        self._seen.clear()
        if bus is None:
            return
        if session:
            try:
                await bus.call(
                    self._message(
                        session, SESSION_INTERFACE, "Close", "", []
                    )
                )
            except Exception:
                pass
        try:
            bus.remove_message_handler(self._on_message)
        except Exception:
            pass
        try:
            bus.disconnect()
        except Exception:
            pass

    def _message(
        self, path: str, interface: str, member: str, signature: str, body: list
    ):
        return Message(
            destination=PORTAL_SERVICE,
            path=path,
            interface=interface,
            member=member,
            signature=signature,
            body=body,
        )

    def _token(self, purpose: str) -> str:
        self._sequence += 1
        return f"agentbell_{os.getpid()}_{purpose}_{self._sequence}"

    def _expect(self, token: str) -> asyncio.Future | None:
        path = request_path(
            str(getattr(self._bus, "unique_name", "") or ""), token
        )
        if not path:
            return None
        future = asyncio.get_running_loop().create_future()
        self._pending[path] = future
        return future

    def _adopt(self, path: str, future: asyncio.Future | None):
        if not path:
            return future
        existing = self._pending.get(path)
        if existing is not None:
            return existing
        seen = self._seen.pop(path, None)
        if future is not None:
            if seen is not None and not future.done():
                future.set_result(seen)
            elif not future.done():
                self._pending[path] = future
            return future
        if seen is not None:
            done = asyncio.get_running_loop().create_future()
            done.set_result(seen)
            return done
        future = asyncio.get_running_loop().create_future()
        self._pending[path] = future
        return future

    async def _response(
        self, future: asyncio.Future | None, action: str, timeout: float
    ) -> dict:
        if future is None:
            raise PortalError(f"{action}未返回请求路径")
        try:
            code, results = await asyncio.wait_for(
                asyncio.shield(future), timeout
            )
        except asyncio.TimeoutError as exc:
            raise PortalError(f"{action}等待授权超时") from exc
        finally:
            self._forget(future)
        if code != 0:
            raise PortalError(f"{action}被取消或拒绝（响应码 {code}）")
        return results

    def _forget(self, future: asyncio.Future) -> None:
        for path, pending in list(self._pending.items()):
            if pending is future:
                self._pending.pop(path, None)

    @staticmethod
    def _body_path(reply) -> str:
        body = getattr(reply, "body", None) or []
        if not body:
            return ""
        value = body[0]
        return str(value) if value else ""

    @staticmethod
    def _check_reply(reply, action: str) -> None:
        if reply is None:
            raise PortalError(f"{action}没有收到门户响应")
        if reply.message_type == MessageType.ERROR:
            detail = (reply.body or [""])[0]
            raise PortalError(
                f"{action}失败（{reply.error_name or '未知错误'}）：{detail}"
            )
        if reply.message_type != MessageType.METHOD_RETURN:
            raise PortalError(f"{action}返回了意外的消息类型")

    def _on_message(self, message) -> bool:
        if MessageType is None or message.message_type != MessageType.SIGNAL:
            return False
        if (
            message.path == PORTAL_PATH
            and message.interface == SHORTCUTS_INTERFACE
        ):
            if message.member == "Activated":
                body = message.body or []
                shortcut = str(body[1]) if len(body) > 1 else ""
                session = str(body[0]) if body else ""
                if shortcut != SHORTCUT_ID:
                    return False
                if self._session and session and session != self._session:
                    return False
                try:
                    self._on_activated()
                except Exception:
                    self._logger.exception("Wayland 快捷键回调执行失败")
            elif message.member == "Deactivated":
                self._logger.warning(
                    "Wayland 快捷键已被桌面环境停用：%s", self._spec
                )
            return False
        if (
            message.interface == REQUEST_INTERFACE
            and message.member == "Response"
        ):
            body = message.body or []
            code = int(body[0]) if body else 2
            results = (
                body[1]
                if len(body) > 1 and isinstance(body[1], dict)
                else {}
            )
            future = self._pending.pop(message.path, None)
            if future is not None and not future.done():
                future.set_result((code, results))
            else:
                self._seen[message.path] = (code, results)
        return False


class WaylandHotkey(QObject):
    activated = Signal()

    def __init__(
        self,
        spec: str,
        logger: logging.Logger,
        parent: QObject | None = None,
        bus_factory: Callable[[], Awaitable[object]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._spec = spec
        self._logger = logger
        self._bus_factory = bus_factory
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._client: _PortalClient | None = None
        self._stopping = False
        self._stop_requested = threading.Event()

    def start(self) -> bool:
        if not dbus_available():
            self._logger.warning(
                "Wayland 全局快捷键不可用：缺少 dbus-next 组件"
            )
            return False
        trigger = portal_trigger(self._spec)
        if trigger is None:
            return False
        self._stopping = False
        self._stop_requested.clear()
        self._client = _PortalClient(
            self._spec,
            trigger,
            self._emit_activated,
            self._logger,
            bus_factory=self._bus_factory,
        )
        self._thread = threading.Thread(
            target=self._run,
            name="agentbell-wayland-hotkey",
            daemon=True,
        )
        self._thread.start()
        return True

    def _emit_activated(self) -> None:
        if not self._stopping:
            self.activated.emit()

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        stop = asyncio.Event()
        self._stop = stop
        if self._stop_requested.is_set():
            stop.set()
        client = self._client
        try:
            asyncio.set_event_loop(loop)
            if client is not None:
                loop.run_until_complete(client.run(stop))
        except Exception:
            self._logger.exception("Wayland 快捷键线程异常退出")
        finally:
            self._loop = None
            self._stop = None
            loop.close()

    def stop(self) -> None:
        self._stopping = True
        self._stop_requested.set()
        loop = self._loop
        stop = self._stop
        if loop is not None and stop is not None:
            try:
                loop.call_soon_threadsafe(stop.set)
            except RuntimeError:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.5)
        self._thread = None
        self._client = None