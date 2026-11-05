from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_ANY_PROPERTY_TYPE = 0
_IS_VIEWABLE = 2
_REVERT_TO_POINTER_ROOT = 1
_SUBSTRUCTURE_NOTIFY = 0x00080000
_SUBSTRUCTURE_REDIRECT = 0x00100000
_CURRENT_TIME = 0
_KEY_PRESS = 2
_GRAB_MODE_ASYNC = 1
_LOCK_MASK = 0x0002
_MOD2_MASK = 0x0010
_CONTROL_MASK = 0x0004
_SHIFT_MASK = 0x0001
_MOD1_MASK = 0x0008
_MOD4_MASK = 0x0040


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("border_width", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p),
        ("root", ctypes.c_ulong),
        ("class_", ctypes.c_int),
        ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong),
        ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int),
        ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long),
        ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int),
        ("screen", ctypes.c_void_p),
    ]


class _XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", ctypes.c_long * 5),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [
        ("type", ctypes.c_int),
        ("xclient", _XClientMessageEvent),
        ("pad", ctypes.c_long * 24),
    ]


_X_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


@dataclass(frozen=True, slots=True)
class XWindow:
    handle: int
    pid: int
    title: str
    class_name: str
    fullscreen: bool


def session_type() -> str:
    return (os.environ.get("XDG_SESSION_TYPE") or "").strip().lower()


def is_wayland() -> bool:
    return session_type() == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))


def x11_available() -> bool:
    return not is_wayland() and bool(os.environ.get("DISPLAY"))


def process_name(pid: int) -> str:
    if not isinstance(pid, int) or pid <= 0:
        return ""
    try:
        text = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text.strip().lower()


def process_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return table
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            raw = Path(f"/proc/{pid}/stat").read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            continue
        close = raw.rfind(")")
        if close < 0:
            continue
        fields = raw[close + 2 :].split()
        if len(fields) < 2:
            continue
        try:
            parent = int(fields[1])
        except ValueError:
            continue
        name = process_name(pid)
        table[pid] = (parent, name)
    return table


def process_ancestors(pid: int, table: dict[int, tuple[int, str]]) -> list[int]:
    chain: list[int] = []
    current = pid
    while current > 0 and current not in chain and len(chain) < 16:
        chain.append(current)
        current = table.get(current, (0, ""))[0]
    return chain


def _tcp_socket_inode(local_port: int, remote_port: int | None) -> int | None:
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text(encoding="ascii", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[1:]:
            parts = line.split()
            if len(parts) < 10 or parts[3] != "01":
                continue
            try:
                local = int(parts[1].rsplit(":", 1)[1], 16)
                remote = int(parts[2].rsplit(":", 1)[1], 16)
                inode = int(parts[9])
            except (ValueError, IndexError):
                continue
            if local != local_port:
                continue
            if remote_port is not None and remote != remote_port:
                continue
            if inode > 0:
                return inode
    return None


def pid_for_socket_inode(inode: int) -> int | None:
    marker = f"socket:[{inode}]"
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    own = os.getpid()
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == own:
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            handles = os.listdir(fd_dir)
        except OSError:
            continue
        for handle in handles:
            try:
                if os.readlink(f"{fd_dir}/{handle}") == marker:
                    return pid
            except OSError:
                continue
    return None


def client_pid_for_port(local_port: int, remote_port: int | None = None) -> int | None:
    if not isinstance(local_port, int) or local_port <= 0:
        return None
    inode = _tcp_socket_inode(local_port, remote_port)
    if inode is None:
        return None
    return pid_for_socket_inode(inode)


class X11:
    """Small Xlib bridge used by focus, presence and global hotkeys."""

    def __init__(self) -> None:
        self._lib: ctypes.CDLL | None = None
        self._display: int | None = None
        self._root: int = 0
        self._atoms: dict[str, int] = {}

    @property
    def display(self) -> int | None:
        return self._display

    @property
    def lib(self) -> ctypes.CDLL | None:
        return self._lib

    def open(self) -> bool:
        if self._display:
            return True
        if not x11_available():
            return False
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        try:
            lib = ctypes.CDLL(name)
        except OSError:
            return False
        self._configure(lib)
        display = lib.XOpenDisplay(None)
        if not display:
            return False
        self._lib = lib
        self._display = display
        self._root = int(lib.XDefaultRootWindow(display))
        return True

    @staticmethod
    def _configure(lib: ctypes.CDLL) -> None:
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        lib.XGetWindowProperty.restype = ctypes.c_int
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XQueryTree.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong)),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XQueryTree.restype = ctypes.c_int
        lib.XGetWindowAttributes.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(_XWindowAttributes),
        ]
        lib.XGetWindowAttributes.restype = ctypes.c_int
        lib.XGetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.XGetInputFocus.restype = ctypes.c_int
        lib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.POINTER(_XEvent),
        ]
        lib.XSendEvent.restype = ctypes.c_int
        lib.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XSetInputFocus.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_ulong,
        ]
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        lib.XKeysymToKeycode.restype = ctypes.c_ubyte
        lib.XStringToKeysym.argtypes = [ctypes.c_char_p]
        lib.XStringToKeysym.restype = ctypes.c_ulong
        lib.XGrabKey.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
        ]
        lib.XGrabKey.restype = ctypes.c_int
        lib.XUngrabKey.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_ulong,
        ]
        lib.XPending.argtypes = [ctypes.c_void_p]
        lib.XPending.restype = ctypes.c_int
        lib.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.XNextEvent.restype = ctypes.c_int
        lib.XSetErrorHandler.argtypes = [ctypes.c_void_p]
        lib.XSetErrorHandler.restype = ctypes.c_void_p

    def close(self) -> None:
        if self._lib is not None and self._display:
            try:
                self._lib.XCloseDisplay(self._display)
            except Exception:
                pass
        self._display = None
        self._root = 0
        self._atoms.clear()

    def root(self) -> int:
        return self._root

    def atom(self, name: str) -> int:
        if name in self._atoms:
            return self._atoms[name]
        if not self.open() or self._lib is None or not self._display:
            return 0
        atom = int(self._lib.XInternAtom(self._display, name.encode(), 0))
        self._atoms[name] = atom
        return atom

    def _property(self, window: int, name: str) -> tuple[int, bytes]:
        if not self.open() or self._lib is None or not self._display:
            return 0, b""
        atom = self.atom(name)
        if not atom:
            return 0, b""
        actual_type = ctypes.c_ulong()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop = ctypes.POINTER(ctypes.c_ubyte)()
        status = self._lib.XGetWindowProperty(
            self._display,
            window,
            atom,
            0,
            1024,
            0,
            _ANY_PROPERTY_TYPE,
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(prop),
        )
        if status != 0 or not prop:
            return 0, b""
        try:
            fmt = int(actual_format.value)
            # Xlib returns format 32 data as an array of C longs, not 4-byte ints.
            per_item = ctypes.sizeof(ctypes.c_long) if fmt == 32 else max(1, fmt // 8)
            return fmt, ctypes.string_at(prop, int(nitems.value) * per_item)
        finally:
            self._lib.XFree(prop)

    def _cardinals(self, window: int, name: str) -> list[int]:
        fmt, raw = self._property(window, name)
        if fmt != 32 or not raw:
            return []
        width = ctypes.sizeof(ctypes.c_long)
        return [
            int.from_bytes(raw[offset : offset + width], sys.byteorder)
            for offset in range(0, len(raw) - width + 1, width)
        ]

    def title(self, window: int) -> str:
        for name in ("_NET_WM_NAME", "WM_NAME"):
            _, raw = self._property(window, name)
            if raw:
                text = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
                if text.strip():
                    return " ".join(text.split())
        return ""

    def class_name(self, window: int) -> str:
        _, raw = self._property(window, "WM_CLASS")
        if not raw:
            return ""
        parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\x00")]
        parts = [part.strip() for part in parts if part.strip()]
        return parts[-1] if parts else ""

    def pid(self, window: int) -> int:
        values = self._cardinals(window, "_NET_WM_PID")
        return values[0] if values else 0

    def fullscreen(self, window: int) -> bool:
        values = set(self._cardinals(window, "_NET_WM_STATE"))
        target = self.atom("_NET_WM_STATE_FULLSCREEN")
        return bool(target) and target in values

    def viewable(self, window: int) -> bool:
        if not self.open() or self._lib is None or not self._display:
            return False
        info = _XWindowAttributes()
        if not self._lib.XGetWindowAttributes(
            self._display, window, ctypes.byref(info)
        ):
            return False
        return info.map_state == _IS_VIEWABLE and info.width > 1 and info.height > 1

    def active_window(self) -> int:
        values = self._cardinals(self.root(), "_NET_ACTIVE_WINDOW")
        if values and values[0] > 1:
            return values[0]
        if not self.open() or self._lib is None or not self._display:
            return 0
        window = ctypes.c_ulong(0)
        revert = ctypes.c_int(0)
        self._lib.XGetInputFocus(
            self._display, ctypes.byref(window), ctypes.byref(revert)
        )
        # 0/1 mean None/PointerRoot rather than a real client window.
        return int(window.value) if int(window.value) > 1 else 0

    def client_windows(self) -> list[int]:
        windows = self._cardinals(self.root(), "_NET_CLIENT_LIST")
        if windows:
            return windows
        if not self.open() or self._lib is None or not self._display:
            return []
        root_return = ctypes.c_ulong()
        parent_return = ctypes.c_ulong()
        children = ctypes.POINTER(ctypes.c_ulong)()
        count = ctypes.c_uint(0)
        if not self._lib.XQueryTree(
            self._display,
            self._root,
            ctypes.byref(root_return),
            ctypes.byref(parent_return),
            ctypes.byref(children),
            ctypes.byref(count),
        ):
            return []
        try:
            return [int(children[index]) for index in range(count.value)]
        finally:
            if children:
                self._lib.XFree(children)

    def windows(self) -> list[XWindow]:
        own_pid = os.getpid()
        result: list[XWindow] = []
        seen: set[int] = set()
        for handle in self.client_windows():
            if handle in seen or not self.viewable(handle):
                continue
            seen.add(handle)
            title = self.title(handle)
            pid = self.pid(handle)
            if not title or pid == own_pid:
                continue
            result.append(
                XWindow(
                    handle=handle,
                    pid=pid,
                    title=title,
                    class_name=self.class_name(handle),
                    fullscreen=self.fullscreen(handle),
                )
            )
        return result

    def active_info(self) -> XWindow | None:
        handle = self.active_window()
        if not handle or not self.viewable(handle):
            return None
        title = self.title(handle)
        if not title:
            return None
        return XWindow(
            handle=handle,
            pid=self.pid(handle),
            title=title,
            class_name=self.class_name(handle),
            fullscreen=self.fullscreen(handle),
        )

    def activate(self, handle: int) -> bool:
        if not self.open() or self._lib is None or not self._display or not handle:
            return False
        event = _XEvent()
        event.xclient.type = 33
        event.xclient.send_event = 1
        event.xclient.display = self._display
        event.xclient.window = handle
        event.xclient.message_type = self.atom("_NET_ACTIVE_WINDOW")
        event.xclient.format = 32
        event.xclient.data[0] = 1
        event.xclient.data[1] = _CURRENT_TIME
        event.xclient.data[2] = 0
        self._lib.XSendEvent(
            self._display,
            self._root,
            0,
            _SUBSTRUCTURE_REDIRECT | _SUBSTRUCTURE_NOTIFY,
            ctypes.byref(event),
        )
        self._lib.XRaiseWindow(self._display, handle)
        self._lib.XSetInputFocus(
            self._display, handle, _REVERT_TO_POINTER_ROOT, _CURRENT_TIME
        )
        self._lib.XSync(self._display, 0)
        deadline = time.monotonic() + 0.15
        while time.monotonic() < deadline:
            if self.active_window() == handle:
                return True
            time.sleep(0.02)
        return False


_X11 = X11()


def x11() -> X11:
    return _X11


def foreground_window() -> XWindow | None:
    if not x11_available():
        return None
    try:
        return _X11.active_info()
    except Exception:
        return None


def foreground_fullscreen() -> bool:
    window = foreground_window()
    if window is None or window.pid == os.getpid():
        return False
    return window.fullscreen


def foreground_process_name() -> str:
    window = foreground_window()
    return process_name(window.pid) if window else ""


def foreground_window_class() -> str:
    window = foreground_window()
    return window.class_name if window else ""


def _logind_session_path(bus) -> str:
    from PySide6.QtDBus import QDBusMessage

    message = QDBusMessage.createMethodCall(
        "org.freedesktop.login1",
        "/org/freedesktop/login1",
        "org.freedesktop.login1.Manager",
        "GetSession",
    )
    message.setArguments(["auto"])
    reply = bus.call(message)
    if reply.type() != QDBusMessage.MessageType.ReplyMessage:
        return ""
    arguments = reply.arguments()
    if not arguments:
        return ""
    value = arguments[0]
    path = value.path() if hasattr(value, "path") else str(value)
    return path if path.startswith("/org/freedesktop/login1/session/") else ""


def _logind_property(name: str):
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusMessage
    except Exception:
        return None
    try:
        bus = QDBusConnection.systemBus()
        if not bus.isConnected():
            return None
        path = _logind_session_path(bus)
        if not path:
            return None
        message = QDBusMessage.createMethodCall(
            "org.freedesktop.login1",
            path,
            "org.freedesktop.DBus.Properties",
            "Get",
        )
        message.setArguments(["org.freedesktop.login1.Session", name])
        reply = bus.call(message)
        if reply.type() != QDBusMessage.MessageType.ReplyMessage:
            return None
        arguments = reply.arguments()
        if not arguments:
            return None
        value = arguments[0]
        if hasattr(value, "value") and not isinstance(
            value, (str, int, float, bool)
        ):
            try:
                value = value.value()
            except Exception:
                pass
        return value
    except Exception:
        return None


def session_locked() -> bool:
    try:
        return bool(_logind_property("LockedHint"))
    except Exception:
        return False


def idle_seconds() -> float:
    try:
        idle_hint = _logind_property("IdleHint")
        if not idle_hint:
            return 0.0
        since = _logind_property("IdleSinceHintMonotonic")
        if isinstance(since, int) and since > 0:
            return max(0.0, time.monotonic() - since / 1_000_000.0)
        since = _logind_property("IdleSinceHint")
        if isinstance(since, int) and since > 0:
            return max(0.0, time.time() - since / 1_000_000.0)
        return 1e9
    except Exception:
        return 0.0


def hotkey_keycode(lib: ctypes.CDLL, display: int, keysym_name: str) -> int:
    keysym = lib.XStringToKeysym(keysym_name.encode())
    if not keysym:
        return 0
    return int(lib.XKeysymToKeycode(display, keysym))


def modifier_masks(spec: str) -> tuple[int, str] | None:
    modifiers = 0
    key = ""
    names = {
        "ctrl": _CONTROL_MASK,
        "control": _CONTROL_MASK,
        "alt": _MOD1_MASK,
        "shift": _SHIFT_MASK,
        "win": _MOD4_MASK,
        "meta": _MOD4_MASK,
        "super": _MOD4_MASK,
    }
    keysyms = {
        "space": "space",
        "enter": "Return",
        "return": "Return",
        "tab": "Tab",
        "esc": "Escape",
        "escape": "Escape",
        "insert": "Insert",
        "delete": "Delete",
        "home": "Home",
        "end": "End",
        "pageup": "Prior",
        "pagedown": "Next",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
    }
    for part in (part.strip().lower() for part in (spec or "").split("+")):
        if not part:
            continue
        if part in names:
            modifiers |= names[part]
        elif len(part) == 1 and part.isalnum():
            if key:
                return None
            key = part.upper() if part.isalpha() else part
        elif part in keysyms:
            if key:
                return None
            key = keysyms[part]
        elif part.startswith("f") and part[1:].isdigit() and 1 <= int(part[1:]) <= 24:
            if key:
                return None
            key = f"F{int(part[1:])}"
        else:
            return None
    if not key or not modifiers:
        return None
    return modifiers, key


class X11Hotkey:
    def __init__(self, spec: str) -> None:
        self._spec = spec
        self._x11 = X11()
        self._handler = None
        self._previous_handler = None
        self._error = False
        self._grabs: list[tuple[int, int]] = []

    def _on_error(self, _display, _event) -> int:
        self._error = True
        return 0

    def start(self) -> bool:
        parsed = modifier_masks(self._spec)
        if parsed is None or not self._x11.open():
            return False
        assert self._x11.lib is not None
        assert self._x11.display is not None
        keycode = hotkey_keycode(self._x11.lib, self._x11.display, parsed[1])
        if not keycode:
            return False
        modifiers = parsed[0]
        self._handler = _X_ERROR_HANDLER(self._on_error)
        self._previous_handler = self._x11.lib.XSetErrorHandler(
            ctypes.cast(self._handler, ctypes.c_void_p)
        )
        for extra in (0, _LOCK_MASK, _MOD2_MASK, _LOCK_MASK | _MOD2_MASK):
            mask = modifiers | extra
            self._x11.lib.XGrabKey(
                self._x11.display,
                keycode,
                mask,
                self._x11.root(),
                1,
                _GRAB_MODE_ASYNC,
                _GRAB_MODE_ASYNC,
            )
            self._grabs.append((keycode, mask))
        self._x11.lib.XSync(self._x11.display, 0)
        if self._error:
            self.stop()
            return False
        return True

    def poll(self) -> bool:
        if not self._x11.open() or self._x11.lib is None or not self._x11.display:
            return False
        lib = self._x11.lib
        display = self._x11.display
        if not lib.XPending(display):
            return False
        triggered = False
        while lib.XPending(display):
            event = _XEvent()
            lib.XNextEvent(display, ctypes.byref(event))
            if event.type == _KEY_PRESS:
                triggered = True
        return triggered

    def stop(self) -> None:
        if self._x11.lib is not None and self._x11.display is not None:
            for keycode, mask in self._grabs:
                try:
                    self._x11.lib.XUngrabKey(
                        self._x11.display, keycode, mask, self._x11.root()
                    )
                except Exception:
                    pass
            try:
                self._x11.lib.XSync(self._x11.display, 0)
            except Exception:
                pass
            if self._previous_handler is not None:
                try:
                    self._x11.lib.XSetErrorHandler(self._previous_handler)
                except Exception:
                    pass
        self._grabs.clear()
        self._handler = None
        self._previous_handler = None
        self._x11.close()
