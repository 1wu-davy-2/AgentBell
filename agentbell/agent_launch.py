from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .paths import runtime_dir
from .window_focus import FocusRequest

MAX_PROMPT_CHARS = 8000
MAX_TITLE_CHARS = 120


def _runtime_bin_dirs() -> list[str]:
    root = runtime_dir()
    if os.name == "nt":
        candidates = (root / "agents", root / "node")
    else:
        candidates = (
            root / "agents" / "bin",
            root / "node" / "bin",
            root / "agents",
            root / "node",
        )
    return [str(path) for path in candidates if path.is_dir()]


@dataclass(frozen=True, slots=True)
class AgentSpec:
    id: str
    name: str
    kind: str
    summary: str
    commands: tuple[str, ...] = ()
    desktop_paths: tuple[str, ...] = ()
    install_hint: str = "安装后重新检测"
    prompt_supported: bool = True
    project_url: str = ""


@dataclass(frozen=True, slots=True)
class AgentAvailability:
    spec: AgentSpec
    executable: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.executable)

    @property
    def kind_label(self) -> str:
        return "桌面应用" if self.spec.kind == "desktop" else "终端"

    @property
    def target(self) -> str:
        return self.executable or self.spec.install_hint


@dataclass(frozen=True, slots=True)
class LaunchResult:
    ok: bool
    message: str
    agent_id: str = ""
    agent_name: str = ""
    agent_kind: str = ""
    pid: int = 0
    title: str = ""
    working_dir: str = ""
    executable: str = ""
    prompt_sent: bool = False

    def focus_request(self) -> FocusRequest | None:
        if not self.ok or (self.pid <= 0 and not self.title):
            return None
        return FocusRequest(
            pid=self.pid if self.pid > 0 else None,
            window_title=self.title,
            working_dir=self.working_dir,
        )


AGENT_SPECS: tuple[AgentSpec, ...] = (
    AgentSpec(
        id="claude-code",
        name="Claude Code",
        kind="cli",
        summary="Anthropic 官方终端编码 Agent",
        commands=("claude",),
        install_hint="npm install -g @anthropic-ai/claude-code",
        project_url="https://github.com/anthropics/claude-code",
    ),
    AgentSpec(
        id="claude-desktop",
        name="Claude Desktop",
        kind="desktop",
        summary="Anthropic 桌面客户端",
        desktop_paths=(
            r"%LOCALAPPDATA%\AnthropicClaude\claude.exe",
            r"%LOCALAPPDATA%\Programs\Claude\Claude.exe",
            "/Applications/Claude.app",
            "~/Applications/Claude.app",
        ),
        install_hint="从 claude.ai/download 安装桌面版",
        prompt_supported=False,
        project_url="https://claude.ai/download",
    ),
    AgentSpec(
        id="codex",
        name="Codex",
        kind="cli",
        summary="OpenAI 终端编码 Agent",
        commands=("codex",),
        install_hint="npm install -g @openai/codex",
        project_url="https://github.com/openai/codex",
    ),
    AgentSpec(
        id="gemini-cli",
        name="Gemini CLI",
        kind="cli",
        summary="Google 终端 Agent",
        commands=("gemini",),
        install_hint="npm install -g @google/gemini-cli",
        project_url="https://github.com/google-gemini/gemini-cli",
    ),
    AgentSpec(
        id="grok",
        name="Grok Build",
        kind="cli",
        summary="xAI 终端 Agent",
        commands=("grok",),
        install_hint="安装 Grok CLI 并加入 PATH",
        project_url="https://github.com/xai-org/grok-build",
    ),
    AgentSpec(
        id="opencode",
        name="OpenCode",
        kind="cli",
        summary="开源终端编码 Agent",
        commands=("opencode",),
        install_hint="安装 OpenCode CLI 并加入 PATH",
        project_url="https://github.com/anomalyco/opencode",
    ),
    AgentSpec(
        id="openclaw",
        name="OpenClaw",
        kind="cli",
        summary="开源 Agent 客户端",
        commands=("openclaw",),
        install_hint="安装 OpenClaw 并加入 PATH",
        project_url="https://github.com/openclaw/openclaw",
    ),
    AgentSpec(
        id="hermes",
        name="Hermes",
        kind="cli",
        summary="Nous Research 终端 Agent",
        commands=("hermes",),
        install_hint="安装 Hermes CLI 并加入 PATH",
        project_url="https://github.com/NousResearch/hermes-agent",
    ),
    AgentSpec(
        id="pi",
        name="Pi",
        kind="cli",
        summary="Earendil Works 终端 Agent",
        commands=("pi",),
        install_hint="npm install -g @earendil-works/pi-coding-agent",
        project_url="https://github.com/earendil-works/pi",
    ),
    AgentSpec(
        id="minimax-code",
        name="MiniMax Code",
        kind="cli",
        summary="MiniMax 编码 Agent",
        commands=("minimax",),
        install_hint="安装 MiniMax Code CLI 并加入 PATH",
        project_url="https://github.com/MiniMax-AI/minimax-code",
    ),
    AgentSpec(
        id="antigravity",
        name="Antigravity",
        kind="desktop",
        summary="Google 的 Agent 开发环境",
        desktop_paths=(
            r"%LOCALAPPDATA%\Programs\Antigravity\Antigravity.exe",
            r"%LOCALAPPDATA%\Antigravity\Antigravity.exe",
            "/Applications/Antigravity.app",
            "~/Applications/Antigravity.app",
        ),
        install_hint="安装 Antigravity 后重新检测",
        prompt_supported=False,
        project_url="https://antigravity.google/",
    ),
)

_SPEC_BY_ID = {spec.id: spec for spec in AGENT_SPECS}


def agent_spec(agent_id: str) -> AgentSpec | None:
    return _SPEC_BY_ID.get(agent_id)


def _expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


def _desktop_executable(
    paths: Sequence[str], exists: Callable[[str], bool]
) -> str:
    for candidate in paths:
        expanded = _expand(candidate)
        if expanded == candidate and ("%" in candidate or candidate.startswith("~")):
            continue
        if exists(expanded):
            return expanded
    return ""


def discover_agents(
    env: Mapping[str, str] | None = None,
    *,
    which: Callable[..., str | None] = shutil.which,
    exists: Callable[[str], bool] = os.path.exists,
) -> list[AgentAvailability]:
    environment = os.environ if env is None else env
    path = environment.get("PATH", "")
    bins = _runtime_bin_dirs()
    if bins:
        path = os.pathsep.join(bins + ([path] if path else []))
    found: list[AgentAvailability] = []
    for spec in AGENT_SPECS:
        executable = ""
        if spec.commands:
            for command in spec.commands:
                resolved = which(command, path=path)
                if resolved:
                    executable = resolved
                    break
        if not executable and spec.desktop_paths:
            executable = _desktop_executable(spec.desktop_paths, exists)
        found.append(AgentAvailability(spec=spec, executable=executable))
    found.sort(key=lambda item: (not item.installed, AGENT_SPECS.index(item.spec)))
    return found


def _powershell_path(env: Mapping[str, str]) -> str:
    system_root = env.get("SystemRoot", r"C:\Windows")
    candidate = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if candidate.exists():
        return str(candidate)
    return shutil.which("powershell", path=env.get("PATH", "")) or ""


def _desktop_command(executable: str) -> list[str]:
    if sys.platform == "darwin" and executable.lower().endswith(".app"):
        return ["open", "-a", executable]
    return [executable]


def _safe_title(agent_name: str, project: Path) -> str:
    title = f"AgentBell · {agent_name} · {project.name or str(project)}"
    title = " ".join(title.replace("\x00", " ").split())
    return title[:MAX_TITLE_CHARS]


def _linux_shell(env: Mapping[str, str]) -> str:
    path = env.get("PATH", "")
    for name in ("bash", "sh"):
        found = shutil.which(name, path=path)
        if found:
            return found
    return "/bin/sh"


def _linux_terminal_command(
    env: Mapping[str, str], title: str, shell: str
) -> list[str] | None:
    path = env.get("PATH", "")
    script = (
        "printf '\\033]0;%s\\007' \"$AGENTBELL_TITLE\"; "
        "cd \"$AGENTBELL_CWD\" || exit 1; "
        "if [ -n \"$AGENTBELL_PROMPT\" ]; then "
        "\"$AGENTBELL_EXE\" \"$AGENTBELL_PROMPT\"; else "
        "\"$AGENTBELL_EXE\"; fi; "
        "exec \"${SHELL:-/bin/sh}\" -i"
    )
    shell_args = [shell, "-lc", script]
    candidates: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("kgx", ("--",)),
        ("gnome-terminal", ("--title", title, "--")),
        ("konsole", ("-p", f"tabtitle={title}", "-e")),
        ("xfce4-terminal", ("--title", title, "-x")),
        ("mate-terminal", ("--title", title, "-x")),
        ("tilix", ("-t", title, "-e", shlex.join(shell_args))),
        ("kitty", ("--title", title)),
        ("alacritty", ("--title", title, "-e")),
        ("wezterm", ("start", "--")),
        ("xterm", ("-T", title, "-e")),
        ("urxvt", ("-title", title, "-e")),
        ("st", ("-T", title, "-e")),
        ("x-terminal-emulator", ("-e",)),
    )
    for name, prefix in candidates:
        executable = shutil.which(name, path=path)
        if not executable:
            continue
        if name == "tilix":
            return [executable, *prefix]
        return [executable, *prefix, *shell_args]
    return None


def _launch_linux_terminal(
    availability: AgentAvailability,
    project: Path,
    prompt: str,
    environment: dict[str, str],
    popen: Callable[..., object],
) -> LaunchResult:
    spec = availability.spec
    shell = _linux_shell(environment)
    title = _safe_title(spec.name, project)
    command = _linux_terminal_command(environment, title, shell)
    if command is None:
        return LaunchResult(
            False,
            "未找到可用的终端模拟器，请安装 gnome-terminal、konsole 或 xterm",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    environment.update(
        {
            "AGENTBELL_EXE": availability.executable,
            "AGENTBELL_PROMPT": prompt,
            "AGENTBELL_CWD": str(project),
            "AGENTBELL_TITLE": title,
        }
    )
    environment.setdefault("SHELL", shell)
    try:
        process = popen(
            command,
            cwd=str(project),
            env=environment,
            close_fds=True,
        )
    except OSError as exc:
        return LaunchResult(
            False,
            f"无法打开终端：{exc}",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    return LaunchResult(
        True,
        f"已在终端中启动 {spec.name}" + ("，并输入了提示词" if prompt else ""),
        agent_id=spec.id,
        agent_name=spec.name,
        agent_kind=spec.kind,
        pid=int(getattr(process, "pid", 0) or 0),
        title=title,
        working_dir=str(project),
        executable=availability.executable,
        prompt_sent=bool(prompt),
    )


_MAC_TERMINAL_SCRIPT = r'''
on run argv
    set targetDir to item 1 of argv
    set targetExe to item 2 of argv
    set targetPrompt to item 3 of argv
    set targetTitle to item 4 of argv
    set commandText to "cd " & quoted form of targetDir & " && printf '\\033]0;%s\\007' " & quoted form of targetTitle & " && " & quoted form of targetExe
    if targetPrompt is not "" then set commandText to commandText & " " & quoted form of targetPrompt
    set commandText to commandText & "; exec ${SHELL:-/bin/zsh} -i"
    tell application "Terminal"
        activate
        do script commandText
    end tell
    return "ok"
end run
'''


def _launch_macos_terminal(
    availability: AgentAvailability,
    project: Path,
    prompt: str,
    environment: dict[str, str],
    popen: Callable[..., object],
) -> LaunchResult:
    spec = availability.spec
    title = _safe_title(spec.name, project)
    try:
        process = popen(
            [
                "osascript",
                "-e",
                _MAC_TERMINAL_SCRIPT,
                str(project),
                availability.executable,
                prompt,
                title,
            ],
            cwd=str(project),
            env=environment,
            close_fds=True,
        )
    except OSError as exc:
        return LaunchResult(
            False,
            f"无法打开终端：{exc}",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    return LaunchResult(
        True,
        f"已在终端中启动 {spec.name}" + ("，并输入了提示词" if prompt else ""),
        agent_id=spec.id,
        agent_name=spec.name,
        agent_kind=spec.kind,
        pid=0,
        title=title,
        working_dir=str(project),
        executable=availability.executable,
        prompt_sent=bool(prompt),
    )


def launch_agent(
    availability: AgentAvailability,
    project_dir: str,
    prompt: str = "",
    *,
    env: Mapping[str, str] | None = None,
    extra_env: Mapping[str, str] | None = None,
    popen: Callable[..., object] = subprocess.Popen,
) -> LaunchResult:
    spec = availability.spec
    if not availability.installed:
        return LaunchResult(
            False,
            f"未检测到 {spec.name}，请先安装：{spec.install_hint}",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    project = Path(project_dir).expanduser()
    if not project.is_dir():
        return LaunchResult(
            False,
            "项目目录不存在，请重新选择",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    if "\x00" in prompt:
        return LaunchResult(
            False,
            "提示词包含无效字符",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    prompt = prompt.strip()
    if len(prompt) > MAX_PROMPT_CHARS:
        return LaunchResult(
            False,
            f"提示词不能超过 {MAX_PROMPT_CHARS} 个字符",
            agent_id=spec.id,
            agent_name=spec.name,
        )

    environment = dict(os.environ if env is None else env)
    if extra_env:
        environment.update({key: str(value) for key, value in extra_env.items()})
    bins = _runtime_bin_dirs()
    if bins:
        inherited = environment.get("PATH", "")
        environment["PATH"] = os.pathsep.join(
            bins + ([inherited] if inherited else [])
        )
    if spec.kind == "desktop":
        command = _desktop_command(availability.executable)
        try:
            process = popen(
                command,
                cwd=str(project),
                env=environment,
                close_fds=True,
            )
        except OSError as exc:
            return LaunchResult(
                False,
                f"无法启动 {spec.name}：{exc}",
                agent_id=spec.id,
                agent_name=spec.name,
            )
        note = "已打开桌面应用"
        if prompt:
            note += "；桌面应用不支持自动预填提示词"
        return LaunchResult(
            True,
            note,
            agent_id=spec.id,
            agent_name=spec.name,
            agent_kind=spec.kind,
            pid=int(getattr(process, "pid", 0) or 0),
            working_dir=str(project),
            executable=availability.executable,
        )

    if os.name != "nt":
        if sys.platform == "darwin":
            return _launch_macos_terminal(
                availability,
                project,
                prompt,
                environment,
                popen,
            )
        if not sys.platform.startswith("linux"):
            return LaunchResult(
                False,
                "打开终端目前仅支持 Windows、Linux 和 macOS",
                agent_id=spec.id,
                agent_name=spec.name,
            )
        return _launch_linux_terminal(
            availability,
            project,
            prompt,
            environment,
            popen,
        )

    powershell = _powershell_path(environment)
    if not powershell:
        return LaunchResult(
            False,
            "未找到 PowerShell，无法打开终端",
            agent_id=spec.id,
            agent_name=spec.name,
        )

    title = _safe_title(spec.name, project)
    environment.update(
        {
            "AGENTBELL_EXE": availability.executable,
            "AGENTBELL_PROMPT": prompt,
            "AGENTBELL_CWD": str(project),
            "AGENTBELL_TITLE": title,
        }
    )
    script = (
        "$Host.UI.RawUI.WindowTitle = $env:AGENTBELL_TITLE; "
        "Set-Location -LiteralPath $env:AGENTBELL_CWD; "
        "if ([string]::IsNullOrEmpty($env:AGENTBELL_PROMPT)) { "
        "& $env:AGENTBELL_EXE } else { "
        "& $env:AGENTBELL_EXE $env:AGENTBELL_PROMPT }"
    )
    creation_flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        process = popen(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-NoExit",
                "-Command",
                script,
            ],
            cwd=str(project),
            env=environment,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        return LaunchResult(
            False,
            f"无法打开终端：{exc}",
            agent_id=spec.id,
            agent_name=spec.name,
        )
    return LaunchResult(
        True,
        f"已在终端中启动 {spec.name}" + ("，并输入了提示词" if prompt else ""),
        agent_id=spec.id,
        agent_name=spec.name,
        agent_kind=spec.kind,
        pid=int(getattr(process, "pid", 0) or 0),
        title=title,
        working_dir=str(project),
        executable=availability.executable,
        prompt_sent=bool(prompt),
    )


def launch_focus_value(result: LaunchResult) -> str:
    request = result.focus_request()
    return request.to_value() if request is not None else ""


def launch_to_json(result: LaunchResult) -> str:
    return json.dumps(
        {
            "agent": result.agent_id,
            "pid": result.pid,
            "title": result.title,
            "cwd": result.working_dir,
        },
        ensure_ascii=False,
    )
