from __future__ import annotations

import ctypes
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass

_IS_MACOS = sys.platform == "darwin"

_COREGRAPHICS_PATH = (
    "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
)
_COREFOUNDATION_PATH = (
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)
_APPLICATION_SERVICES_PATHS = (
    "/System/Library/Frameworks/ApplicationServices.framework/"
    "Frameworks/HIServices.framework/HIServices",
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices",
)
_CF_STRING_ENCODING_UTF8 = 0x08000100
_KCG_EVENT_SOURCE_STATE_COMBINED_SESSION = 0
_KCG_ANY_INPUT_EVENT_TYPE = 0xFFFFFFFF
_FOREGROUND_IDLE_LIMIT = 86_400.0

# Carbon modifiers and virtual key codes used for global hotkeys.
_CARBON_COMMAND = 0x0100
_CARBON_SHIFT = 0x0200
_CARBON_OPTION = 0x0800
_CARBON_CONTROL = 0x1000
_MAC_MODIFIERS = {
    "cmd": _CARBON_COMMAND,
    "command": _CARBON_COMMAND,
    "meta": _CARBON_COMMAND,
    "win": _CARBON_COMMAND,
    "ctrl": _CARBON_CONTROL,
    "control": _CARBON_CONTROL,
    "alt": _CARBON_OPTION,
    "option": _CARBON_OPTION,
    "opt": _CARBON_OPTION,
    "shift": _CARBON_SHIFT,
}
_MAC_KEYS = {
    "a": 0,
    "s": 1,
    "d": 2,
    "f": 3,
    "h": 4,
    "g": 5,
    "z": 6,
    "x": 7,
    "c": 8,
    "v": 9,
    "b": 11,
    "q": 12,
    "w": 13,
    "e": 14,
    "r": 15,
    "y": 16,
    "t": 17,
    "1": 18,
    "2": 19,
    "3": 20,
    "4": 21,
    "6": 22,
    "5": 23,
    "=": 24,
    "9": 25,
    "7": 26,
    "-": 27,
    "8": 28,
    "0": 29,
    "]": 30,
    "o": 31,
    "u": 32,
    "[": 33,
    "i": 34,
    "p": 35,
    "return": 36,
    "enter": 36,
    "l": 37,
    "j": 38,
    "'": 39,
    "k": 40,
    ";": 41,
    "\\": 42,
    ",": 43,
    "/": 44,
    "n": 45,
    "m": 46,
    ".": 47,
    "tab": 48,
    "space": 49,
    "`": 50,
    "delete": 51,
    "esc": 53,
    "escape": 53,
}
_MAC_FUNCTION_KEYS = {
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}
_MAC_NAMED_KEYS = {
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "deleteforward": 117,
    "up": 126,
    "down": 125,
    "left": 123,
    "right": 124,
    "help": 114,
}

# Longest fragments first so nested helper bundles resolve to the host app.
_APP_PATH_LABELS = (
    ("/visual studio code.app/", "VS Code"),
    ("/vscode.app/", "VS Code"),
    ("/qoder.app/", "Qoder"),
    ("/cursor.app/", "Cursor"),
    ("/windsurf.app/", "Windsurf"),
    ("/trae.app/", "Trae"),
    ("/iterm2.app/", "iTerm2"),
    ("/iterm.app/", "iTerm2"),
    ("/terminal.app/", "Terminal"),
    ("/warp.app/", "Warp"),
    ("/kitty.app/", "kitty"),
    ("/alacritty.app/", "Alacritty"),
    ("/wezterm.app/", "WezTerm"),
    ("/ghostty.app/", "Ghostty"),
    ("/tabby.app/", "Tabby"),
    ("/hyper.app/", "Hyper"),
    ("/claude.app/", "Claude"),
    ("/chatgpt.app/", "ChatGPT"),
)
_APP_NAME_LABELS = {
    "claude": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "opencode": "OpenCode",
    "grok": "Grok Build",
    "hermes": "Hermes",
    "minimax": "MiniMax Code",
    "pi": "Pi",
}
_TERMINAL_APP_NAMES = {
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
    "vs code",
    "vscode",
    "qoder",
    "cursor",
    "windsurf",
    "trae",
}


@dataclass(frozen=True, slots=True)
class MacWindow:
    pid: int
    app: str
    title: str


def parse_macos_hotkey(spec: str) -> tuple[int, int] | None:
    parts = [part.strip().lower() for part in (spec or "").split("+") if part.strip()]
    if len(parts) < 2:
        return None
    modifiers = 0
    key: int | None = None
    for part in parts:
        if part in _MAC_MODIFIERS:
            modifiers |= _MAC_MODIFIERS[part]
            continue
        if key is not None:
            return None
        if part in _MAC_KEYS:
            key = _MAC_KEYS[part]
        elif part in _MAC_FUNCTION_KEYS:
            key = _MAC_FUNCTION_KEYS[part]
        elif part in _MAC_NAMED_KEYS:
            key = _MAC_NAMED_KEYS[part]
        else:
            return None
    if key is None or modifiers == 0:
        return None
    return modifiers, key


def _execute(command: list[str], timeout: float = 4.0) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False, ""
    output = result.stdout or b""
    if isinstance(output, bytes):
        text = output.decode("utf-8", errors="replace")
    else:
        text = str(output)
    return result.returncode == 0, text


def _run(command: list[str], timeout: float = 4.0) -> str:
    ok, text = _execute(command, timeout)
    return text if ok else ""


_core_graphics_lib: ctypes.CDLL | None = None
_core_graphics_failed = False
_core_foundation_lib: ctypes.CDLL | None = None
_core_foundation_failed = False


def _core_graphics() -> ctypes.CDLL | None:
    global _core_graphics_lib, _core_graphics_failed
    if not _IS_MACOS:
        return None
    if _core_graphics_lib is not None or _core_graphics_failed:
        return _core_graphics_lib
    try:
        lib = ctypes.CDLL(_COREGRAPHICS_PATH)
        lib.CGEventSourceSecondsSinceLastEventType.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        lib.CGEventSourceSecondsSinceLastEventType.restype = ctypes.c_double
        lib.CGSessionCopyCurrentDictionary.argtypes = []
        lib.CGSessionCopyCurrentDictionary.restype = ctypes.c_void_p
    except (OSError, AttributeError):
        _core_graphics_failed = True
        return None
    _core_graphics_lib = lib
    return lib


def _core_foundation() -> ctypes.CDLL | None:
    global _core_foundation_lib, _core_foundation_failed
    if not _IS_MACOS:
        return None
    if _core_foundation_lib is not None or _core_foundation_failed:
        return _core_foundation_lib
    try:
        lib = ctypes.CDLL(_COREFOUNDATION_PATH)
        lib.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        lib.CFStringCreateWithCString.restype = ctypes.c_void_p
        lib.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.CFDictionaryGetValue.restype = ctypes.c_void_p
        lib.CFGetTypeID.argtypes = [ctypes.c_void_p]
        lib.CFGetTypeID.restype = ctypes.c_ulong
        lib.CFBooleanGetTypeID.argtypes = []
        lib.CFBooleanGetTypeID.restype = ctypes.c_ulong
        lib.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        lib.CFBooleanGetValue.restype = ctypes.c_bool
        lib.CFRelease.argtypes = [ctypes.c_void_p]
        lib.CFRelease.restype = None
    except (OSError, AttributeError):
        _core_foundation_failed = True
        return None
    _core_foundation_lib = lib
    return lib


def _session_dictionary_bool(key: str) -> bool | None:
    graphics = _core_graphics()
    foundation = _core_foundation()
    if graphics is None or foundation is None:
        return None
    dictionary = graphics.CGSessionCopyCurrentDictionary()
    if not dictionary:
        return None
    key_ref = foundation.CFStringCreateWithCString(
        None, key.encode("utf-8"), _CF_STRING_ENCODING_UTF8
    )
    if not key_ref:
        foundation.CFRelease(dictionary)
        return None
    try:
        value = foundation.CFDictionaryGetValue(dictionary, key_ref)
        if not value:
            return False
        if foundation.CFGetTypeID(value) != foundation.CFBooleanGetTypeID():
            return None
        return bool(foundation.CFBooleanGetValue(value))
    finally:
        foundation.CFRelease(key_ref)
        foundation.CFRelease(dictionary)


def _ioreg_screen_locked() -> bool:
    text = _run(["ioreg", "-n", "Root", "-d1", "-a"], timeout=2.0)
    if not text.strip():
        text = _run(["ioreg", "-n", "Root", "-d1"], timeout=2.0)
        match = re.search(
            r"CGSSessionScreenIsLocked\"?\s*=\s*(?:Yes|true|1)\b",
            text,
            re.IGNORECASE,
        )
        return bool(match)
    try:
        data = plistlib.loads(text.encode("utf-8", errors="replace"))
    except Exception:
        return False
    users = data.get("IOConsoleUsers") if isinstance(data, dict) else None
    if not isinstance(users, list):
        return False
    return any(
        isinstance(entry, dict) and entry.get("CGSSessionScreenIsLocked") is True
        for entry in users
    )


def idle_seconds() -> float:
    graphics = _core_graphics()
    if graphics is not None:
        try:
            value = float(
                graphics.CGEventSourceSecondsSinceLastEventType(
                    _KCG_EVENT_SOURCE_STATE_COMBINED_SESSION,
                    _KCG_ANY_INPUT_EVENT_TYPE,
                )
            )
            if value == value and value >= 0:
                return min(value, _FOREGROUND_IDLE_LIMIT)
        except Exception:
            pass
    text = _run(["ioreg", "-c", "IOHIDSystem"], timeout=2.0)
    match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', text)
    if match:
        return min(int(match.group(1)) / 1_000_000_000.0, _FOREGROUND_IDLE_LIMIT)
    return 0.0


def session_locked() -> bool:
    locked = _session_dictionary_bool("CGSSessionScreenIsLocked")
    if locked is not None:
        return locked
    return _ioreg_screen_locked()


def _parse_lsappinfo(text: str) -> dict[str, str]:
    info: dict[str, str] = {}
    for key in ("LSDisplayName", "name"):
        match = re.search(rf'"{key}"\s*=\s*"([^"]*)"', text)
        if match:
            info["name"] = match.group(1)
            break
    match = re.search(r'"pid"\s*=\s*(\d+)', text)
    if match:
        info["pid"] = match.group(1)
    match = re.search(r'"ASN"\s*=\s*"(ASN:[^"]+)"', text)
    if match:
        info["asn"] = match.group(1)
    return info


def _clean_app_name(name: str) -> str:
    text = " ".join((name or "").replace("\x00", " ").split())
    if text.lower().endswith(".app"):
        text = text[:-4]
    return text[:80]


def foreground_app() -> tuple[str, int]:
    """Return (display name, pid) for the frontmost application."""
    asn = _run(["lsappinfo", "front"], timeout=2.0).strip()
    if asn.startswith("ASN:"):
        info = _parse_lsappinfo(_run(["lsappinfo", "info", asn], timeout=2.0))
        if info.get("name"):
            return _clean_app_name(info["name"]), int(info.get("pid") or 0)
    text = _run(
        [
            "osascript",
            "-e",
            'tell application "System Events" to get {name, unix id} of '
            "first application process whose frontmost is true",
        ],
        timeout=3.0,
    )
    match = re.search(r'"?([^",]+?)"?\s*,\s*(\d+)', text.strip())
    if match:
        return _clean_app_name(match.group(1)), int(match.group(2))
    return "", 0


def foreground_process_name() -> str:
    name, _pid = foreground_app()
    return name.lower()


def foreground_fullscreen() -> bool:
    _name, pid = foreground_app()
    if pid <= 0:
        return False
    script = """
on run argv
    set targetPid to (item 1 of argv) as integer
    tell application "System Events"
        try
            set targetProcess to first application process whose unix id is targetPid
            if (count of windows of targetProcess) is 0 then return "false"
            return (value of attribute "AXFullScreen" of window 1 of targetProcess) as text
        on error
            return "false"
        end try
    end tell
end run
"""
    return _run(["osascript", "-e", script, str(pid)], timeout=3.0).strip().lower() == "true"


_WINDOW_LIST_SCRIPT = """
on run
    set output to ""
    tell application "System Events"
        set candidates to every application process whose background only is false
        repeat with p in candidates
            try
                set pname to name of p
                set ppid to unix id of p
                set wins to windows of p
                repeat with w in wins
                    try
                        set wtitle to my flatten(name of w)
                        if wtitle is not "" then
                            set output to output & ppid & tab & my flatten(pname) & tab & wtitle & linefeed
                        end if
                    end try
                end repeat
            end try
        end repeat
    end tell
    return output
end run

on flatten(value)
    if value is missing value then return ""
    set textValue to value as text
    set AppleScript's text item delimiters to {tab, linefeed, return}
    set parts to text items of textValue
    set AppleScript's text item delimiters to " "
    set flattened to parts as text
    set AppleScript's text item delimiters to ""
    return flattened
end flatten
"""


def _parse_window_list(text: str) -> list[MacWindow]:
    windows: list[MacWindow] = []
    own_pid = os.getpid()
    for line in text.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        raw_pid, app, title = parts
        try:
            pid = int(raw_pid.strip())
        except ValueError:
            continue
        app = " ".join(app.split())
        title = " ".join(title.split())
        if pid <= 0 or pid == own_pid or not app or not title:
            continue
        windows.append(MacWindow(pid=pid, app=app, title=title[:200]))
    return windows


def window_list() -> list[MacWindow]:
    return _parse_window_list(
        _run(["osascript", "-e", _WINDOW_LIST_SCRIPT], timeout=6.0)
    )


def _parse_process_table(text: str) -> dict[int, tuple[int, str]]:
    table: dict[int, tuple[int, str]] = {}
    for line in text.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
            parent = int(parts[1])
        except ValueError:
            continue
        table[pid] = (parent, parts[2].lower())
    return table


def process_table() -> dict[int, tuple[int, str]]:
    return _parse_process_table(_run(["ps", "-axo", "pid=,ppid=,comm="], timeout=4.0))


def process_ancestors(pid: int, table: dict[int, tuple[int, str]]) -> list[int]:
    chain: list[int] = []
    current = pid
    while current > 0 and current not in chain and len(chain) < 16:
        chain.append(current)
        current = table.get(current, (0, ""))[0]
    return chain


def app_label(comm: str) -> str:
    text = (comm or "").strip().lower().replace("\\", "/")
    if not text:
        return ""
    for needle, label in _APP_PATH_LABELS:
        if needle in text:
            return label
    name = text.rsplit("/", 1)[-1]
    return _APP_NAME_LABELS.get(name, "")


def is_terminal_app(name: str) -> bool:
    text = " ".join((name or "").replace(".app", "").split()).lower()
    return text in _TERMINAL_APP_NAMES


def _parse_lsof(text: str, local_port: int, remote_port: int | None) -> int | None:
    current = 0
    own_pid = os.getpid()
    for line in text.splitlines():
        if line.startswith("p"):
            try:
                current = int(line[1:])
            except ValueError:
                current = 0
            continue
        if not line.startswith("n") or current <= 0 or current == own_pid:
            continue
        local, _, remote = line[1:].partition("->")
        if local.rsplit(":", 1)[-1] != str(local_port):
            continue
        if remote_port is not None and remote.rsplit(":", 1)[-1] != str(remote_port):
            continue
        return current
    return None


def client_pid(local_port: int, remote_port: int | None = None) -> int | None:
    if not isinstance(local_port, int) or local_port <= 0:
        return None
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    text = _run(
        [lsof, "-nP", f"-iTCP:{local_port}", "-sTCP:ESTABLISHED", "-Fpn"],
        timeout=4.0,
    )
    return _parse_lsof(text, local_port, remote_port)


def accessibility_trusted() -> bool | None:
    for path in _APPLICATION_SERVICES_PATHS:
        try:
            lib = ctypes.CDLL(path)
            lib.AXIsProcessTrusted.argtypes = []
            lib.AXIsProcessTrusted.restype = ctypes.c_bool
            return bool(lib.AXIsProcessTrusted())
        except (OSError, AttributeError):
            continue
    return None


_ACTIVATE_SCRIPT = """
on run argv
    set targetPid to (item 1 of argv) as integer
    set targetTitle to item 2 of argv
    tell application "System Events"
        set targetProcess to first application process whose unix id is targetPid
        set frontmost of targetProcess to true
        if targetTitle is not "" then
            try
                set targetWindow to first window of targetProcess whose name is targetTitle
                perform action "AXRaise" of targetWindow
            end try
        end if
    end tell
    return "ok"
end run
"""


def _wait_for_front(pid: int, timeout: float = 1.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if foreground_app()[1] == pid:
            return True
        time.sleep(0.08)
    return False


def activate(pid: int, title: str = "", app_name: str = "") -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    ok, _text = _execute(
        ["osascript", "-e", _ACTIVATE_SCRIPT, str(pid), title or ""],
        timeout=4.0,
    )
    if ok and _wait_for_front(pid):
        return True
    if app_name:
        ok, _text = _execute(["open", "-a", app_name], timeout=4.0)
        if ok and _wait_for_front(pid):
            return True
    return False