from __future__ import annotations

import plistlib
from pathlib import Path

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
