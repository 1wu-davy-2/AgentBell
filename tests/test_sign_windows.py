from __future__ import annotations

import base64
from pathlib import Path

import pytest

from scripts import sign_windows


def test_find_signtool_prefers_path(monkeypatch):
    monkeypatch.setattr(
        sign_windows.shutil,
        "which",
        lambda name: "C:/sdk/signtool.exe" if name in ("signtool", "signtool.exe") else None,
    )

    assert sign_windows.find_signtool() == "C:/sdk/signtool.exe"


def test_find_signtool_scans_windows_kits(tmp_path, monkeypatch):
    monkeypatch.setattr(sign_windows.shutil, "which", lambda name: None)
    kits = tmp_path / "Windows Kits" / "10" / "bin"
    old = kits / "10.0.19041.0" / "x64" / "signtool.exe"
    new = kits / "10.0.22621.0" / "x64" / "signtool.exe"
    for path in (old, new):
        path.parent.mkdir(parents=True)
        path.write_bytes(b"exe")
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)

    assert sign_windows.find_signtool() == str(new)


def test_find_signtool_rejects_missing_explicit_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="signtool"):
        sign_windows.find_signtool(str(tmp_path / "missing.exe"))


def test_sign_command_with_pfx_uses_sha256_and_timestamp(tmp_path):
    pfx = tmp_path / "cert.pfx"
    target = tmp_path / "AgentBell.exe"

    command = sign_windows.sign_command(
        target,
        signtool="C:/sdk/signtool.exe",
        pfx=pfx,
        password="secret",
        timestamp="http://timestamp.example",
    )

    assert command == [
        "C:/sdk/signtool.exe",
        "sign",
        "/fd",
        "SHA256",
        "/td",
        "SHA256",
        "/tr",
        "http://timestamp.example",
        "/d",
        "AgentBell",
        "/f",
        str(pfx),
        "/p",
        "secret",
        str(target),
    ]


def test_sign_command_with_thumbprint_has_no_password(tmp_path):
    command = sign_windows.sign_command(
        tmp_path / "AgentBell.exe",
        thumbprint="ABC123",
    )

    assert "/sha1" in command
    assert command[command.index("/sha1") + 1] == "ABC123"
    assert "/p" not in command
    assert "/f" not in command


def test_sign_command_requires_certificate(tmp_path):
    with pytest.raises(ValueError, match="证书"):
        sign_windows.sign_command(tmp_path / "AgentBell.exe")


def test_redacted_hides_password():
    command = [
        "signtool",
        "sign",
        "/f",
        "cert.pfx",
        "/p",
        "secret",
        "AgentBell.exe",
    ]

    assert "secret" not in sign_windows.redacted(command)
    assert "******" in sign_windows.redacted(command)


def test_decode_pfx_writes_bytes(tmp_path):
    destination = tmp_path / "cert.pfx"
    payload = b"pfx-bytes"

    sign_windows.decode_pfx(base64.b64encode(payload).decode("ascii"), destination)

    assert destination.read_bytes() == payload


def test_decode_pfx_rejects_invalid_base64(tmp_path):
    with pytest.raises(ValueError, match="base64"):
        sign_windows.decode_pfx("not base64!", tmp_path / "cert.pfx")
    with pytest.raises(ValueError, match="PFX_BASE64"):
        sign_windows.decode_pfx("", tmp_path / "cert.pfx")


def test_sign_file_signs_then_verifies(tmp_path, monkeypatch):
    target = tmp_path / "AgentBell.exe"
    target.write_bytes(b"exe")
    commands = []
    run = lambda command, **kwargs: commands.append(command)  # noqa: E731

    sign_windows.sign_file(
        target,
        signtool="signtool",
        thumbprint="ABC123",
        run=run,
    )

    assert commands[0][:2] == ["signtool", "sign"]
    assert commands[1] == [
        "signtool",
        "verify",
        "/pa",
        "/all",
        str(target),
    ]


def test_sign_file_can_skip_verify(tmp_path):
    target = tmp_path / "AgentBell.exe"
    target.write_bytes(b"exe")
    commands = []

    sign_windows.sign_file(
        target,
        thumbprint="ABC123",
        run=lambda command, **kwargs: commands.append(command),
        verify=False,
    )

    assert len(commands) == 1
    assert commands[0][1] == "sign"


def test_sign_file_rejects_missing_target(tmp_path):
    with pytest.raises(FileNotFoundError, match="待签名"):
        sign_windows.sign_file(
            tmp_path / "missing.exe",
            thumbprint="ABC123",
            run=lambda command, **kwargs: None,
        )


def test_main_decodes_pfx_from_environment(tmp_path, monkeypatch):
    target = tmp_path / "AgentBell.exe"
    target.write_bytes(b"exe")
    payload = b"pfx-bytes"
    captured = {}

    def fake_sign_targets(targets, **kwargs):
        captured["targets"] = list(targets)
        captured.update(kwargs)
        captured["pfx_bytes"] = kwargs["pfx"].read_bytes()

    monkeypatch.setattr(sign_windows, "sign_targets", fake_sign_targets)
    monkeypatch.setattr(sign_windows, "find_signtool", lambda explicit: "signtool")
    monkeypatch.setenv(
        sign_windows.PFX_ENV, base64.b64encode(payload).decode("ascii")
    )
    monkeypatch.setenv(sign_windows.PASSWORD_ENV, "secret")

    code = sign_windows.main(["--target", str(target)])

    assert code == 0
    assert captured["targets"] == [target]
    assert captured["password"] == "secret"
    assert captured["pfx_bytes"] == payload


def test_main_rejects_missing_credentials(tmp_path, monkeypatch):
    target = tmp_path / "AgentBell.exe"
    target.write_bytes(b"exe")
    for name in (
        sign_windows.PFX_ENV,
        sign_windows.PASSWORD_ENV,
        sign_windows.THUMBPRINT_ENV,
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as excinfo:
        sign_windows.main(["--target", str(target)])

    assert excinfo.value.code == 2