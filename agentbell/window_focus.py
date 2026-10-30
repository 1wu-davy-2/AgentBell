from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from ctypes import wintypes

_IS_WINDOWS = os.name == "nt"

_SW_SHOW = 5
_SW_RESTORE = 9
_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_TH32CS_SNAPPROCESS = 0x00000002
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_HWND_TOP = 0

_TERMINAL_EXES = {
    "windowsterminal.exe",
    "openconsole.exe",
    "conhost.exe",
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "mintty.exe",
    "wezterm-gui.exe",
    "alacritty.exe",
    "tabby.exe",
    "hyper.exe",
    "code.exe",
    "code - insiders.exe",
    "qoder.exe",
    "cursor.exe",
    "windsurf.exe",
    "trae.exe",
}
_TERMINAL_CLASSES = {
    "ConsoleWindowClass",
    "CASCADIA_HOSTING_WINDOW_CLASS",
    "mintty",
    "PuTTY",
}

if _IS_WINDOWS:  # pragma: no branch - platform dependent
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _ProcessEntry32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    _EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ProcessEntry32W),
    ]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    _user32.EnumWindows.argtypes = [_EnumWindowsProc, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    _user32.AttachThreadInput.restype = wintypes.BOOL


@dataclass(frozen=True, slots=True)
class FocusTarget:
    pid: int | None
    window_title: str
    working_dir: str


@dataclass(frozen=True, slots=True)
class FocusResult:
    ok: bool
    message: str
    working_dir: str = ""
    raised: bool = False


@dataclass(frozen=True, slots=True)
class FocusRequest:
    pid: int | None
    window_title: str = ""
    working_dir: str = ""

    def to_value(self) -> str:
        return json.dumps(
            {
                "pid": self.pid,
                "window_title": self.window_title,
                "working_dir": self.working_dir,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class FocusChoice:
    pid: int
    title: str
    executable: str
    value: str


@dataclass(frozen=True, slots=True)
class _WindowInfo:
    handle: int
    pid: int
    title: str
    class_name: str
    exe: str


def parse_focus_value(raw: str) -> FocusTarget | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    pid = data.get("pid")
    if (
        isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or pid > 0xFFFFFFFF
    ):
        pid = None

    def _text(key: str, limit: int) -> str:
        value = data.get(key)
        if not isinstance(value, str):
            return ""
        return " ".join(value.replace("\x00", " ").split())[:limit]

    title = _text("window_title", 200)
    working_dir = _text("working_dir", 1024)
    if pid is None and not title:
        return None
    return FocusTarget(pid=pid, window_title=title, working_dir=working_dir)


def _window_title(handle: int) -> str:
    length = _user32.GetWindowTextLengthW(handle)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(handle, buffer, length + 1)
    return buffer.value.strip()


def _class_name(handle: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(handle, buffer, 256)
    return buffer.value


def _process_table() -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return table
    try:
        entry = _ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(_ProcessEntry32W)
        if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return table
        while True:
            table[int(entry.th32ProcessID)] = (
                int(entry.th32ParentProcessID),
                entry.szExeFile.lower(),
            )
            if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        _kernel32.CloseHandle(snapshot)
    return table


def _collect_windows(table: dict[int, tuple[int, str]]) -> list[_WindowInfo]:
    windows: list[_WindowInfo] = []
    own_pid = os.getpid()

    @_EnumWindowsProc
    def _callback(handle, _lparam):  # pragma: no cover - Win32 callback
        try:
            if not _user32.IsWindowVisible(handle):
                return True
            title = _window_title(handle)
            if not title:
                return True
            pid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
            process_id = int(pid.value)
            if process_id == own_pid:
                return True
            if _user32.GetWindowLongW(handle, _GWL_EXSTYLE) & _WS_EX_TOOLWINDOW:
                return True
            windows.append(
                _WindowInfo(
                    handle=int(handle),
                    pid=process_id,
                    title=title,
                    class_name=_class_name(handle),
                    exe=table.get(process_id, (0, ""))[1],
                )
            )
        except Exception:
            pass
        return True

    _user32.EnumWindows(_callback, 0)
    return windows


def _candidate_ranks(pid: int, table: dict[int, tuple[int, str]]) -> dict[int, float]:
    ranks: dict[int, float] = {}
    current = pid
    distance = 0.0
    while current and current not in ranks and len(ranks) < 16:
        ranks[current] = distance
        parent, _exe = table.get(current, (0, ""))
        current = parent
        distance += 1.0
    # conhost/OpenConsole 的窗口属于终端进程的子进程，不在父链上
    for child_pid, (parent_pid, exe) in table.items():
        if exe in {"conhost.exe", "openconsole.exe"} and parent_pid in ranks:
            ranks.setdefault(child_pid, ranks[parent_pid] + 0.5)
    return ranks


def _terminal_like(window: _WindowInfo) -> bool:
    return (
        window.exe in _TERMINAL_EXES
        or window.class_name in _TERMINAL_CLASSES
        or "console" in window.class_name.lower()
    )


def find_focus_choices(query: str, limit: int = 8) -> list[FocusChoice]:
    query = " ".join((query or "").split())
    if not query or not _IS_WINDOWS:
        return []
    needle = query.casefold()
    windows = _collect_windows(_process_table())
    matches = {
        (window.pid, window.title): window
        for window in windows
        if _terminal_like(window) and needle in window.title.casefold()
    }
    ordered = sorted(
        matches.values(),
        key=lambda window: (
            window.title.casefold() != needle,
            len(window.title),
            window.title.casefold(),
        ),
    )
    choices: list[FocusChoice] = []
    for window in ordered[:limit]:
        request = FocusRequest(
            pid=window.pid, window_title=window.title, working_dir=""
        )
        choices.append(
            FocusChoice(
                pid=window.pid,
                title=window.title,
                executable=window.exe,
                value=request.to_value(),
            )
        )
    return choices


def _resolve_window(target: FocusTarget) -> _WindowInfo | None:
    table = _process_table()
    windows = _collect_windows(table)
    ranked: list[tuple[float, _WindowInfo]] = []
    if target.pid is not None:
        ranks = _candidate_ranks(target.pid, table)
        ranked = [
            (ranks[window.pid], window)
            for window in windows
            if window.pid in ranks
        ]

    if target.window_title:
        needle = target.window_title.casefold()
        exact = [item for item in ranked if item[1].title.casefold() == needle]
        if exact:
            return min(exact, key=lambda item: item[0])[1]
        partial = [item for item in ranked if needle in item[1].title.casefold()]
        if partial:
            return min(partial, key=lambda item: item[0])[1]

    if ranked:
        return min(ranked, key=lambda item: item[0])[1]

    if target.window_title:
        needle = target.window_title.casefold()
        matches = [
            window
            for window in windows
            if _terminal_like(window) and needle in window.title.casefold()
        ]
        exact = [window for window in matches if window.title.casefold() == needle]
        if exact:
            return exact[0]
        if len(matches) == 1:
            return matches[0]
    return None


def _activate_window(handle: int) -> tuple[bool, bool]:
    if _user32.IsIconic(handle):
        _user32.ShowWindow(handle, _SW_RESTORE)
    else:
        _user32.ShowWindow(handle, _SW_SHOW)
    _user32.BringWindowToTop(handle)
    _user32.SetForegroundWindow(handle)
    if _user32.GetForegroundWindow() == handle:
        return True, True

    foreground = _user32.GetForegroundWindow()
    if foreground:
        foreground_thread = _user32.GetWindowThreadProcessId(foreground, None)
        current_thread = _kernel32.GetCurrentThreadId()
        if foreground_thread and current_thread != foreground_thread:
            _user32.AttachThreadInput(foreground_thread, current_thread, True)
            try:
                if _user32.IsIconic(handle):
                    _user32.ShowWindow(handle, _SW_RESTORE)
                _user32.BringWindowToTop(handle)
                _user32.SetForegroundWindow(handle)
            finally:
                _user32.AttachThreadInput(foreground_thread, current_thread, False)
    if _user32.GetForegroundWindow() == handle:
        return True, True

    raised = bool(
        _user32.SetWindowPos(
            handle,
            _HWND_TOP,
            0,
            0,
            0,
            0,
            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
        )
    )
    return False, raised


def focus_terminal(raw: str) -> FocusResult:
    target = parse_focus_value(raw)
    if target is None:
        return FocusResult(False, "回到终端的参数无效")
    if not _IS_WINDOWS:
        return FocusResult(False, "回到终端仅支持 Windows", target.working_dir)

    window = _resolve_window(target)
    if window is None:
        return FocusResult(False, "未找到对应的终端窗口，可能已经关闭", target.working_dir)
    focused, raised = _activate_window(window.handle)
    if focused:
        return FocusResult(True, window.title, target.working_dir)
    if raised:
        return FocusResult(
            False,
            "终端窗口已置前，但系统未授予键盘焦点",
            target.working_dir,
            raised=True,
        )
    return FocusResult(False, "终端窗口无法切到前台", target.working_dir)
