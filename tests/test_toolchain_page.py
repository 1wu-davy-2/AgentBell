from __future__ import annotations

import json
import logging
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from agentbell.config import ToolchainConfig
from agentbell.ui.toolchain_page import ToolchainPage


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def _make_page(tmp_path, home):
    app_root = tmp_path / "app"
    runtime = app_root / "runtime"
    runtime.mkdir(parents=True)
    return ToolchainPage(
        runtime,
        ToolchainConfig(),
        logging.getLogger("agentbell.tests.toolchain"),
        hooks_home=home,
        hooks_confirm=lambda *_: True,
    )


def _prepare_home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".gemini").mkdir()
    (home / ".grok").mkdir()
    return home


def test_hooks_panel_install_and_undo_from_runtime_page(qapp, tmp_path):
    home = _prepare_home(tmp_path)
    user_hook = {"hooks": [{"type": "command", "command": "my-hook"}]}
    settings = home / ".claude" / "settings.json"
    settings.write_text(
        json.dumps({"model": "sonnet", "hooks": {"Stop": [user_hook]}}),
        encoding="utf-8",
    )

    page = _make_page(tmp_path, home)
    panel = page._hooks_panel
    row = panel._rows["claude"]
    assert row._state.text() == "未接入"

    row._install_button.click()
    assert row._state.text() == "已接入"
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "sonnet"
    assert data["hooks"]["Stop"][0] == user_hook
    commands = [
        handler["command"]
        for group in data["hooks"]["Stop"]
        for handler in group["hooks"]
    ]
    assert any("agentbell-hook.ps1" in command for command in commands)
    helper = tmp_path / "app" / "hooks" / "agentbell-hook.ps1"
    assert helper.is_file()

    row._remove_button.click()
    assert row._state.text() == "未接入"
    restored = json.loads(settings.read_text(encoding="utf-8"))
    assert restored == {"model": "sonnet", "hooks": {"Stop": [user_hook]}}


def test_hooks_panel_marks_codex_notify_conflict(qapp, tmp_path):
    home = _prepare_home(tmp_path)
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    original = 'model = "gpt-5"\nnotify = ["my-notifier"]\n'
    config.write_text(original, encoding="utf-8")

    page = _make_page(tmp_path, home)
    row = page._hooks_panel._rows["codex"]
    assert row._state.text() == "需处理"
    assert row._install_button.text() == "需处理"
    assert not row._install_button.isEnabled()
    assert "notify" in row._problem.text()
    assert not row._problem.isHidden()
    assert config.read_text(encoding="utf-8") == original


def test_hooks_panel_marks_stale_codex_marker(qapp, tmp_path):
    home = _prepare_home(tmp_path)
    config = home / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('# agentbell-hook (manual)\nmodel = "gpt-5"\n', encoding="utf-8")

    page = _make_page(tmp_path, home)
    row = page._hooks_panel._rows["codex"]
    assert row._state.text() == "需处理"
    assert "手动" in row._problem.text()
    assert not row._remove_button.isVisible()
    assert not row._install_button.isVisible()


def test_hooks_panel_install_all_skips_partial_codex(qapp, tmp_path):
    home = _prepare_home(tmp_path)
    codex = home / ".codex" / "config.toml"
    codex.parent.mkdir()
    codex.write_text('model = "gpt-5"\n', encoding="utf-8")

    page = _make_page(tmp_path, home)
    panel = page._hooks_panel
    messages = []
    panel.status_message.connect(lambda message, error: messages.append((message, error)))

    panel._install_all_button.click()

    for agent_id in ("claude", "gemini", "grok"):
        assert panel._rows[agent_id]._state.text() == "已接入"
    assert panel._rows["codex"]._state.text() == "未接入"
    assert "agentbell-hook" not in codex.read_text(encoding="utf-8")
    assert messages and messages[-1][1] is False
