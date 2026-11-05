#!/usr/bin/env python3
"""Package a PyInstaller .app into macOS .dmg and .zip release assets."""

from __future__ import annotations

import argparse
import hashlib
import plistlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

APP_NAME = "AgentBell"
ARCHES = ("x64", "arm64")
CHUNK_SIZE = 1024 * 1024


def asset_name(arch: str, suffix: str) -> str:
    return f"{APP_NAME}-macos-{arch}.{suffix}"


def app_version(app: Path) -> str:
    plist = app / "Contents" / "Info.plist"
    if not plist.is_file():
        return ""
    with plist.open("rb") as handle:
        data = plistlib.load(handle)
    return str(data.get("CFBundleShortVersionString") or "")


def sign_app(
    app: Path, *, identity: str = "-", codesign: str = "codesign"
) -> None:
    subprocess.run(
        [
            codesign,
            "--force",
            "--deep",
            "--sign",
            identity,
            str(app),
        ],
        check=True,
    )


def build_zip(
    app: Path, destination: Path, *, ditto: str = "ditto"
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    subprocess.run(
        [
            ditto,
            "-c",
            "-k",
            "--sequesterRsrc",
            "--keepParent",
            str(app),
            str(destination),
        ],
        check=True,
    )
    return destination


def _run_with_retry(
    command: list[str], *, attempts: int = 3, delay: float = 2.0
) -> None:
    for attempt in range(1, attempts + 1):
        try:
            subprocess.run(command, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise
            time.sleep(delay * attempt)


def build_dmg(
    app: Path, destination: Path, *, hdiutil: str = "hdiutil"
) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="agentbell-dmg-") as raw:
        staging = Path(raw)
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        # hdiutil 偶发 "Resource busy"，重试几次即可。
        _run_with_retry(
            [
                hdiutil,
                "create",
                "-volname",
                APP_NAME,
                "-srcfolder",
                str(staging),
                "-ov",
                "-format",
                "UDZO",
                str(destination),
            ]
        )
    return destination


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def write_checksums(outdir: Path, arch: str) -> Path:
    lines = []
    for suffix in ("dmg", "zip"):
        path = outdir / asset_name(arch, suffix)
        lines.append(f"{sha256_file(path)}  {path.name}")
    target = outdir / f"SHA256SUMS-macos-{arch}.txt"
    target.write_text("\n".join(lines) + "\n", encoding="ascii")
    return target


def build_packages(
    app: Path,
    *,
    version: str,
    arch: str,
    outdir: Path,
    identity: str = "-",
) -> list[Path]:
    if not app.is_dir() or app.suffix != ".app":
        raise ValueError(f"不是有效的 .app 目录：{app}")
    bundled = app_version(app)
    if bundled and bundled != version:
        raise ValueError(
            f".app 版本 {bundled} 与 --version {version} 不一致"
        )
    sign_app(app, identity=identity)
    outdir.mkdir(parents=True, exist_ok=True)
    created = [
        build_dmg(app, outdir / asset_name(arch, "dmg")),
        build_zip(app, outdir / asset_name(arch, "zip")),
    ]
    created.append(write_checksums(outdir, arch))
    return created


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", choices=sorted(ARCHES), required=True)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--identity",
        default="-",
        help="codesign identity; '-' uses an ad-hoc signature",
    )
    args = parser.parse_args(argv)
    created = build_packages(
        args.app,
        version=args.version,
        arch=args.arch,
        outdir=args.outdir,
        identity=args.identity,
    )
    for path in created:
        print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
