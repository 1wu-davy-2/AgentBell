from __future__ import annotations

import hashlib
import json
import os
import platform as _platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit

from . import __version__
from .paths import updates_dir

API_ROOT = "https://api.github.com"
RELEASE_BYTES_LIMIT = 1_048_576
DOWNLOAD_BYTES_LIMIT = 300 * 1024 * 1024
CHUNK_SIZE = 256 * 1024
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
        "github-releases.githubusercontent.com",
    }
)
_REPO_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
_VERSION_CORE = re.compile(r"^[vV]?(\d+)(?:\.(\d+))?(?:\.(\d+))?")

LINUX_REPLACE_SCRIPT = """#!/bin/sh
set -u
target="$AGENTBELL_UPDATE_TARGET"
source="$AGENTBELL_UPDATE_SOURCE"
backup="$AGENTBELL_UPDATE_BACKUP"
log="$AGENTBELL_UPDATE_LOG"
pid="$AGENTBELL_UPDATE_PID"
log_line() {
    [ -n "$log" ] || return 0
    { date '+%Y-%m-%dT%H:%M:%S%z'; printf ' %s\\n' "$1"; } >>"$log" 2>/dev/null || true
}
if [ -n "$pid" ]; then
    waited=0
    while kill -0 "$pid" 2>/dev/null; do
        waited=$((waited + 1))
        [ "$waited" -ge 120 ] && break
        sleep 0.5
    done
fi
sleep 0.5
if [ -f "$target" ]; then
    cp -p "$target" "$backup" 2>/dev/null || true
fi
staged="$target.new.$$"
if cp -p "$source" "$staged" 2>/dev/null &&
    chmod 755 "$staged" 2>/dev/null &&
    mv -f "$staged" "$target" 2>/dev/null; then
    log_line "updated ${AGENTBELL_UPDATE_VERSION:-unknown}"
else
    rm -f "$staged" 2>/dev/null || true
    log_line "replace failed; keeping previous binary"
fi
if [ -n "${AGENTBELL_UPDATE_CWD:-}" ] && [ -d "$AGENTBELL_UPDATE_CWD" ]; then
    cd "$AGENTBELL_UPDATE_CWD" || cd /
fi
@@RESTART@@
"""

REPLACE_SCRIPT = """$ErrorActionPreference = 'Stop'
$target = $env:AGENTBELL_UPDATE_TARGET
$source = $env:AGENTBELL_UPDATE_SOURCE
$backup = $env:AGENTBELL_UPDATE_BACKUP
$log = $env:AGENTBELL_UPDATE_LOG
$pidToWait = 0
[void][int]::TryParse($env:AGENTBELL_UPDATE_PID, [ref]$pidToWait)
if ($pidToWait -gt 0) {
    try { Wait-Process -Id $pidToWait -Timeout 60 -ErrorAction SilentlyContinue } catch { }
}
Start-Sleep -Milliseconds 500
try {
    if (Test-Path -LiteralPath $target) {
        Copy-Item -LiteralPath $target -Destination $backup -Force
    }
    $copied = $false
    for ($i = 0; $i -lt 20 -and -not $copied; $i++) {
        try {
            Copy-Item -LiteralPath $source -Destination $target -Force -ErrorAction Stop
            $copied = $true
        } catch {
            Start-Sleep -Milliseconds 500
        }
    }
    if (-not $copied) { throw "Could not replace AgentBell.exe; the file may still be in use." }
    $restartArgs = @()
    if (-not [string]::IsNullOrEmpty($env:AGENTBELL_UPDATE_ARGS_JSON)) {
        $parsed = ConvertFrom-Json -InputObject $env:AGENTBELL_UPDATE_ARGS_JSON
        if ($null -ne $parsed) { $restartArgs = @($parsed) }
    }
    if (-not [string]::IsNullOrEmpty($env:AGENTBELL_UPDATE_CWD) -and
        (Test-Path -LiteralPath $env:AGENTBELL_UPDATE_CWD)) {
        Set-Location -LiteralPath $env:AGENTBELL_UPDATE_CWD
    }
    & $target @restartArgs
} catch {
    if (Test-Path -LiteralPath $backup) {
        Copy-Item -LiteralPath $backup -Destination $target -Force
    }
    if (-not [string]::IsNullOrEmpty($log)) {
        "$(Get-Date -Format o) update failed: $($_.Exception.Message)" |
            Out-File -LiteralPath $log -Append -Encoding utf8
    }
    Start-Process -FilePath $target
}
"""


class UpdateError(RuntimeError):
    """Raised when a release cannot be checked, downloaded or installed."""


@dataclass(frozen=True, slots=True)
class ReleaseAsset:
    name: str
    url: str
    size: int = 0
    digest: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    version: str
    tag: str = ""
    html_url: str = ""
    notes: str = ""
    asset: ReleaseAsset | None = None


@dataclass(frozen=True, slots=True)
class UpdateCheck:
    status: str
    message: str
    current: str = __version__
    repo: str = ""
    release: ReleaseInfo | None = None

    @property
    def available(self) -> bool:
        return self.status == "available" and self.release is not None

    @property
    def can_install(self) -> bool:
        return bool(self.release and self.release.asset)


@dataclass(frozen=True, slots=True)
class InstallResult:
    ok: bool
    message: str


def normalize_repo(value: str) -> str:
    text = (value or "").strip().rstrip("/")
    if not text:
        return ""
    lowered = text.lower()
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    if text.lower().endswith(".git"):
        text = text[:-4]
    parts = text.split("/")
    if len(parts) != 2:
        return ""
    owner, name = parts
    if not _REPO_PART.fullmatch(owner) or not _REPO_PART.fullmatch(name):
        return ""
    return f"{owner}/{name}"


def version_key(value: str) -> tuple[int, int, int, int]:
    match = _VERSION_CORE.match((value or "").strip())
    if not match:
        return (0, 0, 0, 0)
    major = int(match.group(1) or 0)
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    prerelease = "-" in (value or "").strip().lower()
    return (major, minor, patch, 0 if prerelease else 1)


def is_newer(remote: str, current: str) -> bool:
    return version_key(remote) > version_key(current)


def is_allowed_download_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme == "https" and parts.hostname in ALLOWED_DOWNLOAD_HOSTS


def _read_limited(response, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise UpdateError("Release 信息超过大小上限")
        chunks.append(chunk)
    return b"".join(chunks)


def _request(url: str, headers: Mapping[str, str] | None = None):
    merged = {
        "User-Agent": f"AgentBell/{__version__}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if headers:
        merged.update(headers)
    return urllib.request.Request(url, headers=merged)


def host_platform(platform_name: str | None = None) -> str:
    if platform_name:
        return platform_name
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def linux_arch(machine: str = "") -> str:
    text = (machine or _platform.machine()).strip().lower()
    if text in {"aarch64", "arm64"}:
        return "arm64"
    return "x64"


def asset_label(
    platform_name: str | None = None, machine: str = ""
) -> str:
    if host_platform(platform_name) == "linux":
        return f"AgentBell-linux-{linux_arch(machine)}.tar.gz"
    return "AgentBell.exe"


def select_asset(
    assets: Sequence[ReleaseAsset],
    *,
    platform_name: str | None = None,
    machine: str = "",
) -> ReleaseAsset | None:
    if host_platform(platform_name) == "linux":
        arch = linux_arch(machine)
        candidates = [
            asset
            for asset in assets
            if asset.name.lower().endswith(".tar.gz")
            and "agentbell" in asset.name.lower()
            and f"linux-{arch}" in asset.name.lower()
        ]
        exact = [
            asset
            for asset in candidates
            if asset.name.lower() == f"agentbell-linux-{arch}.tar.gz"
        ]
        if exact:
            return exact[0]
        return candidates[0] if candidates else None
    candidates = [
        asset
        for asset in assets
        if asset.name.lower().endswith(".exe")
        and "agentbell" in asset.name.lower()
    ]
    exact = [
        asset for asset in candidates if asset.name.lower() == "agentbell.exe"
    ]
    if exact:
        return exact[0]
    return candidates[0] if candidates else None


def fetch_latest_release(
    repo: str,
    *,
    timeout: float = 8.0,
    opener: Callable[..., object] = urllib.request.urlopen,
    platform_name: str | None = None,
    machine: str = "",
) -> ReleaseInfo:
    normalized = normalize_repo(repo)
    if not normalized:
        raise UpdateError("更新仓库未配置，格式为 owner/repo")
    url = f"{API_ROOT}/repos/{normalized}/releases/latest"
    try:
        with opener(_request(url), timeout=timeout) as response:
            payload = _read_limited(response, RELEASE_BYTES_LIMIT)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(
                f"找不到 {normalized} 的 Release，请检查仓库名或是否已发布"
            ) from exc
        if exc.code in (403, 429):
            raise UpdateError("GitHub 接口访问受限，请稍后再试") from exc
        raise UpdateError(f"GitHub 返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"无法连接 GitHub：{exc}") from exc

    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError("Release 数据格式无效") from exc
    if not isinstance(data, dict):
        raise UpdateError("Release 数据格式无效")

    tag = str(data.get("tag_name") or "").strip()[:80]
    if not tag:
        raise UpdateError("Release 缺少版本号")
    html_url = str(data.get("html_url") or "").strip()
    try:
        html_host = urlsplit(html_url).hostname
    except ValueError:
        html_host = ""
    if html_host != "github.com":
        html_url = f"https://github.com/{normalized}/releases/latest"
    notes = " ".join(str(data.get("body") or "").split())[:2000]

    assets: list[ReleaseAsset] = []
    raw_assets = data.get("assets")
    if isinstance(raw_assets, list):
        for item in raw_assets:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()[:120]
            asset_url = str(item.get("browser_download_url") or "").strip()
            if not name or not asset_url:
                continue
            size = item.get("size")
            digest = str(item.get("digest") or "").strip()[:100]
            assets.append(
                ReleaseAsset(
                    name=name,
                    url=asset_url,
                    size=size if isinstance(size, int) and size > 0 else 0,
                    digest=digest,
                )
            )

    return ReleaseInfo(
        version=tag.lstrip("vV") or tag,
        tag=tag,
        html_url=html_url,
        notes=notes,
        asset=select_asset(assets, platform_name=platform_name, machine=machine),
    )


def check_for_update(
    repo: str,
    current: str = __version__,
    *,
    fetch: Callable[[str], ReleaseInfo] = fetch_latest_release,
    platform_name: str | None = None,
    machine: str = "",
) -> UpdateCheck:
    normalized = normalize_repo(repo)
    if not normalized:
        return UpdateCheck(
            "disabled",
            "未配置更新仓库：在偏好设置的「程序更新」里填写 GitHub 仓库 owner/repo",
            current,
        )
    try:
        release = fetch(normalized)
    except UpdateError as exc:
        return UpdateCheck("error", str(exc), current, normalized)
    if not is_newer(release.version, current):
        return UpdateCheck(
            "up_to_date", f"已是最新版本 {current}", current, normalized, release
        )
    suffix = (
        ""
        if release.asset
        else f"；该 Release 没有 {asset_label(platform_name, machine)}"
    )
    return UpdateCheck(
        "available",
        f"发现新版本 {release.version}{suffix}",
        current,
        normalized,
        release,
    )


def download_release_asset(
    release: ReleaseInfo,
    *,
    dest_dir: Path | None = None,
    opener: Callable[..., object] = urllib.request.urlopen,
    timeout: float = 30.0,
    max_bytes: int = DOWNLOAD_BYTES_LIMIT,
) -> Path:
    asset = release.asset
    if asset is None:
        raise UpdateError(f"该 Release 没有可下载的 {asset_label()}")
    if not is_allowed_download_url(asset.url):
        raise UpdateError("下载地址不在允许的 GitHub 域名内")
    if asset.size and asset.size > max_bytes:
        raise UpdateError("安装包超过大小上限")
    safe_version = re.sub(r"[^A-Za-z0-9_.-]", "_", release.version)[:40] or "new"
    directory = Path(dest_dir) if dest_dir is not None else updates_dir()
    directory.mkdir(parents=True, exist_ok=True)
    lower_name = asset.name.lower()
    if lower_name.endswith(".tar.gz"):
        extension = ".tar.gz"
    elif lower_name.endswith(".tar.xz"):
        extension = ".tar.xz"
    elif lower_name.endswith(".exe"):
        extension = ".exe"
    else:
        raise UpdateError("该 Release 的安装包格式不受支持")
    arch = ""
    match = re.search(r"(linux-(?:x64|arm64))", lower_name)
    if match:
        arch = f"-{match.group(1)}"
    target = directory / f"AgentBell-{safe_version}{arch}{extension}"
    part = target.with_name(target.name + ".part")

    digest = hashlib.sha256()
    written = 0
    try:
        with opener(
            _request(asset.url, {"Accept": "application/octet-stream"}),
            timeout=timeout,
        ) as response:
            final_url = ""
            geturl = getattr(response, "geturl", None)
            if callable(geturl):
                final_url = str(geturl() or "")
            if final_url and not is_allowed_download_url(final_url):
                raise UpdateError("下载被重定向到非 GitHub 域名，已中止")
            with part.open("wb") as handle:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > max_bytes:
                        raise UpdateError("安装包超过大小上限")
                    digest.update(chunk)
                    handle.write(chunk)
        if written == 0:
            raise UpdateError("下载内容为空")
        if asset.size and written != asset.size:
            raise UpdateError("下载大小与 Release 记录不一致")
        expected = asset.digest.lower().strip()
        if expected.startswith("sha256:") and digest.hexdigest() != expected[7:].strip():
            raise UpdateError("安装包 SHA-256 校验失败")
        os.replace(part, target)
        return target
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"下载失败：HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"下载失败：{exc}") from exc
    finally:
        if part.exists():
            try:
                part.unlink()
            except OSError:
                pass


def _powershell_path(env: Mapping[str, str]) -> str:
    system_root = env.get("SystemRoot", r"C:\Windows")
    candidate = (
        Path(system_root)
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if candidate.is_file():
        return str(candidate)
    return shutil.which("powershell", path=env.get("PATH", "")) or ""


def _install_windows_update(
    source: Path,
    *,
    pid: int | None,
    args: Sequence[str],
    executable: str | None,
    script_dir: Path | None,
    working_dir: str | None,
    env: Mapping[str, str] | None,
    popen: Callable[..., object],
) -> InstallResult:
    if source.suffix.lower() != ".exe":
        return InstallResult(False, "安装包不是 .exe 文件")
    target = Path(executable or sys.executable).resolve()
    if source == target:
        return InstallResult(False, "安装包与当前程序是同一个文件")

    environment = dict(os.environ if env is None else env)
    powershell = _powershell_path(environment)
    if not powershell:
        return InstallResult(False, "未找到 PowerShell，无法完成替换")

    directory = Path(script_dir) if script_dir is not None else updates_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        script_path = directory / "apply_update.ps1"
        script_path.write_text(REPLACE_SCRIPT, encoding="utf-8")
    except OSError as exc:
        return InstallResult(False, f"无法写入更新脚本：{exc}")

    environment.update(
        {
            "AGENTBELL_UPDATE_PID": str(pid if pid is not None else os.getpid()),
            "AGENTBELL_UPDATE_SOURCE": str(source),
            "AGENTBELL_UPDATE_TARGET": str(target),
            "AGENTBELL_UPDATE_BACKUP": str(
                target.with_name(target.name + ".bak")
            ),
            "AGENTBELL_UPDATE_ARGS_JSON": json.dumps(
                [str(item) for item in args], ensure_ascii=False
            ),
            "AGENTBELL_UPDATE_CWD": str(
                working_dir if working_dir is not None else os.getcwd()
            ),
            "AGENTBELL_UPDATE_LOG": str(directory / "update.log"),
        }
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    try:
        popen(
            [
                powershell,
                "-NoLogo",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(script_path),
            ],
            cwd=str(directory),
            env=environment,
            close_fds=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        return InstallResult(False, f"无法启动更新脚本：{exc}")
    return InstallResult(True, "更新脚本已启动，程序将退出并重启")


def _extract_linux_binary(archive: Path, destination: Path) -> Path:
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            candidates = [
                member
                for member in bundle.getmembers()
                if member.isfile() and PurePosixPath(member.name).name == "AgentBell"
            ]
            if len(candidates) != 1:
                raise UpdateError("安装包结构异常：应包含唯一的 AgentBell 可执行文件")
            member = candidates[0]
            if member.size <= 0 or member.size > DOWNLOAD_BYTES_LIMIT:
                raise UpdateError("安装包大小异常")
            source = bundle.extractfile(member)
            if source is None:
                raise UpdateError("无法读取安装包中的 AgentBell")
            destination.mkdir(parents=True, exist_ok=True)
            target = destination / "AgentBell"
            with source, target.open("wb") as handle:
                shutil.copyfileobj(source, handle, CHUNK_SIZE)
    except tarfile.TarError as exc:
        raise UpdateError("安装包不是有效的 tar.gz 文件") from exc
    target.chmod(0o755)
    return target


def linux_install_blocker(
    executable: str | Path, env: Mapping[str, str] | None = None
) -> str:
    environment = os.environ if env is None else env
    if environment.get("APPIMAGE"):
        return "AppImage 版本不支持原地更新，请下载新的 AppImage 替换当前文件"
    target = Path(executable).resolve()
    if not target.exists():
        return ""
    if not os.access(target, os.W_OK) or not os.access(target.parent, os.W_OK):
        return "当前安装由系统包管理器管理，请使用 apt 或 dnf 更新"
    return ""


def _install_linux_update(
    source: Path,
    *,
    pid: int | None,
    args: Sequence[str],
    executable: str | None,
    script_dir: Path | None,
    working_dir: str | None,
    env: Mapping[str, str] | None,
    popen: Callable[..., object],
    version: str,
) -> InstallResult:
    if not source.name.lower().endswith(".tar.gz"):
        return InstallResult(False, "安装包不是 Linux 的 tar.gz 文件")
    target = Path(executable or sys.executable).resolve()
    environment = dict(os.environ if env is None else env)
    blocked = linux_install_blocker(target, environment)
    if blocked:
        return InstallResult(False, blocked)
    directory = Path(script_dir) if script_dir is not None else updates_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        binary = _extract_linux_binary(source, directory / f"staged-{version}")
    except (OSError, UpdateError) as exc:
        return InstallResult(False, f"无法解压安装包：{exc}")
    if binary == target:
        return InstallResult(False, "安装包与当前程序是同一个文件")

    environment.update(
        {
            "AGENTBELL_UPDATE_PID": str(pid if pid is not None else os.getpid()),
            "AGENTBELL_UPDATE_SOURCE": str(binary),
            "AGENTBELL_UPDATE_TARGET": str(target),
            "AGENTBELL_UPDATE_BACKUP": str(target.with_name(target.name + ".bak")),
            "AGENTBELL_UPDATE_CWD": str(
                working_dir if working_dir is not None else os.getcwd()
            ),
            "AGENTBELL_UPDATE_LOG": str(directory / "update.log"),
            "AGENTBELL_UPDATE_VERSION": version,
        }
    )
    restart = "exec " + shlex.join(
        [str(target), *(str(item) for item in args)]
    )
    script = LINUX_REPLACE_SCRIPT.replace("@@RESTART@@", restart)
    try:
        script_path = directory / "apply_update.sh"
        script_path.write_text(script, encoding="utf-8")
        script_path.chmod(0o755)
    except OSError as exc:
        return InstallResult(False, f"无法写入更新脚本：{exc}")
    try:
        popen(
            ["/bin/sh", str(script_path)],
            cwd=str(directory),
            env=environment,
            close_fds=True,
            start_new_session=True,
        )
    except OSError as exc:
        return InstallResult(False, f"无法启动更新脚本：{exc}")
    return InstallResult(True, "更新脚本已启动，程序将退出并重启")


def install_update(
    downloaded: Path,
    *,
    pid: int | None = None,
    args: Sequence[str] = (),
    frozen: bool | None = None,
    executable: str | None = None,
    script_dir: Path | None = None,
    working_dir: str | None = None,
    env: Mapping[str, str] | None = None,
    popen: Callable[..., object] = subprocess.Popen,
    platform_name: str | None = None,
    version: str = "",
) -> InstallResult:
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not is_frozen:
        return InstallResult(
            False, "源码模式不会自动替换程序，请手动运行新版本"
        )
    source = Path(downloaded).resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        return InstallResult(False, "安装包不存在或为空")
    target_platform = host_platform(platform_name)
    if target_platform == "linux":
        safe_version = (
            re.sub(r"[^A-Za-z0-9_.-]", "_", version)[:40] or "new"
        )
        return _install_linux_update(
            source,
            pid=pid,
            args=args,
            executable=executable,
            script_dir=script_dir,
            working_dir=working_dir,
            env=env,
            popen=popen,
            version=safe_version,
        )
    return _install_windows_update(
        source,
        pid=pid,
        args=args,
        executable=executable,
        script_dir=script_dir,
        working_dir=working_dir,
        env=env,
        popen=popen,
    )
