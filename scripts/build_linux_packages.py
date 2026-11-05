#!/usr/bin/env python3
"""Build Linux release packages for AgentBell."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Iterable, Sequence

APP_NAME = "AgentBell"
APP_ID = "agentbell"
SUMMARY = "Local notification center for coding agents"
MAINTAINER = "AgentBell Maintainers <1wu-davy-2@users.noreply.github.com>"
HOMEPAGE = "https://github.com/1wu-davy-2/AgentBell"

DEB_ARCH = {"x64": "amd64", "arm64": "arm64"}
RPM_ARCH = {"x64": "x86_64", "arm64": "aarch64"}
APPIMAGE_ARCH = {"x64": "x86_64", "arm64": "aarch64"}

DEB_DEPENDS = (
    "libc6",
    "libgl1",
    "libegl1",
    "libxkbcommon0",
    "libxkbcommon-x11-0",
    "libdbus-1-3",
    "libfontconfig1",
    "libxcb-cursor0",
    "libxcb-icccm4",
    "libxcb-image0",
    "libxcb-keysyms1",
    "libxcb-randr0",
    "libxcb-render-util0",
    "libxcb-shape0",
    "libxcb-xinerama0",
    "libxcb-xfixes0",
)

RPM_REQUIRES = (
    "libX11",
    "libxkbcommon",
    "libxkbcommon-x11",
    "libxcb",
    "mesa-libGL",
    "mesa-libEGL",
    "fontconfig",
    "dbus-libs",
)


def asset_name(arch: str, suffix: str) -> str:
    return f"{APP_NAME}-linux-{arch}.{suffix}"


def desktop_entry(exec_name: str) -> str:
    return "\n".join(
        [
            "[Desktop Entry]",
            "Type=Application",
            "Name=AgentBell",
            "GenericName=Notification Center",
            "Comment=Local notifications from coding agents",
            "Comment[zh_CN]=本机 Agent 通知中心",
            f"Exec={exec_name}",
            f"Icon={APP_ID}",
            "Terminal=false",
            "Categories=Utility;",
            "StartupNotify=false",
            "StartupWMClass=AgentBell",
            "",
        ]
    )


def apprun_script() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -e",
            'HERE=$(dirname "$(readlink -f "$0")")',
            'exec "$HERE/usr/bin/AgentBell" "$@"',
            "",
        ]
    )


def deb_control(version: str, arch: str, installed_size_kb: int) -> str:
    return "\n".join(
        [
            f"Package: {APP_ID}",
            f"Version: {version}",
            "Section: utils",
            "Priority: optional",
            f"Architecture: {DEB_ARCH[arch]}",
            f"Installed-Size: {installed_size_kb}",
            f"Maintainer: {MAINTAINER}",
            f"Homepage: {HOMEPAGE}",
            "Depends: " + ", ".join(DEB_DEPENDS),
            f"Description: {SUMMARY}",
            " AgentBell collects local notifications from Claude Code, Qoder and",
            " other agents, showing native popups, a notification center and",
            " read-only session views. It listens on 127.0.0.1 only.",
            "",
        ]
    )


def rpm_spec(version: str, arch: str) -> str:
    return "\n".join(
        [
            "%global __os_install_post %{nil}",
            "%global debug_package %{nil}",
            "%global _build_id_links none",
            "",
            f"Name: {APP_ID}",
            f"Version: {version}",
            "Release: 1",
            f"Summary: {SUMMARY}",
            "License: MIT",
            f"URL: {HOMEPAGE}",
            f"BuildArch: {RPM_ARCH[arch]}",
            "AutoReqProv: no",
            *[f"Requires: {item}" for item in RPM_REQUIRES],
            "",
            "%description",
            "AgentBell collects local notifications from Claude Code, Qoder and",
            "other agents, showing native popups, a notification center and",
            "read-only session views. It listens on 127.0.0.1 only.",
            "",
            "%prep",
            "# prebuilt binary; nothing to unpack",
            "",
            "%build",
            "# prebuilt binary; nothing to compile",
            "",
            "%install",
            "mkdir -p %{buildroot}/usr/bin",
            "install -Dm755 %{_sourcedir}/AgentBell %{buildroot}/opt/agentbell/AgentBell",
            "install -Dm644 %{_sourcedir}/agentbell.desktop "
            "%{buildroot}/usr/share/applications/agentbell.desktop",
            "install -Dm644 %{_sourcedir}/agentbell.png "
            "%{buildroot}/usr/share/icons/hicolor/256x256/apps/agentbell.png",
            "install -Dm644 %{_sourcedir}/agentbell.svg "
            "%{buildroot}/usr/share/icons/hicolor/scalable/apps/agentbell.svg",
            "ln -s /opt/agentbell/AgentBell %{buildroot}/usr/bin/agentbell",
            "",
            "%files",
            "/opt/agentbell/AgentBell",
            "/usr/bin/agentbell",
            "/usr/share/applications/agentbell.desktop",
            "/usr/share/icons/hicolor/256x256/apps/agentbell.png",
            "/usr/share/icons/hicolor/scalable/apps/agentbell.svg",
            "",
        ]
    )


def render_icon(svg: Path, png: Path, size: int = 256) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"无法解析图标：{svg}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    png.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(png)):
        raise SystemExit(f"无法写入图标：{png}")


def make_tar_gz(binary: Path, destination: Path) -> Path:
    with tarfile.open(destination, "w:gz") as bundle:
        info = bundle.gettarinfo(str(binary), arcname=APP_NAME)
        info.mode = 0o755
        info.uid = 0
        info.gid = 0
        info.uname = "root"
        info.gname = "root"
        with binary.open("rb") as handle:
            bundle.addfile(info, handle)
    return destination


def stage_appdir(root: Path, binary: Path, icon_png: Path, icon_svg: Path) -> Path:
    appdir = root / f"{APP_NAME}.AppDir"
    _copy(binary, appdir / "usr" / "bin" / APP_NAME, 0o755)
    _write(appdir / f"{APP_ID}.desktop", desktop_entry(APP_NAME))
    _write(appdir / "AppRun", apprun_script(), 0o755)
    shutil.copyfile(icon_png, appdir / f"{APP_ID}.png")
    _copy(icon_png, appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png")
    _copy(icon_svg, appdir / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg")
    _copy(appdir / f"{APP_ID}.desktop", appdir / "usr" / "share" / "applications" / f"{APP_ID}.desktop")
    dir_icon = appdir / ".DirIcon"
    try:
        dir_icon.symlink_to(f"{APP_ID}.png")
    except OSError:
        shutil.copyfile(appdir / f"{APP_ID}.png", dir_icon)
    return appdir


def build_appimage(
    appdir: Path,
    destination: Path,
    *,
    arch: str,
    tool: Path,
    runtime: Path,
) -> Path:
    env = dict(os.environ)
    env["ARCH"] = APPIMAGE_ARCH[arch]
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    destination.unlink(missing_ok=True)
    tool = tool.resolve()
    runtime = runtime.resolve()
    subprocess.run(
        [
            str(tool),
            "--appimage-extract-and-run",
            "--no-appstream",
            "--runtime-file",
            str(runtime),
            str(appdir),
            str(destination),
        ],
        check=True,
        env=env,
    )
    destination.chmod(0o755)
    return destination


def build_deb(
    root: Path,
    binary: Path,
    icon_png: Path,
    icon_svg: Path,
    *,
    version: str,
    arch: str,
    destination: Path,
) -> Path:
    package = root / f"deb-{arch}"
    prefix = package / "opt" / APP_ID
    prefix.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, prefix / APP_NAME)
    (prefix / APP_NAME).chmod(0o755)
    _write(
        package / "usr" / "share" / "applications" / f"{APP_ID}.desktop",
        desktop_entry(APP_ID),
    )
    _copy(
        icon_png,
        package / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png",
    )
    _copy(
        icon_svg,
        package / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg",
    )
    bin_dir = package / "usr" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    link = bin_dir / APP_ID
    try:
        link.symlink_to(f"/opt/{APP_ID}/{APP_NAME}")
    except OSError:
        shutil.copyfile(binary, link)
        link.chmod(0o755)
    installed_size = sum(
        item.stat().st_size for item in package.rglob("*") if item.is_file()
    )
    _write(
        package / "DEBIAN" / "control",
        deb_control(version, arch, max(1, installed_size // 1024)),
    )
    subprocess.run(
        [
            "dpkg-deb",
            "--build",
            "--root-owner-group",
            "-Zxz",
            str(package),
            str(destination),
        ],
        check=True,
    )
    return destination


def build_rpm(
    root: Path,
    binary: Path,
    icon_png: Path,
    icon_svg: Path,
    *,
    version: str,
    arch: str,
    destination: Path,
) -> Path:
    topdir = root / f"rpm-{arch}"
    sources = topdir / "SOURCES"
    specs = topdir / "SPECS"
    sources.mkdir(parents=True, exist_ok=True)
    specs.mkdir(parents=True, exist_ok=True)
    (topdir / "BUILD").mkdir(parents=True, exist_ok=True)
    (topdir / "BUILDROOT").mkdir(parents=True, exist_ok=True)
    (topdir / "RPMS").mkdir(parents=True, exist_ok=True)
    (topdir / "SRPMS").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(binary, sources / APP_NAME)
    (sources / APP_NAME).chmod(0o755)
    _write(sources / f"{APP_ID}.desktop", desktop_entry(APP_ID))
    shutil.copyfile(icon_png, sources / f"{APP_ID}.png")
    shutil.copyfile(icon_svg, sources / f"{APP_ID}.svg")
    spec = specs / f"{APP_ID}.spec"
    _write(spec, rpm_spec(version, arch))
    subprocess.run(
        [
            "rpmbuild",
            "-bb",
            "--define",
            f"_topdir {topdir}",
            "--define",
            f"_sourcedir {sources}",
            "--define",
            f"_specdir {specs}",
            "--define",
            f"_rpmdir {topdir / 'RPMS'}",
            "--define",
            f"_srcrpmdir {topdir / 'SRPMS'}",
            str(spec),
        ],
        check=True,
    )
    built = sorted((topdir / "RPMS").glob(f"*/{APP_ID}-{version}-1.*.rpm"))
    if not built:
        raise SystemExit("rpmbuild 未生成 RPM 文件")
    shutil.copyfile(built[0], destination)
    return destination


def write_checksums(outdir: Path, arch: str) -> Path:
    destination = outdir / f"SHA256SUMS-linux-{arch}.txt"
    files = sorted(
        path
        for path in outdir.glob(f"{APP_NAME}-linux-{arch}.*")
        if path.is_file()
    )
    lines = []
    for path in files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    destination.write_text("\n".join(lines) + "\n", encoding="ascii")
    return destination


def build_packages(
    *,
    binary: Path,
    version: str,
    arch: str,
    outdir: Path,
    icon_svg: Path,
    appimagetool: Path | None = None,
    appimage_runtime: Path | None = None,
) -> list[Path]:
    if arch not in DEB_ARCH:
        raise SystemExit(f"不支持的架构：{arch}")
    if not binary.is_file():
        raise SystemExit(f"找不到可执行文件：{binary}")
    outdir.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    created.append(make_tar_gz(binary, outdir / asset_name(arch, "tar.gz")))
    with tempfile.TemporaryDirectory(prefix="agentbell-pack-") as temp:
        root = Path(temp)
        icon_png = root / f"{APP_ID}.png"
        render_icon(icon_svg, icon_png)
        if appimagetool is not None and appimage_runtime is not None:
            appdir = stage_appdir(root, binary, icon_png, icon_svg)
            created.append(
                build_appimage(
                    appdir,
                    outdir / asset_name(arch, "AppImage"),
                    arch=arch,
                    tool=appimagetool,
                    runtime=appimage_runtime,
                )
            )
        created.append(
            build_deb(
                root,
                binary,
                icon_png,
                icon_svg,
                version=version,
                arch=arch,
                destination=outdir / asset_name(arch, "deb"),
            )
        )
        created.append(
            build_rpm(
                root,
                binary,
                icon_png,
                icon_svg,
                version=version,
                arch=arch,
                destination=outdir / asset_name(arch, "rpm"),
            )
        )
    created.append(write_checksums(outdir, arch))
    return created


def _write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _copy(source: Path, destination: Path, mode: int = 0o644) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", choices=sorted(DEB_ARCH), required=True)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument("--icon", type=Path, default=Path("assets/agentbell.svg"))
    parser.add_argument("--appimagetool", type=Path)
    parser.add_argument("--appimage-runtime", type=Path)
    args = parser.parse_args(argv)
    if (args.appimagetool is None) != (args.appimage_runtime is None):
        parser.error("--appimagetool 与 --appimage-runtime 必须同时提供")
    for tool in (args.appimagetool, args.appimage_runtime):
        if tool is not None and not tool.is_file():
            parser.error(f"找不到文件：{tool}")
    created = build_packages(
        binary=args.binary,
        version=args.version,
        arch=args.arch,
        outdir=args.outdir,
        icon_svg=args.icon,
        appimagetool=args.appimagetool,
        appimage_runtime=args.appimage_runtime,
    )
    for path in created:
        print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
