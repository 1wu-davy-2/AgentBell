from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import zipfile
from pathlib import Path

import pytest

from agentbell import toolchain as tc
from agentbell.config import ConfigError, config_from_dict


class FakeResponse:
    def __init__(self, payload: bytes, headers: dict[str, str] | None = None) -> None:
        self._buffer = io.BytesIO(payload)
        self.headers = headers or {}

    def read(self, size: int = -1) -> bytes:
        return self._buffer.read(size)

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


class FakeOpener:
    def __init__(self, routes: dict[str, tuple[bytes, dict[str, str]]]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def open(self, request, timeout=None):  # noqa: ANN001
        url = request.full_url
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected download: {url}")
        payload, headers = self.routes[url]
        return FakeResponse(payload, headers)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def _node_routes(version: str = "v26.13.0") -> tuple[dict, bytes]:
    arch = tc._windows_arch()
    folder = f"node-{version}-{arch}"
    archive = _zip_bytes({f"{folder}/node.exe": b"MZ", f"{folder}/npm.cmd": b"@echo off"})
    digest = hashlib.sha256(archive).hexdigest()
    filename = f"{folder}.zip"
    index = json.dumps(
        [
            {"version": "v27.0.0-nightly", "lts": False},
            {"version": version, "lts": "Lithium", "date": "2026-10-28"},
        ]
    ).encode("utf-8")
    routes = {
        tc.NODE_INDEX_URL: (index, {}),
        f"{tc.NODE_DIST_ROOT}/{version}/{filename}": (archive, {}),
        f"{tc.NODE_DIST_ROOT}/{version}/SHASUMS256.txt": (
            f"{'0' * 64}  other.zip\n{digest}  {filename}\n".encode("utf-8"),
            {},
        ),
    }
    return routes, archive


def test_validate_registry_rejects_plain_http():
    assert tc.validate_registry("") == tc.NPM_REGISTRY_OFFICIAL
    assert tc.validate_registry("https://registry.npmmirror.com/") == (
        "https://registry.npmmirror.com"
    )
    with pytest.raises(tc.ToolchainError):
        tc.validate_registry("http://registry.npmjs.org")
    with pytest.raises(tc.ToolchainError):
        tc.validate_registry("https://evil.example.com")


def test_safe_extract_rejects_traversal(tmp_path: Path):
    archive = tmp_path / "evil.zip"
    archive.write_bytes(_zip_bytes({"../escape.txt": b"x"}))
    with pytest.raises(tc.ToolchainError):
        tc.safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_writes_regular_tree(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    archive.write_bytes(_zip_bytes({"pkg/a.txt": b"a", "pkg/sub/b.txt": b"b"}))
    target = tmp_path / "out"
    tc.safe_extract_zip(archive, target)
    assert (target / "pkg" / "sub" / "b.txt").read_bytes() == b"b"


def test_parse_shasums_matches_exact_file():
    text = f"{'a' * 64}  other.zip\n{'B' * 64}  node-v26.13.0-win-x64.zip\n"
    assert tc._parse_shasums(text, "node-v26.13.0-win-x64.zip") == "b" * 64
    assert tc._parse_shasums(text, "missing.zip") == ""


def test_resolve_node_release_prefers_lts(tmp_path: Path):
    routes, _ = _node_routes()
    service = tc.ToolchainService(
        tmp_path / "runtime", opener=FakeOpener(routes), registry=tc.NPM_REGISTRY_OFFICIAL
    )
    version, zip_url, shasums_url = service.resolve_node_release()
    assert version == "v26.13.0"
    assert zip_url.endswith(f"node-v26.13.0-{tc._windows_arch()}.zip")
    assert shasums_url.endswith("/SHASUMS256.txt")


@pytest.mark.skipif(os.name != "nt", reason="portable Node install is Windows-only")
def test_install_node_verifies_and_extracts(tmp_path: Path):
    routes, archive = _node_routes()
    service = tc.ToolchainService(
        tmp_path / "runtime", opener=FakeOpener(routes), registry=tc.NPM_REGISTRY_OFFICIAL
    )
    events: list[tc.Progress] = []
    version = service.install_node(events.append)
    assert version == "v26.13.0"
    assert service.node_exe.exists()
    assert service.node_version() == "v26.13.0"
    manifest = service.manifest()
    assert manifest["node"]["runtime"]["archive_sha256"] == hashlib.sha256(archive).hexdigest()
    assert events and events[-1].percent == 100


@pytest.mark.skipif(os.name != "nt", reason="portable Node install is Windows-only")
def test_install_node_rejects_bad_checksum(tmp_path: Path):
    routes, _ = _node_routes()
    arch = tc._windows_arch()
    filename = f"node-v26.13.0-{arch}.zip"
    routes[f"{tc.NODE_DIST_ROOT}/v26.13.0/SHASUMS256.txt"] = (
        f"{'f' * 64}  {filename}\n".encode("utf-8"),
        {},
    )
    service = tc.ToolchainService(
        tmp_path / "runtime", opener=FakeOpener(routes), registry=tc.NPM_REGISTRY_OFFICIAL
    )
    if os.name != "nt":
        pytest.skip("portable Node install is Windows-only")
    with pytest.raises(tc.ToolchainError):
        service.install_node()


def _fake_node(service: tc.ToolchainService) -> None:
    service.node_exe.parent.mkdir(parents=True, exist_ok=True)
    service.node_exe.write_bytes(b"MZ")
    service.npm_cli.parent.mkdir(parents=True, exist_ok=True)
    service.npm_cli.write_text("// npm", encoding="utf-8")
    service._record("node", "runtime", {"version": "v26.13.0"})


_KNOWN_PACKAGES = {spec.package for spec in tc.NPM_TOOLS}


def _fake_runner(recorded: list[list[str]]):
    def run(command, **kwargs):  # noqa: ANN001
        recorded.append(list(command))
        if "install" in command:
            packages = [item for item in command if item in _KNOWN_PACKAGES]
            if packages:
                name = packages[0]
                target = Path(kwargs["cwd"]) / "agents" / "node_modules" / name
                target.mkdir(parents=True, exist_ok=True)
                (target / "package.json").write_text(
                    json.dumps({"name": name, "version": "9.9.9"}), encoding="utf-8"
                )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    return run


def test_install_tool_uses_local_prefix_and_records_version(tmp_path: Path):
    service = tc.ToolchainService(
        tmp_path / "runtime",
        opener=FakeOpener({}),
        registry=tc.NPM_REGISTRY_MIRROR,
        runner=_fake_runner([]),
    )
    _fake_node(service)
    version = service.install_tool("codex")
    assert version == "9.9.9"
    package_json = (
        service.agents_dir / "node_modules" / "@openai" / "codex" / "package.json"
    )
    assert package_json.exists()
    assert service.state().tools[1].version == "9.9.9"
    assert service.manifest()["tools"]["codex"]["registry"] == tc.NPM_REGISTRY_MIRROR


def test_install_tool_builds_args_without_shell(tmp_path: Path):
    recorded: list[list[str]] = []
    service = tc.ToolchainService(
        tmp_path / "runtime",
        opener=FakeOpener({}),
        registry=tc.NPM_REGISTRY_MIRROR,
        runner=_fake_runner(recorded),
    )
    _fake_node(service)
    service.install_tool("claude-code")
    command = recorded[0]
    assert command[0].endswith("node.exe")
    assert command[1].endswith("npm-cli.js")
    assert "install" in command and "-g" in command
    assert "@anthropic-ai/claude-code" in command
    assert f"--prefix={service.agents_dir}" not in command
    assert str(service.agents_dir) in command
    assert tc.NPM_REGISTRY_MIRROR in command


def test_uninstall_removes_package_and_manifest(tmp_path: Path):
    service = tc.ToolchainService(
        tmp_path / "runtime",
        opener=FakeOpener({}),
        registry=tc.NPM_REGISTRY_OFFICIAL,
        runner=_fake_runner([]),
    )
    _fake_node(service)
    service.install_tool("pi")
    assert service.tool_version("pi") == "9.9.9"
    service.uninstall("pi")
    assert service.tool_version("pi") == ""
    assert "pi" not in service.manifest().get("tools", {})


def test_state_lists_node_and_seven_npm_tools(tmp_path: Path):
    service = tc.ToolchainService(
        tmp_path / "runtime",
        opener=FakeOpener({}),
        registry=tc.NPM_REGISTRY_OFFICIAL,
    )
    state = service.state()
    assert state.node.installed is False
    assert [tool.id for tool in state.tools] == [spec.id for spec in tc.NPM_TOOLS]
    assert len(state.tools) == 7
    assert not hasattr(state, "cc_switch")


def test_download_allowlist_rejects_github_hosts():
    with pytest.raises(tc.ToolchainError):
        tc._check_url("https://api.github.com/repos/farion1231/cc-switch")
    with pytest.raises(tc.ToolchainError):
        tc._check_url("https://github.com/farion1231/cc-switch/releases")


def test_protect_and_reveal_secret_roundtrip():
    protected = tc.protect_secret("sk-test-123")
    assert protected and "sk-test-123" not in protected
    assert tc.reveal_secret(protected) == "sk-test-123"
    assert tc.protect_secret("") == ""
    assert tc.reveal_secret("") == ""


def test_deepseek_env_only_when_key_present():
    assert tc.deepseek_claude_env("") == {}
    env = tc.deepseek_claude_env("sk-1")
    assert env["ANTHROPIC_BASE_URL"] == "https://api.deepseek.com/anthropic"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "sk-1"
    assert env["ANTHROPIC_MODEL"] == "deepseek-chat"


def test_runtime_env_prepends_portable_dirs(tmp_path: Path):
    env = tc.runtime_env(tmp_path / "runtime", base={"PATH": "C:/Windows"})
    parts = env["PATH"].split(os.pathsep)
    assert parts[0].endswith("agents")
    assert parts[1].endswith("node")
    assert parts[-1] == "C:/Windows"
    assert env["AGENTBELL_RUNTIME"].endswith("runtime")


def test_config_accepts_toolchain_section():
    config = config_from_dict(
        {
            "toolchain": {
                "npm_registry": tc.NPM_REGISTRY_MIRROR,
                "deepseek_key": "dpapi:abc",
            }
        }
    )
    assert config.toolchain.npm_registry == tc.NPM_REGISTRY_MIRROR
    assert config.toolchain.deepseek_key == "dpapi:abc"


def test_config_rejects_insecure_registry():
    with pytest.raises(ConfigError):
        config_from_dict({"toolchain": {"npm_registry": "http://registry.npmjs.org"}})
