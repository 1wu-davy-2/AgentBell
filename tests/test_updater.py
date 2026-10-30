from __future__ import annotations

import hashlib
import json
import os
import urllib.error

import pytest

from agentbell import __version__
from agentbell.updater import (
    API_ROOT,
    REPLACE_SCRIPT,
    ReleaseAsset,
    ReleaseInfo,
    UpdateError,
    check_for_update,
    download_release_asset,
    fetch_latest_release,
    install_update,
    is_allowed_download_url,
    is_newer,
    normalize_repo,
    select_asset,
    version_key,
)


class FakeResponse:
    def __init__(self, payload: bytes, final_url: str = "") -> None:
        self._payload = payload
        self._offset = 0
        self._final_url = final_url

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class FakeOpener:
    def __init__(self, results) -> None:
        self._results = list(results)
        self.calls = []

    def __call__(self, request, timeout=None):
        self.calls.append((request, timeout))
        result = self._results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_normalize_repo_accepts_urls_and_rejects_junk():
    assert normalize_repo("acme/AgentBell") == "acme/AgentBell"
    assert (
        normalize_repo("https://github.com/acme/AgentBell.git")
        == "acme/AgentBell"
    )
    assert normalize_repo("github.com/acme/AgentBell/") == "acme/AgentBell"
    assert normalize_repo("") == ""
    assert normalize_repo("acme") == ""
    assert normalize_repo("acme/agent bell") == ""
    assert normalize_repo("https://gitlab.com/acme/AgentBell") == ""


def test_version_comparison_handles_v_prefix_and_prerelease():
    assert version_key("v2.8.0") == (2, 8, 0, 1)
    assert version_key("2.8") == (2, 8, 0, 1)
    assert version_key("2.8.0-beta.1") == (2, 8, 0, 0)
    assert is_newer("2.8.1", "2.8.0")
    assert is_newer("2.8.0", "2.7.9")
    assert not is_newer("2.8.0", "2.8.0")
    assert not is_newer("2.8.0-beta", "2.8.0")


def test_select_asset_prefers_stable_name_and_falls_back():
    stable = ReleaseAsset("AgentBell.exe", "https://github.com/a/b/x.exe")
    versioned = ReleaseAsset(
        "AgentBell-2.8.0.exe", "https://github.com/a/b/y.exe"
    )
    other = ReleaseAsset("notes.txt", "https://github.com/a/b/n.txt")
    assert select_asset([versioned, stable, other]) is stable
    assert select_asset([versioned, other]) is versioned
    assert select_asset([other]) is None


def test_check_for_update_is_disabled_without_repo():
    def fetch(repo):  # pragma: no cover - must not be called
        raise AssertionError("network should not be used")

    result = check_for_update("", "2.8.0", fetch=fetch)
    assert result.status == "disabled"
    assert result.available is False


def test_check_for_update_reports_up_to_date_and_available():
    current = "2.8.0"
    up_to_date = check_for_update(
        "acme/AgentBell",
        current,
        fetch=lambda repo: ReleaseInfo(version="2.8.0"),
    )
    assert up_to_date.status == "up_to_date"
    assert up_to_date.message == f"已是最新版本 {current}"

    asset = ReleaseAsset("AgentBell.exe", "https://github.com/a/b/x.exe")
    newer = check_for_update(
        "acme/AgentBell",
        current,
        fetch=lambda repo: ReleaseInfo(version="2.9.0", asset=asset),
    )
    assert newer.status == "available"
    assert newer.available is True
    assert newer.can_install is True
    assert "2.9.0" in newer.message

    without_asset = check_for_update(
        "acme/AgentBell",
        current,
        fetch=lambda repo: ReleaseInfo(version="2.9.0"),
    )
    assert without_asset.available is True
    assert without_asset.can_install is False
    assert "AgentBell.exe" in without_asset.message


def test_check_for_update_surfaces_fetch_errors():
    def fetch(repo):
        raise UpdateError("boom")

    result = check_for_update("acme/AgentBell", "2.8.0", fetch=fetch)
    assert result.status == "error"
    assert result.message == "boom"


def test_fetch_latest_release_parses_github_payload():
    payload = json.dumps(
        {
            "tag_name": "v9.9.9",
            "html_url": "https://github.com/acme/AgentBell/releases/tag/v9.9.9",
            "body": "修复\n  - 一个问题",
            "assets": [
                {
                    "name": "AgentBell-9.9.9.exe",
                    "browser_download_url": "https://github.com/acme/AgentBell/releases/download/v9.9.9/AgentBell-9.9.9.exe",
                    "size": 10,
                },
                {
                    "name": "AgentBell.exe",
                    "browser_download_url": "https://github.com/acme/AgentBell/releases/download/v9.9.9/AgentBell.exe",
                    "size": 12,
                    "digest": "sha256:" + "a" * 64,
                },
            ],
        }
    ).encode("utf-8")
    opener = FakeOpener([FakeResponse(payload, "https://api.github.com/x")])

    release = fetch_latest_release(
        "https://github.com/acme/AgentBell", opener=opener
    )

    assert release.version == "9.9.9"
    assert release.tag == "v9.9.9"
    assert release.asset is not None
    assert release.asset.name == "AgentBell.exe"
    assert release.asset.size == 12
    assert release.asset.digest == "sha256:" + "a" * 64
    assert release.notes == "修复 - 一个问题"
    request, _ = opener.calls[0]
    assert request.full_url == f"{API_ROOT}/repos/acme/AgentBell/releases/latest"
    assert request.headers.get("User-agent") == f"AgentBell/{__version__}"


def test_fetch_latest_release_maps_404_to_readable_error():
    error = urllib.error.HTTPError(
        "https://api.github.com/x", 404, "Not Found", None, None
    )
    opener = FakeOpener([error])
    with pytest.raises(UpdateError, match="Release"):
        fetch_latest_release("acme/AgentBell", opener=opener)


def test_download_url_allowlist():
    assert is_allowed_download_url(
        "https://github.com/a/b/releases/download/v1/AgentBell.exe"
    )
    assert is_allowed_download_url(
        "https://objects.githubusercontent.com/x"
    )
    assert is_allowed_download_url(
        "https://release-assets.githubusercontent.com/x"
    )
    assert not is_allowed_download_url("http://github.com/a/b/x.exe")
    assert not is_allowed_download_url("https://evil.example/x.exe")
    assert not is_allowed_download_url("https://github.com.evil.example/x.exe")


def test_download_verifies_size_and_digest(tmp_path):
    content = b"MZ fake executable"
    asset = ReleaseAsset(
        "AgentBell.exe",
        "https://github.com/acme/AgentBell/releases/download/v9/AgentBell.exe",
        size=len(content),
        digest="sha256:" + hashlib.sha256(content).hexdigest(),
    )
    opener = FakeOpener([FakeResponse(content)])

    target = download_release_asset(
        ReleaseInfo(version="9.9.9", asset=asset),
        dest_dir=tmp_path,
        opener=opener,
    )

    assert target == tmp_path / "AgentBell-9.9.9.exe"
    assert target.read_bytes() == content
    assert not target.with_name(target.name + ".part").exists()


def test_download_rejects_digest_mismatch_and_cleans_part(tmp_path):
    content = b"MZ fake executable"
    asset = ReleaseAsset(
        "AgentBell.exe",
        "https://github.com/acme/AgentBell/releases/download/v9/AgentBell.exe",
        size=len(content),
        digest="sha256:" + "0" * 64,
    )
    with pytest.raises(UpdateError, match="SHA-256"):
        download_release_asset(
            ReleaseInfo(version="9.9.9", asset=asset),
            dest_dir=tmp_path,
            opener=FakeOpener([FakeResponse(content)]),
        )
    assert list(tmp_path.iterdir()) == []


def test_download_rejects_foreign_host_before_network(tmp_path):
    asset = ReleaseAsset(
        "AgentBell.exe", "https://evil.example/AgentBell.exe", size=1
    )
    opener = FakeOpener([])
    with pytest.raises(UpdateError, match="域名"):
        download_release_asset(
            ReleaseInfo(version="9.9.9", asset=asset),
            dest_dir=tmp_path,
            opener=opener,
        )
    assert opener.calls == []


def test_download_rejects_size_mismatch(tmp_path):
    content = b"MZ"
    asset = ReleaseAsset(
        "AgentBell.exe",
        "https://github.com/acme/AgentBell/releases/download/v9/AgentBell.exe",
        size=len(content) + 4,
    )
    with pytest.raises(UpdateError, match="大小"):
        download_release_asset(
            ReleaseInfo(version="9.9.9", asset=asset),
            dest_dir=tmp_path,
            opener=FakeOpener([FakeResponse(content)]),
        )
    assert list(tmp_path.iterdir()) == []


def test_install_update_requires_frozen_mode(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"MZ")
    calls = []
    result = install_update(
        source,
        frozen=False,
        executable=str(tmp_path / "AgentBell.exe"),
        script_dir=tmp_path / "updates",
        popen=lambda *args, **kwargs: calls.append(args),
    )
    assert result.ok is False
    assert "源码模式" in result.message
    assert calls == []


def test_install_update_schedules_static_script_for_frozen_app(tmp_path):
    source = tmp_path / "new.exe"
    source.write_bytes(b"MZ new")
    target = tmp_path / "AgentBell.exe"
    target.write_bytes(b"MZ old")
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))
        return object()

    result = install_update(
        source,
        pid=4321,
        args=["--config", str(tmp_path / "config.json")],
        frozen=True,
        executable=str(target),
        script_dir=tmp_path / "updates",
        popen=fake_popen,
    )

    assert result.ok is True
    script_path = tmp_path / "updates" / "apply_update.ps1"
    assert script_path.read_text(encoding="utf-8") == REPLACE_SCRIPT
    assert str(source) not in REPLACE_SCRIPT
    assert str(target) not in REPLACE_SCRIPT
    args, kwargs = calls[0]
    assert "-File" in args
    assert str(script_path) in args
    env = kwargs["env"]
    assert env["AGENTBELL_UPDATE_PID"] == "4321"
    assert env["AGENTBELL_UPDATE_SOURCE"] == str(source)
    assert env["AGENTBELL_UPDATE_TARGET"] == str(target)
    assert json.loads(env["AGENTBELL_UPDATE_ARGS_JSON"]) == [
        "--config",
        str(tmp_path / "config.json"),
    ]
    assert env["AGENTBELL_UPDATE_CWD"] == os.getcwd()
    assert "AGENTBELL_UPDATE_CWD" in REPLACE_SCRIPT
    assert kwargs["creationflags"]
    assert kwargs["close_fds"] is True


def test_install_update_rejects_missing_or_empty_file(tmp_path):
    result = install_update(
        tmp_path / "missing.exe",
        frozen=True,
        executable=str(tmp_path / "AgentBell.exe"),
        script_dir=tmp_path / "updates",
    )
    assert result.ok is False
    assert "不存在" in result.message

    empty = tmp_path / "empty.exe"
    empty.write_bytes(b"")
    result = install_update(
        empty,
        frozen=True,
        executable=str(tmp_path / "AgentBell.exe"),
        script_dir=tmp_path / "updates",
    )
    assert result.ok is False
