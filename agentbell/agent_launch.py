from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .paths import runtime_dir
from .window_focus import FocusRequest

MAX_PROMPT_CHARS = 8000
MAX_TITLE_CHARS = 120


def _runtime_bin_dirs() -> list[str]:
    root = runtime_dir()
    return [str(path) for path in (root / "agents", root / "node") if path.is_dir()]


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
        if not self.ok or self.pid <= 0:
            return None
        return FocusRequest(
            pid=self.pid,
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
        if expanded != candidate and exists(expanded):
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


def _safe_title(agent_name: str, project: Path) -> str:
    title = f"AgentBell · {agent_name} · {project.name or project.drive}"
    title = " ".join(title.replace("\x00", " ").split())
    return title[:MAX_TITLE_CHARS]


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
        try:
            process = popen(
                [availability.executable],
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
        return LaunchResult(
            False,
            "打开终端目前仅支持 Windows",
            agent_id=spec.id,
            agent_name=spec.name,
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
