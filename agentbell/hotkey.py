from __future__ import annotations

import ctypes
import logging
import os
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal
from PySide6.QtWidgets import QApplication

_IS_WINDOWS = os.name == "nt"
_WM_HOTKEY = 0x0312
_MOD_NOREPEAT = 0x4000
_MODIFIERS = {
    "ctrl": 0x0002,
    "control": 0x0002,
    "alt": 0x0001,
    "shift": 0x0004,
    "win": 0x0008,
    "meta": 0x0008,
}
_NAMED_KEYS = {
    "space": 0x20,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "esc": 0x1B,
    "escape": 0x1B,
    "insert": 0x2D,
    "delete": 0x2E,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
for _index in range(1, 25):
    _NAMED_KEYS[f"f{_index}"] = 0x6F + _index

_hotkey_counter = 0x4A00
_user32 = ctypes.WinDLL("user32", use_last_error=True) if _IS_WINDOWS else None
if _user32 is not None:  # pragma: no branch - platform dependent
    _user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """Parse strings such as Ctrl+Alt+A into (modifiers, virtual-key code)."""
    parts = [part.strip().lower() for part in (spec or "").split("+") if part.strip()]
    if len(parts) < 2:
        return None
    modifiers = 0
    key: int | None = None
    for part in parts:
        if part in _MODIFIERS:
            modifiers |= _MODIFIERS[part]
            continue
        if key is not None:
            return None
        if len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif part in _NAMED_KEYS:
            key = _NAMED_KEYS[part]
        else:
            return None
    if key is None or modifiers == 0:
        return None
    return modifiers, key


class _HotkeyFilter(QAbstractNativeEventFilter):
    def __init__(self, hotkey_id: int, callback) -> None:
        super().__init__()
        self._hotkey_id = hotkey_id
        self._callback = callback

    def nativeEventFilter(self, event_type, message):  # type: ignore[override]
        try:
            msg = wintypes.MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False
        if msg.message == _WM_HOTKEY and int(msg.wParam) == self._hotkey_id:
            self._callback()
            return True
        return False


class GlobalHotkey(QObject):
    activated = Signal()

    def __init__(
        self,
        spec: str,
        logger: logging.Logger,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logger
        self._spec = spec
        self._id: int | None = None
        self._filter: _HotkeyFilter | None = None

    @property
    def spec(self) -> str:
        return self._spec

    @property
    def registered(self) -> bool:
        return self._id is not None

    def register(self) -> bool:
        self.unregister()
        global _hotkey_counter
        parsed = parse_hotkey(self._spec)
        if parsed is None:
            self._logger.warning("全局快捷键格式无效，已忽略：%s", self._spec or "(空)")
            return False
        if not _IS_WINDOWS:
            return False
        application = QApplication.instance()
        if application is None:
            return False

        modifiers, virtual_key = parsed
        _hotkey_counter += 1
        hotkey_id = _hotkey_counter
        if not _user32.RegisterHotKey(
            None, hotkey_id, modifiers | _MOD_NOREPEAT, virtual_key
        ):
            self._logger.warning(
                "注册全局快捷键失败（可能已被其他程序占用）：%s", self._spec
            )
            return False

        self._id = hotkey_id
        self._filter = _HotkeyFilter(hotkey_id, self.activated.emit)
        application.installNativeEventFilter(self._filter)
        self._logger.info("全局快捷键已注册：%s", self._spec)
        return True

    def apply(self, spec: str) -> bool:
        self._spec = spec
        return self.register()

    def unregister(self) -> None:
        if self._id is None:
            return
        application = QApplication.instance()
        if _IS_WINDOWS and _user32 is not None:
            _user32.UnregisterHotKey(None, self._id)
        if application is not None and self._filter is not None:
            application.removeNativeEventFilter(self._filter)
        self._filter = None
        self._id = None
