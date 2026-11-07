from __future__ import annotations

import ctypes
import json
import os
import sys
from dataclasses import dataclass
from ctypes import wintypes

from . import macos_desktop

_IS_WINDOWS = os.name == "nt"
_IS_LINUX = sys.platform.startswith("linux")
_IS_MACOS = sys.platform == "darwin"

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
_AF_INET = 2
_TCP_TABLE_OWNER_PID_CONNECTIONS = 4
_ERROR_INSUFFICIENT_BUFFER = 122
_MAX_PROCESS_DEPTH = 16
_VK_MENU = 0x12
_KEYEVENTF_KEYUP = 0x0002

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

_APP_LABELS = {
    "qoder.exe": "Qoder",
    "cursor.exe": "Cursor",
    "windsurf.exe": "Windsurf",
    "trae.exe": "Trae",
    "code.exe": "VS Code",
    "code - insiders.exe": "VS Code",
    "claude.exe": "Claude Code",
    "codex.exe": "Codex",
    "gemini.exe": "Gemini CLI",
    "opencode.exe": "OpenCode",
    "openclaw.exe": "OpenClaw",
    "hermes.exe": "Hermes",
    "pi.exe": "Pi",
    "windowsterminal.exe": "Windows Terminal",
    "powershell.exe": "PowerShell",
    "pwsh.exe": "PowerShell",
    "cmd.exe": "命令提示符",
    "conhost.exe": "控制台",
    "openconsole.exe": "控制台",
    "mintty.exe": "Mintty",
    "bash.exe": "Bash",
    "git-bash.exe": "Git Bash",
    "wezterm-gui.exe": "WezTerm",
    "alacritty.exe": "Alacritty",
    "tabby.exe": "Tabby",
    "hyper.exe": "Hyper",
}
_GENERIC_LABELS = {
    "Windows Terminal",
    "PowerShell",
    "命令提示符",
    "控制台",
    "Mintty",
    "Bash",
    "Git Bash",
    "WezTerm",
    "Alacritty",
    "Tabby",
    "Hyper",
}

_LINUX_TERMINAL_EXES = {
    "gnome-terminal-server",
    "gnome-terminal",
    "kgx",
    "konsole",
    "xfce4-terminal",
    "mate-terminal",
    "tilix",
    "kitty",
    "alacritty",
    "wezterm-gui",
    "wezterm",
    "xterm",
    "urxvt",
    "st",
    "qoder",
    "cursor",
    "windsurf",
    "trae",
    "code",
    "claude",
    "codex",
    "gemini",
    "opencode",
}
_LINUX_TERMINAL_CLASSES = {
    "Gnome-terminal",
    "kgx",
    "konsole",
    "Xfce4-terminal",
    "Mate-terminal",
    "Tilix",
    "kitty",
    "Alacritty",
    "wezterm",
    "xterm",
    "URxvt",
    "st",
}
_LINUX_APP_LABELS = {
    "qoder": "Qoder",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "trae": "Trae",
    "code": "VS Code",
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "opencode": "OpenCode",
    "gnome-terminal-server": "GNOME Terminal",
    "gnome-terminal": "GNOME Terminal",
    "kgx": "GNOME Console",
    "konsole": "Konsole",
    "xfce4-terminal": "Xfce Terminal",
    "mate-terminal": "MATE Terminal",
    "tilix": "Tilix",
    "kitty": "kitty",
    "alacritty": "Alacritty",
    "wezterm-gui": "WezTerm",
    "xterm": "Xterm",
    "bash": "Bash",
    "zsh": "Zsh",
}
_LINUX_GENERIC_LABELS = {
    "GNOME Terminal",
    "GNOME Console",
    "Konsole",
    "Xfce Terminal",
    "MATE Terminal",
    "Tilix",
    "kitty",
    "Alacritty",
    "WezTerm",
    "Xterm",
    "Bash",
    "Zsh",
}

_MAC_TERMINAL_EXES = {
    "terminal",
    "iterm",
    "iterm2",
    "warp",
    "kitty",
    "alacritty",
    "wezterm",
    "ghostty",
    "hyper",
    "tabby",
    "visual studio code",
    "code",
    "code - insiders",
    "vscode",
    "qoder",
    "cursor",
    "windsurf",
    "trae",
}
_MAC_APP_LABELS = {
    "terminal": "Terminal",
    "iterm": "iTerm2",
    "iterm2": "iTerm2",
    "warp": "Warp",
    "kitty": "kitty",
    "alacritty": "Alacritty",
    "wezterm": "WezTerm",
    "ghostty": "Ghostty",
    "hyper": "Hyper",
    "tabby": "Tabby",
    "visual studio code": "VS Code",
    "code": "VS Code",
    "code - insiders": "VS Code",
    "vscode": "VS Code",
    "qoder": "Qoder",
    "cursor": "Cursor",
    "windsurf": "Windsurf",
    "trae": "Trae",
}
_MAC_GENERIC_LABELS = {
    "Terminal",
    "iTerm2",
    "Warp",
    "kitty",
    "Alacritty",
    "WezTerm",
    "Ghostty",
    "Hyper",
    "Tabby",
}

if _IS_WINDOWS:  # pragma: no branch - platform dependent
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _iphlpapi = ctypes.WinDLL("iphlpapi", use_last_error=True)

    class _MibTcpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

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
    _user32.SetFocus.argtypes = [wintypes.HWND]
    _user32.SetFocus.restype = wintypes.HWND
    _user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    _user32.SwitchToThisWindow.restype = None
    _user32.keybd_event.argtypes = [
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        ctypes.c_size_t,
    ]
    _user32.keybd_event.restype = None
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

    _iphlpapi.GetExtendedTcpTable.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    _iphlpapi.GetExtendedTcpTable.restype = wintypes.DWORD
else:  # pragma: no cover - platform dependent
    _user32 = None
    _kernel32 = None
    _iphlpapi = None


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
        or window.exe in _LINUX_TERMINAL_EXES
        or window.exe in _MAC_TERMINAL_EXES
        or window.class_name in _TERMINAL_CLASSES
        or window.class_name in _LINUX_TERMINAL_CLASSES
        or "console" in window.class_name.lower()
    )


def _linux_windows(table: dict[int, tuple[int, str]]) -> list[_WindowInfo]:
    try:
        from . import linux_desktop
    except Exception:
        return []
    try:
        raw_windows = linux_desktop.x11().windows()
    except Exception:
        return []
    return [
        _WindowInfo(
            handle=window.handle,
            pid=window.pid,
            title=window.title,
            class_name=window.class_name,
            exe=table.get(window.pid, (0, ""))[1],
        )
        for window in raw_windows
        if window.pid > 0
    ]


def _mac_windows(table: dict[int, tuple[int, str]]) -> list[_WindowInfo]:
    try:
        raw_windows = macos_desktop.window_list()
    except Exception:
        return []
    own_pid = os.getpid()
    return [
        _WindowInfo(
            handle=window.pid,
            pid=window.pid,
            title=window.title,
            class_name=window.app,
            exe=window.app.lower(),
        )
        for window in raw_windows
        if window.pid > 0 and window.pid != own_pid
    ]


def _mac_window_label(window: _WindowInfo) -> str:
    return _MAC_APP_LABELS.get(window.exe, "")


def _mac_terminal_ancestor(
    pid: int, table: dict[int, tuple[int, str]]
) -> tuple[int, str] | None:
    for candidate in macos_desktop.process_ancestors(pid, table):
        label = macos_desktop.app_label(table.get(candidate, (0, ""))[1])
        if label and macos_desktop.is_terminal_app(label):
            return candidate, label
    return None


def _focus_choices(
    windows: list[_WindowInfo], query: str, limit: int
) -> list[FocusChoice]:
    needle = query.casefold()
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


def find_focus_choices(query: str, limit: int = 8) -> list[FocusChoice]:
    query = " ".join((query or "").split())
    if not query:
        return []
    if _IS_MACOS:
        try:
            table = macos_desktop.process_table()
            return _focus_choices(_mac_windows(table), query, limit)
        except Exception:
            return []
    if _IS_LINUX:
        try:
            from . import linux_desktop

            if not linux_desktop.x11_available():
                return []
            table = linux_desktop.process_table()
            return _focus_choices(_linux_windows(table), query, limit)
        except Exception:
            return []
    if not _IS_WINDOWS:
        return []
    return _focus_choices(_collect_windows(_process_table()), query, limit)


def _resolve_window(target: FocusTarget) -> _WindowInfo | None:
    anchor: tuple[int, str] | None = None
    if _IS_MACOS:
        try:
            table = macos_desktop.process_table()
        except Exception:
            table = {}
        if target.pid is not None:
            anchor = _mac_terminal_ancestor(target.pid, table)
            if anchor is not None and not target.window_title:
                return _WindowInfo(
                    handle=anchor[0],
                    pid=anchor[0],
                    title="",
                    class_name=anchor[1],
                    exe=anchor[1].lower(),
                )
        windows = _mac_windows(table)
    elif _IS_LINUX:
        try:
            from . import linux_desktop

            if not linux_desktop.x11_available():
                return None
            table = linux_desktop.process_table()
            windows = _linux_windows(table)
        except Exception:
            return None
    else:
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

    if _IS_MACOS and anchor is not None:
        anchor_pid, anchor_label = anchor
        label_windows = [
            window for window in windows if _mac_window_label(window) == anchor_label
        ]
        if target.window_title:
            needle = target.window_title.casefold()
            titled = [
                window
                for window in label_windows
                if needle in window.title.casefold()
            ]
            if titled:
                return titled[0]
        if label_windows:
            return label_windows[0]
        if not windows:
            return _WindowInfo(
                handle=anchor_pid,
                pid=anchor_pid,
                title="",
                class_name=anchor_label,
                exe=anchor_label.lower(),
            )
    return None


def snapshot_focus(pid: int) -> FocusChoice | None:
    """Resolve the host window now so it survives the agent process exiting."""
    if (
        not (_IS_WINDOWS or _IS_LINUX or _IS_MACOS)
        or not isinstance(pid, int)
        or pid <= 0
    ):
        return None
    window = _resolve_window(
        FocusTarget(pid=pid, window_title="", working_dir="")
    )
    if window is None:
        return None
    request = FocusRequest(pid=window.pid, window_title=window.title)
    return FocusChoice(
        pid=window.pid,
        title=window.title,
        executable=window.exe,
        value=request.to_value(),
    )


def _decode_net_port(raw: int) -> int:
    # dwLocalPort/dwRemotePort hold the port in network byte order.
    return ((raw & 0xFF) << 8) | ((raw >> 8) & 0xFF)


def _select_owner_pid(
    entries: list[tuple[int, int, int]],
    local_port: int,
    remote_port: int | None,
) -> int | None:
    for entry_local, entry_remote, pid in entries:
        if entry_local != local_port:
            continue
        if remote_port is not None and entry_remote != remote_port:
            continue
        if pid > 0:
            return pid
    return None


def client_pid(local_port: int, remote_port: int | None = None) -> int | None:
    """Resolve the process that owns a local TCP client socket.

    Notifications that omit ``origin`` still arrive on a socket owned by the
    sender, so this is used as a best-effort fallback for the focus action.
    """
    if _IS_MACOS:
        if not isinstance(local_port, int) or local_port <= 0:
            return None
        try:
            pid = macos_desktop.client_pid(local_port, remote_port)
        except Exception:
            return None
        return pid if pid and pid != os.getpid() else None
    if _IS_LINUX:
        if not isinstance(local_port, int) or local_port <= 0:
            return None
        try:
            from . import linux_desktop

            pid = linux_desktop.client_pid_for_port(local_port, remote_port)
        except Exception:
            return None
        return pid if pid and pid != os.getpid() else None
    if not _IS_WINDOWS or not isinstance(local_port, int) or local_port <= 0:
        return None
    size = wintypes.DWORD(0)
    result = _iphlpapi.GetExtendedTcpTable(
        None,
        ctypes.byref(size),
        False,
        _AF_INET,
        _TCP_TABLE_OWNER_PID_CONNECTIONS,
        0,
    )
    if result != _ERROR_INSUFFICIENT_BUFFER or size.value == 0:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    result = _iphlpapi.GetExtendedTcpTable(
        buffer,
        ctypes.byref(size),
        False,
        _AF_INET,
        _TCP_TABLE_OWNER_PID_CONNECTIONS,
        0,
    )
    if result != 0:
        return None
    count = min(
        int(ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value),
        65536,
    )
    rows = ctypes.cast(
        ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD),
        ctypes.POINTER(_MibTcpRowOwnerPid),
    )
    entries = [
        (
            _decode_net_port(int(rows[index].dwLocalPort)),
            _decode_net_port(int(rows[index].dwRemotePort)),
            int(rows[index].dwOwningPid),
        )
        for index in range(count)
    ]
    pid = _select_owner_pid(entries, local_port, remote_port)
    if pid is None or pid == 4 or pid == os.getpid():
        return None
    return pid


def _linux_sender_label(pid: int) -> str:
    try:
        from . import linux_desktop

        table = linux_desktop.process_table()
    except Exception:
        return ""
    fallback = ""
    for candidate in linux_desktop.process_ancestors(pid, table):
        name = table.get(candidate, (0, ""))[1].rsplit(".", 1)[0]
        if not name:
            continue
        label = _LINUX_APP_LABELS.get(name, "")
        if label and label not in _LINUX_GENERIC_LABELS:
            return label
        fallback = fallback or label or name
    return fallback[:32]


def _mac_sender_label(pid: int) -> str:
    try:
        table = macos_desktop.process_table()
    except Exception:
        return ""
    fallback = ""
    for candidate in macos_desktop.process_ancestors(pid, table):
        comm = table.get(candidate, (0, ""))[1]
        label = macos_desktop.app_label(comm)
        if label and label not in _MAC_GENERIC_LABELS:
            return label
        fallback = fallback or label
    return fallback[:32]


def sender_label(pid: int) -> str:
    """Best-effort agent/app name for the process that sent a notification."""
    if _IS_MACOS:
        if not isinstance(pid, int) or pid <= 0:
            return ""
        return _mac_sender_label(pid)
    if _IS_LINUX:
        if not isinstance(pid, int) or pid <= 0:
            return ""
        return _linux_sender_label(pid)
    if not _IS_WINDOWS or not isinstance(pid, int) or pid <= 0:
        return ""
    table = _process_table()
    current = pid
    fallback = ""
    for _ in range(_MAX_PROCESS_DEPTH):
        parent, exe = table.get(current, (0, ""))
        if not exe:
            break
        label = _APP_LABELS.get(exe, "")
        if label and label not in _GENERIC_LABELS:
            return label
        fallback = fallback or label
        if parent <= 0 or parent == current:
            break
        current = parent
    window = _resolve_window(FocusTarget(pid=pid, window_title="", working_dir=""))
    if window is not None:
        label = _APP_LABELS.get(window.exe, "")
        if label:
            return label
        stem = window.exe.rsplit(".", 1)[0]
        if stem:
            return stem[:32]
    return fallback


def _foreground_is(handle: int) -> bool:
    return _user32.GetForegroundWindow() == handle


def _attach_and_focus(handle: int) -> bool:
    current_thread = _kernel32.GetCurrentThreadId()
    foreground = _user32.GetForegroundWindow()
    foreground_thread = (
        _user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    )
    target_thread = _user32.GetWindowThreadProcessId(handle, None)
    attached: list[int] = []
    for thread in {foreground_thread, target_thread}:
        if thread and thread != current_thread:
            if _user32.AttachThreadInput(thread, current_thread, True):
                attached.append(thread)
    try:
        _user32.BringWindowToTop(handle)
        _user32.SetForegroundWindow(handle)
        _user32.SetFocus(handle)
    finally:
        for thread in attached:
            _user32.AttachThreadInput(thread, current_thread, False)
    return _foreground_is(handle)


def _alt_tap_focus(handle: int) -> bool:
    # Windows refuses SetForegroundWindow unless the caller recently received
    # input. A synthetic Alt tap satisfies that check after an explicit click,
    # so this runs only after the non-invasive attempts fail.
    _user32.keybd_event(_VK_MENU, 0, 0, 0)
    try:
        _user32.SetForegroundWindow(handle)
    finally:
        _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
    return _foreground_is(handle)


def _activate_window(handle: int) -> tuple[bool, bool]:
    if _user32.IsIconic(handle):
        _user32.ShowWindow(handle, _SW_RESTORE)
    else:
        _user32.ShowWindow(handle, _SW_SHOW)
    _user32.BringWindowToTop(handle)
    _user32.SetForegroundWindow(handle)
    if _foreground_is(handle):
        return True, True

    if _attach_and_focus(handle):
        return True, True

    _user32.SwitchToThisWindow(handle, True)
    if _foreground_is(handle):
        return True, True

    if _alt_tap_focus(handle):
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


def _focus_terminal_linux(target: FocusTarget) -> FocusResult:
    try:
        from . import linux_desktop
    except Exception:
        return FocusResult(False, "Linux 桌面组件不可用", target.working_dir)
    if not linux_desktop.x11_available():
        if linux_desktop.is_wayland():
            return FocusResult(
                False,
                "Wayland 不允许应用主动切换窗口焦点；请从任务栏切换到终端",
                target.working_dir,
            )
        return FocusResult(
            False, "回到终端需要 X11 会话", target.working_dir
        )
    window = _resolve_window(target)
    if window is None:
        return FocusResult(False, "未找到对应的终端窗口，可能已经关闭", target.working_dir)
    if linux_desktop.x11().activate(window.handle):
        return FocusResult(True, window.title, target.working_dir)
    return FocusResult(False, "终端窗口无法切到前台", target.working_dir)


def _focus_terminal_macos(target: FocusTarget) -> FocusResult:
    window = _resolve_window(target)
    if window is None:
        return FocusResult(False, "未找到对应的终端窗口，可能已经关闭", target.working_dir)
    label = _mac_window_label(window) or window.class_name or window.exe
    if macos_desktop.activate(window.pid, window.title, label):
        return FocusResult(True, window.title or label, target.working_dir)
    message = "终端窗口无法切到前台"
    if macos_desktop.accessibility_trusted() is False:
        message = (
            "回到终端需要辅助功能权限，请在「系统设置 → 隐私与安全性 → "
            "辅助功能」中允许 AgentBell"
        )
    return FocusResult(False, message, target.working_dir)


def focus_terminal(raw: str) -> FocusResult:
    target = parse_focus_value(raw)
    if target is None:
        return FocusResult(False, "回到终端的参数无效")
    if _IS_MACOS:
        return _focus_terminal_macos(target)
    if _IS_LINUX:
        return _focus_terminal_linux(target)
    if not _IS_WINDOWS:
        return FocusResult(False, "当前系统不支持回到终端", target.working_dir)

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
