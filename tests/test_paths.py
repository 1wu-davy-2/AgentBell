from __future__ import annotations

import agentbell.paths as paths


def test_chat_and_updates_live_beside_config(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "app_dir", lambda: tmp_path)

    assert paths.chat_dir() == tmp_path / "chat"
    assert paths.updates_dir() == tmp_path / "updates"
    assert paths.default_project_dir() == tmp_path

    created = paths.ensure_chat_dir()

    assert created == tmp_path / "chat"
    assert created.is_dir()
    assert paths.default_project_dir() == created


def test_frozen_macos_uses_application_support(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(
        paths.Path, "home", classmethod(lambda cls: tmp_path)
    )

    assert (
        paths.app_dir()
        == tmp_path / "Library" / "Application Support" / "AgentBell"
    )
    assert paths.config_file() == paths.app_dir() / "config.json"
    assert paths.logs_dir() == paths.app_dir() / "logs"


def test_frozen_windows_keeps_portable_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(
        paths.sys, "executable", str(tmp_path / "AgentBell.exe")
    )

    assert paths.app_dir() == tmp_path
