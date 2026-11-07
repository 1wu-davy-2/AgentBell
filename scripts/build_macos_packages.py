#!/usr/bin/env python3
"""Package a PyInstaller .app into macOS .dmg and .zip release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

APP_NAME = "AgentBell"
ARCHES = ("x64", "arm64")
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class NotaryCredentials:
    key_path: Path | None = None
    key_id: str = ""
    issuer_id: str = ""
    apple_id: str = ""
    password: str = ""
    team_id: str = ""

    @property
    def api_key(self) -> bool:
        return bool(self.key_path and self.key_id and self.issuer_id)

    @property
    def apple_account(self) -> bool:
        return bool(self.apple_id and self.password and self.team_id)

    @property
    def configured(self) -> bool:
        return self.api_key or self.apple_account

    def arguments(self) -> list[str]:
        if self.api_key:
            assert self.key_path is not None
            return [
                "--key",
                str(self.key_path),
                "--key-id",
                self.key_id,
                "--issuer",
                self.issuer_id,
            ]
        if self.apple_account:
            return [
                "--apple-id",
                self.apple_id,
                "--password",
                self.password,
                "--team-id",
                self.team_id,
            ]
        return []


def asset_name(arch: str, suffix: str) -> str:
    return f"{APP_NAME}-macos-{arch}.{suffix}"


def app_version(app: Path) -> str:
    plist = app / "Contents" / "Info.plist"
    if not plist.is_file():
        return ""
    with plist.open("rb") as handle:
        data = plistlib.load(handle)
    return str(data.get("CFBundleShortVersionString") or "")


def sign_command(
    app: Path,
    *,
    identity: str = "-",
    entitlements: Path | None = None,
    codesign: str = "codesign",
) -> list[str]:
    command = [codesign, "--force", "--deep"]
    if identity and identity != "-":
        command += ["--options", "runtime", "--timestamp"]
    if entitlements is not None:
        if not entitlements.is_file():
            raise ValueError(f"缺少 entitlements 文件：{entitlements}")
        command += ["--entitlements", str(entitlements)]
    command += ["--sign", identity or "-", str(app)]
    return command


def sign_app(
    app: Path,
    *,
    identity: str = "-",
    entitlements: Path | None = None,
    codesign: str = "codesign",
) -> None:
    subprocess.run(
        sign_command(
            app,
            identity=identity,
            entitlements=entitlements,
            codesign=codesign,
        ),
        check=True,
    )


def sign_dmg(
    dmg: Path, *, identity: str, codesign: str = "codesign"
) -> None:
    if not identity or identity == "-":
        return
    subprocess.run(
        [
            codesign,
            "--force",
            "--timestamp",
            "--sign",
            identity,
            str(dmg),
        ],
        check=True,
    )


def notary_command(
    archive: Path, credentials: NotaryCredentials, *, xcrun: str = "xcrun"
) -> list[str]:
    return [
        xcrun,
        "notarytool",
        "submit",
        str(archive),
        "--wait",
        "--output-format",
        "json",
        *credentials.arguments(),
    ]


def notarize_app(
    app: Path,
    credentials: NotaryCredentials,
    *,
    ditto: str = "ditto",
    xcrun: str = "xcrun",
    run=subprocess.run,
    timeout: int = 1800,
) -> None:
    if not credentials.configured:
        raise ValueError("缺少 Apple 公证凭据")
    with tempfile.TemporaryDirectory(prefix="agentbell-notary-") as raw:
        archive = Path(raw) / f"{app.stem}.zip"
        build_zip(app, archive, ditto=ditto)
        result = run(
            notary_command(archive, credentials, xcrun=xcrun),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        status = ""
        try:
            status = str(json.loads(result.stdout or "{}").get("status") or "")
        except (TypeError, ValueError):
            status = ""
        if status and status != "Accepted":
            raise RuntimeError(f"Apple 公证未通过：{status}")
    run([xcrun, "stapler", "staple", str(app)], check=True)
    run([xcrun, "stapler", "validate", str(app)], check=True)


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
    entitlements: Path | None = None,
    notarize: bool = False,
    credentials: NotaryCredentials | None = None,
) -> list[Path]:
    if not app.is_dir() or app.suffix != ".app":
        raise ValueError(f"不是有效的 .app 目录：{app}")
    bundled = app_version(app)
    if bundled and bundled != version:
        raise ValueError(
            f".app 版本 {bundled} 与 --version {version} 不一致"
        )
    if notarize:
        if identity in ("", "-"):
            raise ValueError("公证需要 Developer ID 签名身份，不能使用 ad-hoc 签名")
        if credentials is None or not credentials.configured:
            raise ValueError("缺少 Apple 公证凭据")
    sign_app(app, identity=identity, entitlements=entitlements)
    if notarize:
        assert credentials is not None
        notarize_app(app, credentials)
    outdir.mkdir(parents=True, exist_ok=True)
    dmg = build_dmg(app, outdir / asset_name(arch, "dmg"))
    sign_dmg(dmg, identity=identity)
    created = [
        dmg,
        build_zip(app, outdir / asset_name(arch, "zip")),
    ]
    created.append(write_checksums(outdir, arch))
    return created


def _env(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def credentials_from_args(args: argparse.Namespace) -> NotaryCredentials:
    return NotaryCredentials(
        key_path=args.notary_key,
        key_id=args.notary_key_id,
        issuer_id=args.notary_issuer,
        apple_id=args.apple_id,
        password=args.apple_password,
        team_id=args.team_id,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--arch", choices=sorted(ARCHES), required=True)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--identity",
        default=_env("MACOS_SIGN_IDENTITY") or "-",
        help="codesign identity; '-' uses an ad-hoc signature",
    )
    parser.add_argument(
        "--entitlements",
        type=Path,
        help="hardened runtime entitlements plist",
    )
    parser.add_argument(
        "--notarize",
        action="store_true",
        help="submit the signed app to Apple notarytool and staple it",
    )
    parser.add_argument(
        "--notary-key",
        type=Path,
        default=Path(value) if (value := _env("APPLE_API_KEY")) else None,
        help="App Store Connect API key (.p8); env APPLE_API_KEY",
    )
    parser.add_argument(
        "--notary-key-id",
        default=_env("APPLE_API_KEY_ID"),
        help="App Store Connect key id; env APPLE_API_KEY_ID",
    )
    parser.add_argument(
        "--notary-issuer",
        default=_env("APPLE_API_ISSUER"),
        help="App Store Connect issuer id; env APPLE_API_ISSUER",
    )
    parser.add_argument(
        "--apple-id",
        default=_env("APPLE_ID"),
        help="Apple ID for notarytool; env APPLE_ID",
    )
    parser.add_argument(
        "--apple-password",
        default=_env("APPLE_APP_PASSWORD"),
        help="app-specific password; prefer env APPLE_APP_PASSWORD",
    )
    parser.add_argument(
        "--team-id",
        default=_env("APPLE_TEAM_ID"),
        help="Apple team id; env APPLE_TEAM_ID",
    )
    args = parser.parse_args(argv)
    created = build_packages(
        args.app,
        version=args.version,
        arch=args.arch,
        outdir=args.outdir,
        identity=args.identity,
        entitlements=args.entitlements,
        notarize=args.notarize,
        credentials=credentials_from_args(args),
    )
    for path in created:
        print(f"{path}  {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
