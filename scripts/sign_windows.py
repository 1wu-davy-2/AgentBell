#!/usr/bin/env python3
"""Sign AgentBell Windows binaries with Authenticode (signtool)."""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

APP_NAME = "AgentBell"
DEFAULT_TIMESTAMP = "http://timestamp.digicert.com"
PFX_ENV = "WINDOWS_CERT_PFX_BASE64"
PASSWORD_ENV = "WINDOWS_CERT_PASSWORD"
THUMBPRINT_ENV = "WINDOWS_CERT_THUMBPRINT"
TIMESTAMP_ENV = "WINDOWS_TIMESTAMP_URL"


def _version_key(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in value.split("."):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def find_signtool(explicit: str = "") -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise FileNotFoundError(f"未找到 signtool：{explicit}")
        return str(path)
    found = shutil.which("signtool") or shutil.which("signtool.exe")
    if found:
        return found
    candidates: list[Path] = []
    for base in (
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
    ):
        if not base:
            continue
        kits = Path(base) / "Windows Kits" / "10" / "bin"
        if not kits.is_dir():
            continue
        candidates.extend(kits.glob("*/x64/signtool.exe"))
        candidates.extend(kits.glob("*/x86/signtool.exe"))
        candidates.extend(kits.glob("*/arm64/signtool.exe"))
    if not candidates:
        raise FileNotFoundError(
            "未找到 signtool.exe，请安装 Windows SDK 或传入 --signtool"
        )
    candidates.sort(key=lambda item: _version_key(item.parent.parent.name))
    return str(candidates[-1])


def sign_command(
    target: Path,
    *,
    signtool: str = "signtool",
    pfx: Path | None = None,
    password: str = "",
    thumbprint: str = "",
    timestamp: str = DEFAULT_TIMESTAMP,
    description: str = APP_NAME,
) -> list[str]:
    if pfx is None and not thumbprint:
        raise ValueError("缺少代码签名证书：请提供 PFX 或证书指纹")
    command = [
        signtool,
        "sign",
        "/fd",
        "SHA256",
        "/td",
        "SHA256",
        "/tr",
        timestamp,
        "/d",
        description,
    ]
    if pfx is not None:
        command += ["/f", str(pfx)]
        if password:
            command += ["/p", password]
    else:
        command += ["/sha1", thumbprint]
    command.append(str(target))
    return command


def verify_command(target: Path, *, signtool: str = "signtool") -> list[str]:
    return [signtool, "verify", "/pa", "/all", str(target)]


def redacted(command: Sequence[str]) -> str:
    masked: list[str] = []
    hide_next = False
    for item in command:
        if hide_next:
            masked.append("******")
            hide_next = False
            continue
        masked.append(item)
        if item == "/p":
            hide_next = True
    return " ".join(masked)


def decode_pfx(encoded: str, destination: Path) -> Path:
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("WINDOWS_CERT_PFX_BASE64 不是有效的 base64") from exc
    if not data:
        raise ValueError("WINDOWS_CERT_PFX_BASE64 为空")
    destination.write_bytes(data)
    return destination


def sign_file(
    target: Path,
    *,
    signtool: str = "signtool",
    pfx: Path | None = None,
    password: str = "",
    thumbprint: str = "",
    timestamp: str = DEFAULT_TIMESTAMP,
    run=subprocess.run,
    verify: bool = True,
) -> None:
    if not target.is_file():
        raise FileNotFoundError(f"待签名文件不存在：{target}")
    command = sign_command(
        target,
        signtool=signtool,
        pfx=pfx,
        password=password,
        thumbprint=thumbprint,
        timestamp=timestamp,
    )
    print(f"签名 {target.name}：{redacted(command)}")
    run(command, check=True)
    if verify:
        run(verify_command(target, signtool=signtool), check=True)


def sign_targets(
    targets: Sequence[Path],
    *,
    pfx: Path | None = None,
    password: str = "",
    thumbprint: str = "",
    signtool: str = "",
    timestamp: str = DEFAULT_TIMESTAMP,
    run=subprocess.run,
    verify: bool = True,
) -> None:
    if not targets:
        raise ValueError("没有待签名文件")
    tool = find_signtool(signtool)
    for target in targets:
        sign_file(
            Path(target),
            signtool=tool,
            pfx=pfx,
            password=password,
            thumbprint=thumbprint,
            timestamp=timestamp,
            run=run,
            verify=verify,
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        action="append",
        required=True,
        help="file to sign; repeat for every executable",
    )
    parser.add_argument("--pfx", type=Path, help="PKCS#12 certificate file")
    parser.add_argument(
        "--thumbprint",
        default=os.environ.get(THUMBPRINT_ENV, ""),
        help=f"certificate SHA-1 thumbprint; env {THUMBPRINT_ENV}",
    )
    parser.add_argument(
        "--timestamp",
        default=os.environ.get(TIMESTAMP_ENV, "") or DEFAULT_TIMESTAMP,
        help=f"RFC 3161 timestamp URL; env {TIMESTAMP_ENV}",
    )
    parser.add_argument("--signtool", default="", help="path to signtool.exe")
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip signtool verify after signing",
    )
    args = parser.parse_args(argv)

    password = os.environ.get(PASSWORD_ENV, "")
    encoded = os.environ.get(PFX_ENV, "").strip()
    if args.pfx is None and not args.thumbprint and not encoded:
        parser.error(
            f"缺少证书：请传入 --pfx/--thumbprint，或设置 {PFX_ENV}"
        )
    if args.pfx is None and not args.thumbprint and encoded:
        with tempfile.TemporaryDirectory(prefix="agentbell-sign-") as raw:
            pfx = decode_pfx(encoded, Path(raw) / "cert.pfx")
            sign_targets(
                args.target,
                pfx=pfx,
                password=password,
                signtool=args.signtool,
                timestamp=args.timestamp,
                verify=not args.no_verify,
            )
    else:
        sign_targets(
            args.target,
            pfx=args.pfx,
            password=password,
            thumbprint=args.thumbprint,
            signtool=args.signtool,
            timestamp=args.timestamp,
            verify=not args.no_verify,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())