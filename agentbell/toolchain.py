from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

from . import __version__
from .paths import runtime_dir

NODE_INDEX_URL = "https://nodejs.org/dist/index.json"
NODE_DIST_ROOT = "https://nodejs.org/dist"
NPM_REGISTRY_OFFICIAL = "https://registry.npmjs.org"
NPM_REGISTRY_MIRROR = "https://registry.npmmirror.com"

MANIFEST_NAME = "tools.json"
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_EXTRACT_BYTES = 900 * 1024 * 1024
CHUNK_SIZE = 256 * 1024
NPM_TIMEOUT_SECONDS = 1800
PROBE_TIMEOUT_SECONDS = 8

ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "nodejs.org",
        "registry.npmjs.org",
        "registry.npmmirror.com",
    }
)

_ARCHIVE_HASH = re.compile(r"^[0-9a-f]{64}$")


class ToolchainError(RuntimeError):
    """Raised when a runtime component cannot be downloaded or installed."""


@dataclass(frozen=True, slots=True)
class NpmToolSpec:
    id: str
    name: str
    package: str
    command: str
    summary: str
    project_url: str


NPM_TOOLS: tuple[NpmToolSpec, ...] = (
    NpmToolSpec(
        "claude-code",
        "Claude Code",
        "@anthropic-ai/claude-code",
        "claude",
        "Anthropic 官方终端编码 Agent",
        "https://github.com/anthropics/claude-code",
    ),
    NpmToolSpec(
        "codex",
        "Codex",
        "@openai/codex",
        "codex",
        "OpenAI 终端编码 Agent",
        "https://github.com/openai/codex",
    ),
    NpmToolSpec(
        "gemini-cli",
        "Gemini CLI",
        "@google/gemini-cli",
        "gemini",
        "Google 终端 Agent",
        "https://github.com/google-gemini/gemini-cli",
    ),
    NpmToolSpec(
        "opencode",
        "OpenCode",
        "opencode-ai",
        "opencode",
        "开源终端编码 Agent",
        "https://github.com/sst/opencode",
    ),
    NpmToolSpec(
        "openclaw",
        "OpenClaw",
        "openclaw",
        "openclaw",
        "开源 Agent 客户端",
        "https://github.com/openclaw/openclaw",
    ),
    NpmToolSpec(
        "hermes",
        "Hermes",
        "hermes-agent",
        "hermes",
        "Nous Research 终端 Agent",
        "https://github.com/NousResearch/hermes-agent",
    ),
    NpmToolSpec(
        "pi",
        "Pi",
        "@earendil-works/pi-coding-agent",
        "pi",
        "Earendil Works 终端 Agent",
        "https://github.com/earendil-works/pi",
    ),
)

_TOOL_BY_ID = {tool.id: tool for tool in NPM_TOOLS}
NODE_ID = "node"

DEEPSEEK_CLAUDE_ENV = {
    "ANTHROPIC_BASE_URL": "https://api.deepseek.com/anthropic",
    "ANTHROPIC_MODEL": "deepseek-chat",
    "ANTHROPIC_SMALL_FAST_MODEL": "deepseek-chat",
}

DEEPSEEK_CODEX_TOML = """model_provider = "deepseek"
model = "deepseek-chat"

[model_providers.deepseek]
name = "DeepSeek"
base_url = "https://api.deepseek.com/v1"
env_key = "DEEPSEEK_API_KEY"
"""


@dataclass(frozen=True, slots=True)
class ComponentState:
    id: str
    name: str
    kind: str
    summary: str
    version: str = ""
    path: str = ""
    project_url: str = ""

    @property
    def installed(self) -> bool:
        return bool(self.version)


@dataclass(frozen=True, slots=True)
class ToolchainState:
    root: str
    node: ComponentState
    tools: tuple[ComponentState, ...]

    def component(self, component_id: str) -> ComponentState | None:
        if component_id == self.node.id:
            return self.node
        for tool in self.tools:
            if tool.id == component_id:
                return tool
        return None


@dataclass(frozen=True, slots=True)
class Progress:
    stage: str
    percent: int = -1
    detail: str = ""


ProgressCallback = Callable[[Progress], None]


def _noop(_progress: Progress) -> None:
    return None


def validate_registry(value: str) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        return NPM_REGISTRY_OFFICIAL
    parts = urlsplit(text)
    if parts.scheme != "https":
        raise ToolchainError("npm 源必须是 HTTPS 地址")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        raise ToolchainError(f"npm 源不在允许列表内：{host or text}")
    return text


def _check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise ToolchainError(f"只允许 HTTPS 下载：{url}")
    host = (parts.hostname or "").lower()
    if host not in ALLOWED_DOWNLOAD_HOSTS:
        raise ToolchainError(f"下载地址不在允许列表内：{host or url}")
    return url


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _build_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_AllowlistRedirectHandler())


def _user_agent() -> str:
    return f"AgentBell/{__version__} (+https://github.com/1wu-davy-2/AgentBell)"


def _request(url: str) -> urllib.request.Request:
    _check_url(url)
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": _user_agent(),
            "Accept": "application/json, */*;q=0.8",
        },
    )


def _read_limited(response, limit: int) -> bytes:  # noqa: ANN001
    data = response.read(limit + 1)
    if len(data) > limit:
        raise ToolchainError("远端响应超过大小限制")
    return data


def safe_extract_zip(archive: Path, destination: Path) -> None:
    """Extract a zip while rejecting traversal, absolute paths and oversized trees."""
    total = 0
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            name = info.filename.replace("\\", "/")
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or ":" in pure.parts[0]:
                raise ToolchainError(f"压缩包包含非法路径：{info.filename}")
            total += max(info.file_size, 0)
            if total > MAX_EXTRACT_BYTES:
                raise ToolchainError("压缩包解压后体积超过限制")
        destination.mkdir(parents=True, exist_ok=True)
        bundle.extractall(destination)


def _swap_directory(source: Path, target: Path) -> None:
    backup = target.with_name(target.name + ".old")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.rename(backup)
    try:
        source.rename(target)
    except OSError:
        if backup.exists() and not target.exists():
            backup.rename(target)
        raise
    shutil.rmtree(backup, ignore_errors=True)


def _single_root(folder: Path) -> Path:
    entries = [item for item in folder.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return folder


def _read_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_file(path: Path, data: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def protect_secret(value: str) -> str:
    """Store a secret with Windows DPAPI when available."""
    text = (value or "").strip()
    if not text:
        return ""
    try:
        import win32crypt  # type: ignore

        blob = win32crypt.CryptProtectData(
            text.encode("utf-8"), "AgentBell", None, None, None, 0
        )
        return "dpapi:" + base64.b64encode(blob).decode("ascii")
    except Exception:
        return "plain:" + base64.b64encode(text.encode("utf-8")).decode("ascii")


def reveal_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    try:
        if text.startswith("dpapi:"):
            import win32crypt  # type: ignore

            raw = base64.b64decode(text[len("dpapi:") :])
            return win32crypt.CryptUnprotectData(raw, None, None, None, 0)[1].decode(
                "utf-8"
            )
        if text.startswith("plain:"):
            return base64.b64decode(text[len("plain:") :]).decode("utf-8")
    except Exception:
        return ""
    return text


def deepseek_claude_env(api_key: str) -> dict[str, str]:
    key = (api_key or "").strip()
    if not key:
        return {}
    env = dict(DEEPSEEK_CLAUDE_ENV)
    env["ANTHROPIC_AUTH_TOKEN"] = key
    env["ANTHROPIC_API_KEY"] = key
    return env


def runtime_env(
    root: Path | None = None, base: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Environment that makes the portable runtime visible to child processes."""
    base_dir = Path(root) if root is not None else runtime_dir()
    env = dict(os.environ if base is None else base)
    prefixes = [str(base_dir / "agents"), str(base_dir / "node")]
    path = env.get("PATH", "")
    env["PATH"] = os.pathsep.join(prefixes + ([path] if path else []))
    env["AGENTBELL_RUNTIME"] = str(base_dir)
    return env


class ToolchainService:
    def __init__(
        self,
        root: Path | None = None,
        *,
        registry: str = NPM_REGISTRY_OFFICIAL,
        logger=None,  # noqa: ANN001
        opener: urllib.request.OpenerDirector | None = None,
        runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
        node_index_url: str = NODE_INDEX_URL,
    ) -> None:
        self.root = Path(root) if root is not None else runtime_dir()
        self.registry = validate_registry(registry)
        self.logger = logger
        self._opener = opener or _build_opener()
        self._runner = runner
        self._node_index_url = node_index_url

    # ---------- layout ----------

    @property
    def node_dir(self) -> Path:
        return self.root / "node"

    @property
    def node_exe(self) -> Path:
        return self.node_dir / ("node.exe" if os.name == "nt" else "bin/node")

    @property
    def npm_cli(self) -> Path:
        return self.node_dir / "node_modules" / "npm" / "bin" / "npm-cli.js"

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def _npmrc(self) -> Path:
        return self.root / "npmrc"

    def _ensure_npmrc(self) -> Path:
        path = self._npmrc()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fund=false\naudit=false\nupdate-notifier=false\n", encoding="utf-8")
        return path

    # ---------- network ----------

    def _get_json(self, url: str):  # noqa: ANN201
        with self._opener.open(_request(url), timeout=30) as response:
            raw = _read_limited(response, MAX_JSON_BYTES)
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError as exc:
            raise ToolchainError("远端返回的不是有效 JSON") from exc

    def _get_text(self, url: str, limit: int = MAX_JSON_BYTES) -> str:
        with self._opener.open(_request(url), timeout=30) as response:
            return _read_limited(response, limit).decode("utf-8", "replace")

    def _download(
        self,
        url: str,
        destination: Path,
        progress: ProgressCallback,
        stage: str,
        limit: int = MAX_ARCHIVE_BYTES,
    ) -> str:
        _check_url(url)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        written = 0
        with self._opener.open(_request(url), timeout=60) as response:
            length = 0
            header = response.headers.get("Content-Length") or ""
            if header.isdigit():
                length = int(header)
            if length > limit:
                raise ToolchainError("下载内容超过大小限制")
            temp = destination.with_name(destination.name + ".part")
            with temp.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > limit:
                        handle.close()
                        temp.unlink(missing_ok=True)
                        raise ToolchainError("下载内容超过大小限制")
                    digest.update(chunk)
                    handle.write(chunk)
                    if length:
                        percent = min(99, int(written * 100 / length))
                    else:
                        percent = -1
                    progress(Progress(stage, percent, _human_size(written)))
        os.replace(temp, destination)
        return digest.hexdigest()

    # ---------- manifest ----------

    def manifest(self) -> dict:
        return _read_json_file(self.manifest_path)

    def _record(self, section: str, key: str, value: dict) -> None:
        data = self.manifest()
        block = data.get(section)
        if not isinstance(block, dict):
            block = {}
        block[key] = value
        data[section] = block
        data["version"] = 1
        _write_json_file(self.manifest_path, data)

    def _forget(self, section: str, key: str) -> None:
        data = self.manifest()
        block = data.get(section)
        if isinstance(block, dict) and key in block:
            block.pop(key, None)
            data[section] = block
            _write_json_file(self.manifest_path, data)

    # ---------- node ----------

    def resolve_node_release(self, arch: str = "") -> tuple[str, str, str]:
        data = self._get_json(self._node_index_url)
        rows = data if isinstance(data, list) else []
        latest = ""
        for row in rows:
            if not isinstance(row, dict):
                continue
            if row.get("lts"):
                latest = str(row.get("version") or "")
                break
        if not latest:
            raise ToolchainError("无法从 nodejs.org 解析最新 LTS 版本")
        platform_arch = arch or _windows_arch()
        filename = f"node-{latest}-{platform_arch}.zip"
        zip_url = f"{NODE_DIST_ROOT}/{latest}/{filename}"
        shasums_url = f"{NODE_DIST_ROOT}/{latest}/SHASUMS256.txt"
        return latest, zip_url, shasums_url

    def node_version(self) -> str:
        block = self.manifest().get("node")
        if isinstance(block, dict):
            record = block.get("runtime")
            if isinstance(record, dict) and self.node_exe.exists():
                return str(record.get("version") or "")
        return ""

    def install_node(self, progress: ProgressCallback | None = None) -> str:
        report = progress or _noop
        if os.name != "nt":
            raise ToolchainError("便携 Node 目前仅支持 Windows")
        version, zip_url, shasums_url = self.resolve_node_release()
        report(Progress(f"准备下载 Node {version}", 0))
        with tempfile.TemporaryDirectory(dir=str(self._temp_root())) as temp:
            temp_dir = Path(temp)
            archive = temp_dir / Path(urlsplit(zip_url).path).name
            report(Progress(f"下载 Node {version}", 0))
            actual = self._download(zip_url, archive, report, f"下载 Node {version}")
            report(Progress("校验 Node 安装包", 99))
            expected = _parse_shasums(self._get_text(shasums_url), archive.name)
            if not expected or expected != actual:
                raise ToolchainError("Node 安装包校验失败，文件可能不完整")
            report(Progress("解压 Node", -1))
            extracted = temp_dir / "unpacked"
            safe_extract_zip(archive, extracted)
            inner = _single_root(extracted)
            if not (inner / "node.exe").exists():
                raise ToolchainError("Node 安装包结构异常，未找到 node.exe")
            _swap_directory(inner, self.node_dir)
        self._record(
            "node",
            "runtime",
            {
                "version": version,
                "archive_sha256": actual,
                "installed_at": _timestamp(),
            },
        )
        report(Progress(f"Node {version} 已安装", 100))
        return version

    def ensure_node(self, progress: ProgressCallback | None = None) -> str:
        version = self.node_version()
        if version:
            return version
        return self.install_node(progress)

    # ---------- npm tools ----------

    def tool_version(self, tool_id: str) -> str:
        tool = _TOOL_BY_ID.get(tool_id)
        if tool is None:
            return ""
        package_json = (
            self.agents_dir / "node_modules" / Path(*tool.package.split("/")) / "package.json"
        )
        data = _read_json_file(package_json)
        return str(data.get("version") or "")

    def _npm_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["npm_config_cache"] = str(self.cache_dir / "npm")
        env["npm_config_prefix"] = str(self.agents_dir)
        env["npm_config_userconfig"] = str(self._ensure_npmrc())
        env["npm_config_registry"] = self.registry
        env["npm_config_fund"] = "false"
        env["npm_config_audit"] = "false"
        env["npm_config_update_notifier"] = "false"
        env["PATH"] = os.pathsep.join(
            [str(self.node_dir), str(self.agents_dir), env.get("PATH", "")]
        )
        return env

    def _run_npm(
        self, args: Sequence[str], progress: ProgressCallback, stage: str
    ) -> None:
        if not self.node_exe.exists() or not self.npm_cli.exists():
            raise ToolchainError("请先安装 Node 运行环境")
        command = [
            str(self.node_exe),
            str(self.npm_cli),
            *args,
            "--registry",
            self.registry,
            "--no-fund",
            "--no-audit",
            "--loglevel=error",
        ]
        if self.logger is not None:
            self.logger.info("toolchain npm %s", " ".join(args))
        try:
            result = self._runner(
                command,
                cwd=str(self.root),
                env=self._npm_env(),
                capture_output=True,
                text=True,
                timeout=NPM_TIMEOUT_SECONDS,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolchainError("安装超时，请检查网络后重试") from exc
        except OSError as exc:
            raise ToolchainError(f"无法运行 npm：{exc}") from exc
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "").strip()
            raise ToolchainError(
                f"{stage}失败（npm 退出码 {result.returncode}）："
                f"{message[-400:] or '没有输出，可能是安全软件拦截或网络中断'}"
            )

    def install_tool(
        self, tool_id: str, progress: ProgressCallback | None = None
    ) -> str:
        tool = _TOOL_BY_ID.get(tool_id)
        if tool is None:
            raise ToolchainError(f"未知组件：{tool_id}")
        report = progress or _noop
        self.ensure_node(report)
        report(Progress(f"安装 {tool.name}", -1))
        self._run_npm(
            ["install", "-g", "--prefix", str(self.agents_dir), tool.package],
            report,
            f"安装 {tool.name}",
        )
        version = self.tool_version(tool.id)
        if not version:
            raise ToolchainError(f"{tool.name} 安装后未找到版本信息")
        self._record(
            "tools",
            tool.id,
            {
                "version": version,
                "package": tool.package,
                "registry": self.registry,
                "installed_at": _timestamp(),
            },
        )
        report(Progress(f"{tool.name} {version} 已安装", 100))
        return version

    def uninstall(self, component_id: str, progress: ProgressCallback | None = None) -> str:
        report = progress or _noop
        if component_id == NODE_ID:
            if self.node_dir.exists():
                shutil.rmtree(self.node_dir, ignore_errors=True)
            self._forget("node", "runtime")
            report(Progress("Node 已移除", 100))
            return "Node 已移除"
        tool = _TOOL_BY_ID.get(component_id)
        if tool is None:
            raise ToolchainError(f"未知组件：{component_id}")
        if self.node_exe.exists() and self.npm_cli.exists():
            report(Progress(f"卸载 {tool.name}", -1))
            self._run_npm(
                ["uninstall", "-g", "--prefix", str(self.agents_dir), tool.package],
                report,
                f"卸载 {tool.name}",
            )
        self._remove_tool_shims(tool)
        package_dir = (
            self.agents_dir / "node_modules" / Path(*tool.package.split("/"))
        )
        if package_dir.exists():
            shutil.rmtree(package_dir, ignore_errors=True)
        self._forget("tools", tool.id)
        report(Progress(f"{tool.name} 已卸载", 100))
        return f"{tool.name} 已卸载"

    def _remove_tool_shims(self, tool: NpmToolSpec) -> None:
        for suffix in ("", ".cmd", ".ps1", ".sh"):
            candidate = self.agents_dir / f"{tool.command}{suffix}"
            try:
                candidate.unlink()
            except OSError:
                continue

    def tool_executable(self, tool_id: str) -> Path | None:
        tool = _TOOL_BY_ID.get(tool_id)
        if tool is None:
            return None
        for suffix in (".cmd", ".exe", ""):
            candidate = self.agents_dir / f"{tool.command}{suffix}"
            if candidate.exists():
                return candidate
        return None

    # ---------- state ----------

    def state(self) -> ToolchainState:
        node_version = self.node_version()
        node = ComponentState(
            id=NODE_ID,
            name="Node 运行环境",
            kind="runtime",
            summary="便携 Node.js LTS，Agent CLI 的运行基础",
            version=node_version,
            path=str(self.node_exe) if node_version else "",
            project_url="https://nodejs.org/",
        )
        tools: list[ComponentState] = []
        for spec in NPM_TOOLS:
            version = self.tool_version(spec.id)
            executable = self.tool_executable(spec.id)
            tools.append(
                ComponentState(
                    id=spec.id,
                    name=spec.name,
                    kind="npm",
                    summary=spec.summary,
                    version=version,
                    path=str(executable) if executable else "",
                    project_url=spec.project_url,
                )
            )
        return ToolchainState(root=str(self.root), node=node, tools=tuple(tools))

    def _temp_root(self) -> Path:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir


def _parse_shasums(text: str, filename: str) -> str:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[-1].lstrip("*") == filename:
            candidate = parts[0].lower()
            if _ARCHIVE_HASH.match(candidate):
                return candidate
    return ""


def _windows_arch() -> str:
    machine = platform.machine().lower()
    if machine in {"arm64", "aarch64"}:
        return "win-arm64"
    return "win-x64"


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
