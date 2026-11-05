from __future__ import annotations

import hashlib
import tarfile

from scripts import build_linux_packages as packages


def test_asset_names_cover_all_formats():
    assert packages.asset_name("x64", "tar.gz") == "AgentBell-linux-x64.tar.gz"
    assert packages.asset_name("arm64", "AppImage") == "AgentBell-linux-arm64.AppImage"
    assert packages.asset_name("x64", "deb") == "AgentBell-linux-x64.deb"
    assert packages.asset_name("arm64", "rpm") == "AgentBell-linux-arm64.rpm"


def test_desktop_entry_uses_requested_exec():
    entry = packages.desktop_entry("agentbell")

    assert "[Desktop Entry]" in entry
    assert "Exec=agentbell" in entry
    assert "Icon=agentbell" in entry
    assert "StartupWMClass=AgentBell" in entry
    assert "Comment[zh_CN]" in entry


def test_apprun_executes_bundled_binary():
    script = packages.apprun_script()

    assert script.startswith("#!/bin/sh")
    assert 'exec "$HERE/usr/bin/AgentBell" "$@"' in script


def test_deb_control_maps_architectures_and_dependencies():
    control = packages.deb_control("2.17.0", "arm64", 12345)

    assert "Package: agentbell" in control
    assert "Version: 2.17.0" in control
    assert "Architecture: arm64" in control
    assert "Installed-Size: 12345" in control
    assert "Depends: libc6, libgl1" in control
    assert "libxcb-cursor0" in control


def test_rpm_spec_disables_stripping_and_maps_arch():
    spec = packages.rpm_spec("2.17.0", "arm64")

    assert "%global __os_install_post %{nil}" in spec
    assert "%global debug_package %{nil}" in spec
    assert "BuildArch: aarch64" in spec
    assert "AutoReqProv: no" in spec
    assert "Requires: dbus-libs" in spec
    assert "%prep" in spec
    assert "%build" in spec
    assert "%{_sourcedir}/AgentBell" in spec


def test_make_tar_gz_contains_single_executable(tmp_path):
    binary = tmp_path / "AgentBell"
    binary.write_bytes(b"agentbell-binary")
    archive = packages.make_tar_gz(binary, tmp_path / "AgentBell-linux-x64.tar.gz")

    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()

    assert [item.name for item in members] == ["AgentBell"]
    assert members[0].mode == 0o755
    assert members[0].uid == 0


def test_write_checksums_covers_each_asset(tmp_path):
    contents = {
        "AgentBell-linux-x64.tar.gz": b"tar",
        "AgentBell-linux-x64.AppImage": b"appimage",
        "AgentBell-linux-x64.deb": b"deb",
        "AgentBell-linux-x64.rpm": b"rpm",
    }
    for name, data in contents.items():
        (tmp_path / name).write_bytes(data)

    result = packages.write_checksums(tmp_path, "x64")
    lines = result.read_text(encoding="ascii").splitlines()

    assert len(lines) == 4
    hashes = {line.split()[1]: line.split()[0] for line in lines}
    for name, data in contents.items():
        assert hashes[name] == hashlib.sha256(data).hexdigest()
