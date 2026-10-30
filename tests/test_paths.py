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
