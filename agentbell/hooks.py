from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .paths import app_dir as default_app_dir

HELPER_NAME = "agentbell-hook.ps1"
HOOK_MARKER = "agentbell-hook"
BACKUP_SUFFIX = ".agentbell-backup-"
LOCK_SUFFIX = ".agentbell.lock"
LOCK_TIMEOUT_SECONDS = 2.0
LOCK_STALE_SECONDS = 30.0

_CODEX_NOTIFY = re.compile(r"(?m)^[ \t]*notify[ \t]*=")
_CODEX_BLOCK = re.compile(
    r"(?m)^# agentbell-hook[^\r\n]*\r?\nnotify[ \t]*=[^\r\n]*(?:\r?\n){0,2}"
)
_CODEX_UNRESOLVED = (
    "检测到 AgentBell 标记，但无法定位 Codex notify 配置；"
    "请手动检查 config.toml"
)
_FIRST_TABLE = re.compile(r"(?m)^[ \t]*\[")
_TRAILING_NEWLINE = re.compile(r"(?:\r?\n)+\Z")


class HookError(RuntimeError):
    """Raised when a hook configuration cannot be planned or written."""


@dataclass(frozen=True, slots=True)
class HookAgent:
    id: str
    name: str
    support: str
    kind: str
    config_parts: tuple[str, ...]
    events: tuple[str, ...]
    note: str


HOOK_AGENTS: tuple[HookAgent, ...] = (
    HookAgent(
        "claude",
        "Claude Code",
        "full",
        "settings-json",
        (".claude", "settings.json"),
        ("UserPromptSubmit", "Notification", "Stop"),
        "等待确认、等待回答与每轮结束",
    ),
    HookAgent(
        "gemini",
        "Gemini CLI",
        "full",
        "settings-json",
        (".gemini", "settings.json"),
        ("BeforeAgent", "Notification", "AfterAgent"),
        "等待确认、等待回答与每轮结束",
    ),
    HookAgent(
        "grok",
        "Grok",
        "full",
        "grok-json",
        (".grok", "hooks", "agentbell.json"),
        ("UserPromptSubmit", "Notification", "Stop", "StopFailure", "StopCancelled"),
        "等待确认、等待回答与每轮结束",
    ),
    HookAgent(
        "codex",
        "Codex",
        "partial",
        "codex-toml",
        (".codex", "config.toml"),
        ("notify",),
        "仅支持每轮结束提醒，无法感知等待确认",
    ),
)

HOOK_AGENT_MAP = {spec.id: spec for spec in HOOK_AGENTS}


@dataclass(frozen=True, slots=True)
class HookStatus:
    agent: HookAgent
    config_path: Path
    detected: bool
    installed: bool
    problem: str = ""

    @property
    def summary(self) -> str:
        if self.problem:
            return self.problem
        if self.installed:
            return "已接入"
        if self.detected:
            return "未接入"
        return "未检测到 CLI 配置目录"


@dataclass(frozen=True, slots=True)
class HookPlan:
    agent: HookAgent
    action: str
    config_path: Path
    backup_path: Path | None
    preview: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HookResult:
    agent_id: str
    config_path: Path
    backup_path: Path | None
    changed: bool
    message: str


def helper_source() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        candidate = base / "assets" / "hooks" / HELPER_NAME
        if candidate.is_file():
            return candidate
    return Path(__file__).resolve().parent.parent / "assets" / "hooks" / HELPER_NAME


def helper_target(root: Path | None = None) -> Path:
    return Path(root or default_app_dir()) / "hooks" / HELPER_NAME


def hook_config_path(spec: HookAgent, home: Path | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base.joinpath(*spec.config_parts)


def _read_text(path: Path) -> tuple[str, bool]:
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        return raw.decode("utf-8-sig"), bom
    except UnicodeDecodeError as exc:
        raise HookError(f"{path} 不是 UTF-8 文本，未做修改") from exc


def _write_text(path: Path, text: str, *, bom: bool = False) -> None:
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    tmp = path.with_name(f"{path.name}.agentbell-tmp-{os.getpid()}")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


@contextmanager
def _config_lock(path: Path) -> Iterator[None]:
    lock = path.with_name(path.name + LOCK_SUFFIX)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle: int | None = None
    while handle is None:
        try:
            handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise HookError("配置正被其他操作占用，请稍后重试") from exc
            time.sleep(0.05)
        except OSError as exc:
            raise HookError(f"无法创建配置锁：{exc}") from exc
    try:
        yield
    finally:
        if handle is not None:
            os.close(handle)
        try:
            lock.unlink()
        except OSError:
            pass


def _backup_path(path: Path) -> Path | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return path.with_name(f"{path.name}{BACKUP_SUFFIX}{stamp}")


def _backup(path: Path) -> Path | None:
    target = _backup_path(path)
    if target is None:
        return None
    shutil.copy2(path, target)
    return target


def _load_json(path: Path) -> tuple[dict, bool]:
    if not path.exists():
        return {}, False
    text, bom = _read_text(path)
    if not text.strip():
        return {}, bom
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HookError(
            f"{path} 不是有效 JSON（第 {exc.lineno} 行第 {exc.colno} 列），未做修改"
        ) from exc
    if not isinstance(data, dict):
        raise HookError(f"{path} 顶层不是 JSON 对象，未做修改")
    return data, bom


def _hook_args(spec: HookAgent, root: Path) -> list[str]:
    if os.name != "nt":
        if getattr(sys, "frozen", False):
            return [
                str(Path(sys.executable).resolve()),
                "--hook",
                "--agent",
                spec.id,
            ]
        script = Path(root) / "run.py"
        if not script.is_file():
            script = default_app_dir() / "run.py"
        return [
            str(Path(sys.executable).resolve()),
            str(script),
            "--hook",
            "--agent",
            spec.id,
        ]
    return [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-WindowStyle",
        "Hidden",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(helper_target(root)),
        "-Agent",
        spec.id,
    ]


def _command(spec: HookAgent, root: Path) -> str:
    args = _hook_args(spec, root)
    if os.name != "nt":
        return shlex.join(args)
    return subprocess.list2cmdline(args)


def _is_agentbell_handler(handler: object) -> bool:
    if not isinstance(handler, dict):
        return False
    command = handler.get("command")
    if not isinstance(command, str):
        return False
    folded = command.casefold()
    if HELPER_NAME.casefold() in folded:
        return True
    return (
        "--hook" in folded
        and "--agent" in folded
        and ("agentbell" in folded or "run.py" in folded)
    )


def _handler_count(data: dict) -> int:
    count = 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return count
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if isinstance(handlers, list):
                count += sum(1 for item in handlers if isinstance(item, dict))
    return count


def _add_json_hooks(data: dict, spec: HookAgent, command: str) -> dict:
    result = json.loads(json.dumps(data))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise HookError("现有的 hooks 字段不是对象，未做修改")
    for event in spec.events:
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise HookError(f"hooks.{event} 不是数组，未做修改")
        already = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if isinstance(handlers, list) and any(
                _is_agentbell_handler(item) for item in handlers
            ):
                already = True
                break
        if already:
            continue
        groups.append(
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "timeout": 10,
                    }
                ]
            }
        )
    return result


def _remove_json_hooks(data: dict) -> dict:
    result = json.loads(json.dumps(data))
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        return result
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks")
            if not isinstance(handlers, list):
                kept_groups.append(group)
                continue
            kept_handlers = [
                item for item in handlers if not _is_agentbell_handler(item)
            ]
            if len(kept_handlers) == len(handlers):
                kept_groups.append(group)
            elif kept_handlers:
                replacement = dict(group)
                replacement["hooks"] = kept_handlers
                kept_groups.append(replacement)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if not hooks:
        result.pop("hooks", None)
    return result


def _count_agentbell_handlers(data: dict) -> int:
    count = 0
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return count
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            handlers = group.get("hooks")
            if isinstance(handlers, list):
                count += sum(
                    1 for item in handlers if _is_agentbell_handler(item)
                )
    return count


def _codex_block(spec: HookAgent, root: Path) -> str:
    args = _hook_args(spec, root)
    return (
        "# agentbell-hook (managed by AgentBell; 可在运行环境页撤销)\n"
        f"notify = {json.dumps(args, ensure_ascii=False)}\n"
    )


def _insert_codex_block(text: str, block: str) -> str:
    match = _FIRST_TABLE.search(text)
    if match is None:
        body = text.rstrip("\r\n")
        prefix = body + "\n\n" if body else ""
        return prefix + block
    head = text[: match.start()].rstrip("\r\n")
    tail = text[match.start() :]
    prefix = head + "\n\n" if head else ""
    return prefix + block + "\n" + tail


def _remove_codex_block(text: str) -> tuple[str, bool]:
    updated, count = _CODEX_BLOCK.subn("", text, count=1)
    if not count:
        return text, False
    updated = _TRAILING_NEWLINE.sub("\n", updated)
    return updated, True


def _detection_root(spec: HookAgent, config_path: Path) -> Path:
    if spec.kind == "grok-json":
        return config_path.parent.parent
    return config_path.parent


def _status_for(spec: HookAgent, config_path: Path) -> HookStatus:
    detected = _detection_root(spec, config_path).is_dir()
    if spec.kind == "codex-toml":
        if not config_path.is_file():
            return HookStatus(spec, config_path, detected, False)
        try:
            text, _ = _read_text(config_path)
        except (HookError, OSError) as exc:
            return HookStatus(spec, config_path, detected, False, str(exc))
        marker = HOOK_MARKER in text
        has_block = bool(_CODEX_BLOCK.search(text))
        installed = marker and has_block
        problem = ""
        if marker and not has_block:
            problem = _CODEX_UNRESOLVED
        elif not installed and _CODEX_NOTIFY.search(text):
            problem = "已有 notify 配置，不会覆盖"
        return HookStatus(spec, config_path, detected, installed, problem)
    if not config_path.is_file():
        return HookStatus(spec, config_path, detected, False)
    try:
        data, _ = _load_json(config_path)
    except (HookError, OSError) as exc:
        return HookStatus(spec, config_path, detected, False, str(exc))
    return HookStatus(
        spec, config_path, detected, _count_agentbell_handlers(data) > 0
    )


def hook_statuses(
    home: Path | None = None, root: Path | None = None
) -> tuple[HookStatus, ...]:
    del root
    return tuple(
        _status_for(spec, hook_config_path(spec, home)) for spec in HOOK_AGENTS
    )


def _preview_json(
    spec: HookAgent,
    path: Path,
    before: dict,
    after: dict,
    backup: Path | None,
) -> str:
    added = _count_agentbell_handlers(after) - _count_agentbell_handlers(before)
    lines = [
        f"目标：{path}",
        f"事件：{', '.join(spec.events)}",
        f"新增 AgentBell hook：{max(0, added)} 个",
        f"保留已有 hook：{_handler_count(before)} 个",
    ]
    if backup is not None:
        lines.append(f"备份：{backup}")
    lines.append("")
    lines.append("写入后内容：")
    lines.append(json.dumps(after, ensure_ascii=False, indent=2))
    return "\n".join(lines)


def plan_install(
    agent_id: str, home: Path | None = None, root: Path | None = None
) -> HookPlan:
    spec = HOOK_AGENT_MAP.get(agent_id)
    if spec is None:
        raise HookError(f"未知的接入目标：{agent_id}")
    base = Path(root or default_app_dir())
    if os.name == "nt":
        source = helper_source()
        if not source.is_file():
            raise HookError(f"缺少接入脚本：{source}")
    path = hook_config_path(spec, home)
    detected_root = _detection_root(spec, path)
    if not detected_root.is_dir():
        raise HookError(f"未检测到 {spec.name} 配置目录：{detected_root}")
    backup = _backup_path(path)
    warnings: list[str] = []
    if spec.support == "partial":
        warnings.append(spec.note)

    if spec.kind == "codex-toml":
        text = _read_text(path)[0] if path.is_file() else ""
        if HOOK_MARKER in text:
            if not _CODEX_BLOCK.search(text):
                raise HookError(_CODEX_UNRESOLVED)
            preview = f"目标：{path}\nCodex 结束提醒已接入，无需重复写入。"
        elif _CODEX_NOTIFY.search(text):
            raise HookError(
                "Codex 已有自定义 notify 配置。为避免覆盖，请先手动移除旧 notify，"
                "或在 AgentBell 中查看接入说明。"
            )
        else:
            block = _codex_block(spec, base)
            preview = (
                f"目标：{path}\n"
                "将插入 Codex 顶层 notify（只在本轮结束时提醒，无法感知等待确认）：\n\n"
                f"{block}"
            )
            if backup is not None:
                preview += f"\n备份：{backup}"
        return HookPlan(spec, "install", path, backup, preview, tuple(warnings))

    data, _ = _load_json(path)
    after = _add_json_hooks(data, spec, _command(spec, base))
    preview = _preview_json(spec, path, data, after, backup)
    return HookPlan(spec, "install", path, backup, preview, tuple(warnings))


def plan_uninstall(
    agent_id: str, home: Path | None = None, root: Path | None = None
) -> HookPlan:
    spec = HOOK_AGENT_MAP.get(agent_id)
    if spec is None:
        raise HookError(f"未知的接入目标：{agent_id}")
    path = hook_config_path(spec, home)
    backup = _backup_path(path)
    if spec.kind == "codex-toml":
        text = _read_text(path)[0] if path.is_file() else ""
        updated, changed = _remove_codex_block(text)
        if not changed and HOOK_MARKER in text:
            raise HookError(_CODEX_UNRESOLVED)
        preview = (
            f"目标：{path}\n将移除 AgentBell 写入的 Codex notify。\n\n"
            f"移除后内容：\n{updated or '（空配置）'}"
        )
        return HookPlan(spec, "uninstall", path, backup, preview)
    data, _ = _load_json(path)
    after = _remove_json_hooks(data)
    preview = (
        f"目标：{path}\n"
        f"将移除 AgentBell hook：{_count_agentbell_handlers(data)} 个\n\n"
        f"移除后内容：\n{json.dumps(after, ensure_ascii=False, indent=2)}"
    )
    return HookPlan(spec, "uninstall", path, backup, preview)


def _copy_helper(root: Path) -> Path:
    source = helper_source()
    if not source.is_file():
        raise HookError(f"缺少接入脚本：{source}")
    target = helper_target(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = source.read_bytes()
    if not target.is_file() or target.read_bytes() != payload:
        tmp = target.with_name(f"{target.name}.agentbell-tmp-{os.getpid()}")
        try:
            tmp.write_bytes(payload)
            os.replace(tmp, target)
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass
    return target


def install_hook(
    agent_id: str, home: Path | None = None, root: Path | None = None
) -> HookResult:
    plan = plan_install(agent_id, home, root)
    base = Path(root or default_app_dir())
    helper = _copy_helper(base) if os.name == "nt" else None
    path = plan.config_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with _config_lock(path):
        if plan.agent.kind == "codex-toml":
            text, bom = _read_text(path) if path.is_file() else ("", False)
            if HOOK_MARKER in text:
                if not _CODEX_BLOCK.search(text):
                    raise HookError(_CODEX_UNRESOLVED)
                suffix = f"（{helper}）" if helper else ""
                return HookResult(
                    agent_id,
                    path,
                    None,
                    False,
                    f"{plan.agent.name} 结束提醒已接入{suffix}",
                )
            if _CODEX_NOTIFY.search(text):
                raise HookError("Codex 已有自定义 notify 配置，未做覆盖")
            updated = _insert_codex_block(text, _codex_block(plan.agent, base))
            backup = _backup(path)
            _write_text(path, updated, bom=bom)
            return HookResult(
                agent_id,
                path,
                backup,
                True,
                f"{plan.agent.name} 结束提醒已接入；等待确认仍需回到终端",
            )

        data, bom = _load_json(path)
        after = _add_json_hooks(data, plan.agent, _command(plan.agent, base))
        if after == data:
            suffix = f"（{helper}）" if helper else ""
            return HookResult(
                agent_id,
                path,
                None,
                False,
                f"{plan.agent.name} 已接入{suffix}",
            )
        backup = _backup(path)
        _write_text(path, json.dumps(after, ensure_ascii=False, indent=2) + "\n", bom=bom)
    return HookResult(
        agent_id,
        path,
        backup,
        True,
        f"{plan.agent.name} 已接入；等待或结束时将自动提醒",
    )


def uninstall_hook(
    agent_id: str, home: Path | None = None, root: Path | None = None
) -> HookResult:
    del root
    spec = HOOK_AGENT_MAP.get(agent_id)
    if spec is None:
        raise HookError(f"未知的接入目标：{agent_id}")
    path = hook_config_path(spec, home)
    if not path.is_file():
        return HookResult(agent_id, path, None, False, f"{spec.name} 尚未接入")
    with _config_lock(path):
        if spec.kind == "codex-toml":
            text, bom = _read_text(path)
            updated, changed = _remove_codex_block(text)
            if not changed:
                if HOOK_MARKER in text:
                    raise HookError(_CODEX_UNRESOLVED)
                return HookResult(agent_id, path, None, False, f"{spec.name} 尚未接入")
            backup = _backup(path)
            _write_text(path, updated, bom=bom)
            return HookResult(agent_id, path, backup, True, f"{spec.name} 接入已撤销")

        data, bom = _load_json(path)
        after = _remove_json_hooks(data)
        if after == data:
            return HookResult(agent_id, path, None, False, f"{spec.name} 尚未接入")
        backup = _backup(path)
        if spec.kind == "grok-json" and not after:
            path.unlink()
        else:
            _write_text(path, json.dumps(after, ensure_ascii=False, indent=2) + "\n", bom=bom)
    return HookResult(agent_id, path, backup, True, f"{spec.name} 接入已撤销")
