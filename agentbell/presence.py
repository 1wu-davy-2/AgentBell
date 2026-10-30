from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

from .config import AppConfig
from .policy import Presence

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:  # pragma: no branch - platform dependent
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    class _WtsInfoExLevel1(ctypes.Structure):
        _fields_ = [
            ("SessionId", wintypes.ULONG),
            ("SessionState", ctypes.c_int),
            ("SessionFlags", ctypes.c_int),
            ("WinStationName", wintypes.WCHAR * 33),
            ("UserName", wintypes.WCHAR * 21),
            ("DomainName", wintypes.WCHAR * 18),
            ("LogonTime", ctypes.c_longlong),
            ("ConnectTime", ctypes.c_longlong),
            ("DisconnectTime", ctypes.c_longlong),
            ("LastInputTime", ctypes.c_longlong),
            ("CurrentTime", ctypes.c_longlong),
        ]

    class _WtsInfoExLevel(ctypes.Union):
        _fields_ = [("Level1", _WtsInfoExLevel1)]

    class _WtsInfoEx(ctypes.Structure):
        _fields_ = [("Level", wintypes.DWORD), ("Data", _WtsInfoExLevel)]

    _wtsapi32.WTSQuerySessionInformationW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _wtsapi32.WTSQuerySessionInformationW.restype = wintypes.BOOL
    _wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]

    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.GetClassNameW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    _user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.MonitorFromWindow.restype = wintypes.HMONITOR
    _user32.GetMonitorInfoW.argtypes = [
        wintypes.HMONITOR,
        ctypes.POINTER(_MonitorInfo),
    ]
    _kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _user32.OpenInputDesktop.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    _user32.OpenInputDesktop.restype = wintypes.HANDLE
    _user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    _user32.CloseDesktop.restype = wintypes.BOOL
    _user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.SystemParametersInfoW.argtypes = [
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        wintypes.UINT,
    ]

_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_MONITOR_DEFAULTTONEAREST = 2
_DESKTOP_READOBJECTS = 0x0001
_UOI_NAME = 2
_SPI_GETSCREENSAVERRUNNING = 0x0072
_WTS_CURRENT_SESSION = 0xFFFFFFFF
_WTS_INFO_EX = 25
_WTS_SESSIONSTATE_LOCK = 0


def _session_flags() -> int | None:
    if not _IS_WINDOWS:
        return None
    buffer = ctypes.c_void_p()
    size = wintypes.DWORD(0)
    if not _wtsapi32.WTSQuerySessionInformationW(
        None,
        _WTS_CURRENT_SESSION,
        _WTS_INFO_EX,
        ctypes.byref(buffer),
        ctypes.byref(size),
    ):
        return None
    try:
        info = ctypes.cast(buffer, ctypes.POINTER(_WtsInfoEx)).contents
        if info.Level != 1:
            return None
        return int(info.Data.Level1.SessionFlags)
    finally:
        _wtsapi32.WTSFreeMemory(buffer)


def idle_seconds() -> float:
    if not _IS_WINDOWS:
        return 0.0
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0.0
    current = int(_kernel32.GetTickCount64()) & 0xFFFFFFFF
    elapsed = (current - int(info.dwTime)) & 0xFFFFFFFF
    return elapsed / 1000.0


def foreground_window_class() -> str:
    if not _IS_WINDOWS:
        return ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value


def foreground_process_name() -> str:
    if not _IS_WINDOWS:
        return ""
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return ""
    process_id = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    if not process_id.value:
        return ""
    handle = _kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, process_id.value
    )
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buffer))
        if _kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return os.path.basename(buffer.value).lower()
    finally:
        _kernel32.CloseHandle(handle)
    return ""


def foreground_is_fullscreen() -> bool:
    if not _IS_WINDOWS:
        return False
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return False
    if not _user32.IsWindowVisible(hwnd) or _user32.IsIconic(hwnd):
        return False
    if foreground_window_class() in _SHELL_CLASSES:
        return False

    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    monitor = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return False
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return False
    bounds = info.rcMonitor
    return (
        rect.left <= bounds.left
        and rect.top <= bounds.top
        and rect.right >= bounds.right
        and rect.bottom >= bounds.bottom
    )


def active_meeting_process(processes: tuple[str, ...]) -> str:
    if not processes:
        return ""
    foreground = foreground_process_name()
    if not foreground:
        return ""
    return foreground if foreground in processes else ""


def _screensaver_running() -> bool:
    if not _IS_WINDOWS:
        return False
    running = wintypes.BOOL(False)
    if not _user32.SystemParametersInfoW(
        _SPI_GETSCREENSAVERRUNNING, 0, ctypes.byref(running), 0
    ):
        return False
    return bool(running.value)


def _monitor_powered_off() -> bool:
    if not _IS_WINDOWS:
        return False
    # SM_CMONITORS reports 0 while the workstation is locked or displays sleep.
    return _user32.GetSystemMetrics(0x50) == 0


def _input_desktop_name() -> str:
    if not _IS_WINDOWS:
        return ""
    desktop = _user32.OpenInputDesktop(0, False, _DESKTOP_READOBJECTS)
    if not desktop:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(256)
        needed = wintypes.DWORD(0)
        if _user32.GetUserObjectInformationW(
            desktop,
            _UOI_NAME,
            buffer,
            ctypes.sizeof(buffer),
            ctypes.byref(needed),
        ):
            return buffer.value
    finally:
        _user32.CloseDesktop(desktop)
    return ""


def session_locked() -> bool:
    """Best-effort detection of lock screen, screensaver or monitor sleep."""
    if not _IS_WINDOWS:
        return False
    flags = _session_flags()
    if flags is not None and flags == _WTS_SESSIONSTATE_LOCK:
        return True
    if _screensaver_running() or _monitor_powered_off():
        return True
    name = _input_desktop_name()
    return bool(name) and name.lower() != "default"


class PresenceMonitor(QObject):
    changed = Signal(object)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fullscreen_enabled = config.suppress_fullscreen
        self._meeting_processes = tuple(
            name.lower() for name in config.meeting_processes if name
        )
        self._away_idle_seconds = config.away_idle_seconds
        self._hold_when_locked = config.hold_when_locked
        self._state = Presence()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._apply_interval(config.presence_poll_seconds)

    @property
    def state(self) -> Presence:
        return self._state

    def start(self) -> None:
        self._poll()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def apply_config(self, config: AppConfig) -> None:
        self._fullscreen_enabled = config.suppress_fullscreen
        self._meeting_processes = tuple(
            name.lower() for name in config.meeting_processes if name
        )
        self._away_idle_seconds = config.away_idle_seconds
        self._hold_when_locked = config.hold_when_locked
        self._apply_interval(config.presence_poll_seconds)
        self._poll()

    def _apply_interval(self, seconds: int) -> None:
        self._timer.setInterval(max(1, int(seconds)) * 1000)

    def _poll(self) -> None:
        idle = idle_seconds()
        state = Presence(
            away=self._away_idle_seconds > 0 and idle >= self._away_idle_seconds,
            fullscreen=self._fullscreen_enabled and foreground_is_fullscreen(),
            meeting_process=active_meeting_process(self._meeting_processes),
            idle_seconds=idle,
            locked=self._hold_when_locked and session_locked(),
        )
        if state != self._state:
            self._state = state
            self.changed.emit(state)
