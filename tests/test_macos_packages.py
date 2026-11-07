from __future__ import annotations

import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import build_macos_packages as packages
from scripts import make_macos_icon as icon


def _fake_app(tmp_path: Path, version: str = "2.18.0") -> Path:
    app = tmp_path / "dist" / "AgentBell.app"
    (app / "Contents").mkdir(parents=True)
    with (app / "Contents" / "Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleShortVersionString": version}, handle)
    return app


def test_asset_names_cover_both_arches():
    assert packages.asset_name("x64", "dmg") == "AgentBell-macos-x64.dmg"
    assert packages.asset_name("arm64", "zip") == "AgentBell-macos-arm64.zip"


def test_build_packages_signs_and_writes_checksums(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    signed: list[Path] = []

    def fake_sign(target, **kwargs):
        signed.append(target)

    def fake_dmg(target, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dmg payload")
        return destination

    def fake_zip(target, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"zip payload")
        return destination

    monkeypatch.setattr(packages, "sign_app", fake_sign)
    monkeypatch.setattr(packages, "build_dmg", fake_dmg)
    monkeypatch.setattr(packages, "build_zip", fake_zip)

    outdir = tmp_path / "dist"
    created = packages.build_packages(
        app, version="2.18.0", arch="arm64", outdir=outdir
    )

    assert signed == [app]
    assert [path.name for path in created] == [
        "AgentBell-macos-arm64.dmg",
        "AgentBell-macos-arm64.zip",
        "SHA256SUMS-macos-arm64.txt",
    ]
    lines = created[-1].read_text(encoding="ascii").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith(packages.sha256_file(outdir / created[0].name))
    assert lines[0].endswith("AgentBell-macos-arm64.dmg")
    assert lines[1].endswith("AgentBell-macos-arm64.zip")


def test_build_packages_rejects_version_mismatch(tmp_path, monkeypatch):
    app = _fake_app(tmp_path, version="2.17.1")
    monkeypatch.setattr(
        packages, "sign_app", lambda *args, **kwargs: None
    )

    try:
        packages.build_packages(
            app, version="2.18.0", arch="x64", outdir=tmp_path / "dist"
        )
    except ValueError as exc:
        assert "2.17.1" in str(exc)
    else:
        raise AssertionError("version mismatch must be rejected")


def test_sign_command_uses_hardened_runtime_and_entitlements(tmp_path):
    entitlements = tmp_path / "entitlements.plist"
    entitlements.write_text("<plist/>", encoding="utf-8")

    command = packages.sign_command(
        tmp_path / "AgentBell.app",
        identity="Developer ID Application: Example (TEAM)",
        entitlements=entitlements,
        codesign="/usr/bin/codesign",
    )

    assert command[:3] == ["/usr/bin/codesign", "--force", "--deep"]
    assert command[3:7] == ["--options", "runtime", "--timestamp", "--entitlements"]
    assert command[7] == str(entitlements)
    assert command[-3:] == [
        "--sign",
        "Developer ID Application: Example (TEAM)",
        str(tmp_path / "AgentBell.app"),
    ]


def test_sign_command_ad_hoc_stays_unchanged(tmp_path):
    entitlements = tmp_path / "entitlements.plist"
    entitlements.write_text("<plist/>", encoding="utf-8")

    command = packages.sign_command(
        tmp_path / "AgentBell.app",
        identity="-",
        entitlements=entitlements,
    )

    assert "--options" not in command
    assert "--timestamp" not in command
    assert "--entitlements" in command
    assert command[-2:] == ["-", str(tmp_path / "AgentBell.app")]


def test_sign_command_rejects_missing_entitlements(tmp_path):
    with pytest.raises(ValueError, match="entitlements"):
        packages.sign_command(
            tmp_path / "AgentBell.app",
            entitlements=tmp_path / "missing.plist",
        )


def test_sign_dmg_skips_ad_hoc_and_signs_developer_id(tmp_path, monkeypatch):
    commands = []
    monkeypatch.setattr(
        packages.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )

    packages.sign_dmg(tmp_path / "AgentBell.dmg", identity="-")
    assert commands == []

    packages.sign_dmg(
        tmp_path / "AgentBell.dmg",
        identity="Developer ID Application: Example (TEAM)",
        codesign="/usr/bin/codesign",
    )
    assert commands == [
        [
            "/usr/bin/codesign",
            "--force",
            "--timestamp",
            "--sign",
            "Developer ID Application: Example (TEAM)",
            str(tmp_path / "AgentBell.dmg"),
        ]
    ]


def test_notary_credentials_prefers_api_key(tmp_path):
    credentials = packages.NotaryCredentials(
        key_path=tmp_path / "AuthKey.p8",
        key_id="KEY123",
        issuer_id="ISSUER",
        apple_id="dev@example.com",
        password="app-password",
        team_id="TEAM123",
    )

    assert credentials.api_key
    assert credentials.apple_account
    assert credentials.configured
    assert credentials.arguments() == [
        "--key",
        str(tmp_path / "AuthKey.p8"),
        "--key-id",
        "KEY123",
        "--issuer",
        "ISSUER",
    ]


def test_notary_credentials_apple_account_and_empty():
    credentials = packages.NotaryCredentials(
        apple_id="dev@example.com",
        password="app-password",
        team_id="TEAM123",
    )

    assert credentials.arguments() == [
        "--apple-id",
        "dev@example.com",
        "--password",
        "app-password",
        "--team-id",
        "TEAM123",
    ]
    assert not packages.NotaryCredentials().configured
    assert packages.NotaryCredentials().arguments() == []


def test_notarize_app_submits_waits_and_staples(tmp_path, monkeypatch):
    app = tmp_path / "AgentBell.app"
    app.mkdir()
    commands = []

    def fake_zip(source, destination, **kwargs):
        destination.write_bytes(b"zip")
        return destination

    def fake_run(command, **kwargs):
        commands.append(command)
        if "notarytool" in command:
            return SimpleNamespace(stdout='{"status": "Accepted"}')
        return None

    monkeypatch.setattr(packages, "build_zip", fake_zip)
    credentials = packages.NotaryCredentials(
        key_path=tmp_path / "AuthKey.p8",
        key_id="KEY123",
        issuer_id="ISSUER",
    )

    packages.notarize_app(
        app, credentials, ditto="/usr/bin/ditto", xcrun="/usr/bin/xcrun",
        run=fake_run,
    )

    assert commands[0][:5] == [
        "/usr/bin/xcrun",
        "notarytool",
        "submit",
        commands[0][3],
        "--wait",
    ]
    assert commands[0][-6:] == [
        "--key",
        str(tmp_path / "AuthKey.p8"),
        "--key-id",
        "KEY123",
        "--issuer",
        "ISSUER",
    ]
    assert commands[1] == ["/usr/bin/xcrun", "stapler", "staple", str(app)]
    assert commands[2] == ["/usr/bin/xcrun", "stapler", "validate", str(app)]


def test_notarize_app_rejects_rejected_status(tmp_path, monkeypatch):
    app = tmp_path / "AgentBell.app"
    app.mkdir()
    monkeypatch.setattr(
        packages,
        "build_zip",
        lambda source, destination, **kwargs: destination.write_bytes(b"zip"),
    )
    credentials = packages.NotaryCredentials(
        apple_id="dev@example.com",
        password="app-password",
        team_id="TEAM123",
    )
    run = lambda command, **kwargs: SimpleNamespace(  # noqa: E731
        stdout='{"status": "Invalid"}'
    )

    with pytest.raises(RuntimeError, match="Invalid"):
        packages.notarize_app(app, credentials, run=run)


def test_build_packages_orders_signing_and_notarization(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    events = []

    def fake_sign(target, **kwargs):
        events.append(("sign", kwargs))

    def fake_notarize(target, credentials, **kwargs):
        events.append(("notarize", credentials))

    def fake_dmg(target, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"dmg")
        return destination

    def fake_zip(target, destination, **kwargs):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"zip")
        return destination

    def fake_sign_dmg(target, **kwargs):
        events.append(("sign-dmg", kwargs))

    monkeypatch.setattr(packages, "sign_app", fake_sign)
    monkeypatch.setattr(packages, "notarize_app", fake_notarize)
    monkeypatch.setattr(packages, "sign_dmg", fake_sign_dmg)
    monkeypatch.setattr(packages, "build_dmg", fake_dmg)
    monkeypatch.setattr(packages, "build_zip", fake_zip)
    entitlements = tmp_path / "entitlements.plist"
    entitlements.write_text("<plist/>", encoding="utf-8")
    credentials = packages.NotaryCredentials(
        apple_id="dev@example.com",
        password="app-password",
        team_id="TEAM123",
    )

    packages.build_packages(
        app,
        version="2.18.0",
        arch="x64",
        outdir=tmp_path / "dist",
        identity="Developer ID Application: Example (TEAM)",
        entitlements=entitlements,
        notarize=True,
        credentials=credentials,
    )

    assert [event[0] for event in events] == ["sign", "notarize", "sign-dmg"]
    assert events[0][1]["entitlements"] == entitlements
    assert events[1][1] == credentials


def test_build_packages_requires_identity_and_credentials_for_notarization(
    tmp_path, monkeypatch
):
    app = _fake_app(tmp_path)
    monkeypatch.setattr(packages, "sign_app", lambda *args, **kwargs: None)
    credentials = packages.NotaryCredentials(
        apple_id="dev@example.com",
        password="app-password",
        team_id="TEAM123",
    )

    with pytest.raises(ValueError, match="ad-hoc"):
        packages.build_packages(
            app,
            version="2.18.0",
            arch="x64",
            outdir=tmp_path / "dist",
            notarize=True,
            credentials=credentials,
        )

    with pytest.raises(ValueError, match="公证凭据"):
        packages.build_packages(
            app,
            version="2.18.0",
            arch="x64",
            outdir=tmp_path / "dist",
            identity="Developer ID Application: Example (TEAM)",
            notarize=True,
        )


def test_main_reads_notary_environment(tmp_path, monkeypatch):
    app = _fake_app(tmp_path)
    captured = {}

    def fake_build(target, **kwargs):
        captured["app"] = target
        captured.update(kwargs)
        return []

    monkeypatch.setattr(packages, "build_packages", fake_build)
    monkeypatch.setenv("MACOS_SIGN_IDENTITY", "Developer ID Application: Example")
    monkeypatch.setenv("APPLE_API_KEY", str(tmp_path / "AuthKey.p8"))
    monkeypatch.setenv("APPLE_API_KEY_ID", "KEY123")
    monkeypatch.setenv("APPLE_API_ISSUER", "ISSUER")

    code = packages.main(
        [
            "--app",
            str(app),
            "--version",
            "2.18.0",
            "--arch",
            "arm64",
            "--notarize",
        ]
    )

    assert code == 0
    assert captured["identity"] == "Developer ID Application: Example"
    assert captured["notarize"] is True
    credentials = captured["credentials"]
    assert credentials.key_path == tmp_path / "AuthKey.p8"
    assert credentials.api_key


def test_build_zip_uses_ditto_flags(tmp_path, monkeypatch):
    app = tmp_path / "AgentBell.app"
    app.mkdir()
    destination = tmp_path / "AgentBell-macos-x64.zip"
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"zip")

    monkeypatch.setattr(packages.subprocess, "run", fake_run)

    packages.build_zip(app, destination, ditto="/usr/bin/ditto")

    assert commands == [
        [
            "/usr/bin/ditto",
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app),
            str(destination),
        ]
    ]


def test_build_dmg_stages_app_and_applications_link(tmp_path, monkeypatch):
    app = tmp_path / "AgentBell.app"
    app.mkdir()
    destination = tmp_path / "AgentBell-macos-arm64.dmg"
    commands = []
    symlinks = []

    def fake_copytree(source, target, **kwargs):
        Path(target).mkdir(parents=True)
        return Path(target)

    def fake_symlink(self, target):
        symlinks.append((self, target))

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"dmg")

    monkeypatch.setattr(packages.shutil, "copytree", fake_copytree)
    monkeypatch.setattr(Path, "symlink_to", fake_symlink)
    monkeypatch.setattr(packages.subprocess, "run", fake_run)

    packages.build_dmg(app, destination, hdiutil="/usr/bin/hdiutil")

    assert commands[0][0] == "/usr/bin/hdiutil"
    assert commands[0][1:4] == ["create", "-volname", "AgentBell"]
    assert commands[0][-2:] == ["UDZO", str(destination)]
    assert symlinks[0][1] == "/Applications"


def test_iconset_entries_cover_standard_sizes():
    assert icon.iconset_name(16, 1) == "icon_16x16.png"
    assert icon.iconset_name(512, 2) == "icon_512x512@2x.png"
    assert len(icon.iconset_entries()) == 10
    assert icon.iconset_entries()[0] == (16, 1)
    assert icon.iconset_entries()[-1] == (512, 2)


def test_build_icns_invokes_iconutil_and_cleans_iconset(
    tmp_path, monkeypatch
):
    svg = tmp_path / "agentbell.svg"
    svg.write_text("<svg/>", encoding="utf-8")
    destination = tmp_path / "agentbell.icns"
    commands = []

    def fake_render(source, iconset):
        iconset.mkdir(parents=True)
        (iconset / "icon_16x16.png").write_bytes(b"png")

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"icns")

    monkeypatch.setattr(icon, "render_iconset", fake_render)
    monkeypatch.setattr(icon.subprocess, "run", fake_run)

    created = icon.build_icns(
        svg, destination, iconutil="/usr/bin/iconutil"
    )

    assert commands[0][0] == "/usr/bin/iconutil"
    assert commands[0][1:3] == ["-c", "icns"]
    assert created.read_bytes() == b"icns"
    assert not (tmp_path / "agentbell.iconset").exists()
