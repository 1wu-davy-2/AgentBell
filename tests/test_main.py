from __future__ import annotations

import agentbell.main as main_module


def test_port_error_text_uses_platform_command(monkeypatch):
    monkeypatch.setattr(main_module.os, "name", "nt")
    windows = main_module._port_error_text(8765, RuntimeError("busy"))
    assert "netstat -ano" in windows
    assert "ss -ltnp" not in windows

    monkeypatch.setattr(main_module.os, "name", "posix")
    monkeypatch.setattr(main_module.sys, "platform", "linux")
    linux = main_module._port_error_text(8765, RuntimeError("busy"))
    assert "ss -ltnp" in linux
    assert "netstat -ano" not in linux

    monkeypatch.setattr(main_module.sys, "platform", "darwin")
    macos = main_module._port_error_text(8765, RuntimeError("busy"))
    assert "lsof -nP -iTCP:8765" in macos
    assert "ss -ltnp" not in macos
