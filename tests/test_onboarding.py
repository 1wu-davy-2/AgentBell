from __future__ import annotations

import logging
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from agentbell.config import AppConfig
from agentbell.store import NotificationStore
from agentbell.ui.onboarding import AUTO_ADVANCE_MS, OnboardingOverlay, onboarding_steps
from agentbell.ui.window import NotificationWindow

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


@pytest.fixture
def overlay_factory(qapp):
    overlays: list[OnboardingOverlay] = []
    parents: list[QWidget] = []

    def create(*, auto: bool = False) -> OnboardingOverlay:
        parent = QWidget()
        parent.resize(900, 640)
        parents.append(parent)
        overlay = OnboardingOverlay(parent, hotkey="Ctrl+Alt+A", animate=False, auto=auto)
        overlays.append(overlay)
        parent.show()
        overlay.show()
        return overlay

    yield create

    for overlay in overlays:
        overlay.hide()
        overlay.deleteLater()
    for parent in parents:
        parent.hide()
        parent.deleteLater()
    QTest.qWait(30)


def test_steps_include_hotkey_and_fallback():
    steps = onboarding_steps("Ctrl+Alt+A")
    assert len(steps) == 4
    assert steps[0][0] == "只读"
    assert "Ctrl+Alt+A" in steps[3][2]
    fallback = onboarding_steps("   ")
    assert "点托盘图标" in fallback[3][2]


def test_navigation_buttons_and_skip_emits_once(overlay_factory):
    overlay = overlay_factory()
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))
    assert overlay.step_count == 4
    assert overlay.current_step == 0
    assert not overlay._prev.isEnabled()
    assert overlay._next.text() == "下一步"
    assert overlay._count_label.text() == "1 / 4"

    overlay.next_step()
    assert overlay.current_step == 1
    assert overlay._prev.isEnabled()
    assert overlay._count_label.text() == "2 / 4"

    overlay.go_to_step(3)
    assert overlay._next.text() == "进入通知中心"
    overlay.previous_step()
    assert overlay.current_step == 2

    overlay.skip()
    QTest.qWait(10)
    assert finished == [True]
    assert not overlay.isVisible()
    overlay.skip()
    QTest.qWait(10)
    assert finished == [True]


def test_auto_toggle_and_hide_pause(overlay_factory):
    overlay = overlay_factory(auto=True)
    assert overlay.auto_playing is True
    assert overlay._auto_timer.isActive()
    assert overlay._auto_timer.interval() == AUTO_ADVANCE_MS

    overlay.toggle_auto()
    assert overlay.auto_playing is False
    assert overlay._auto_button.text() == "继续播放"
    assert not overlay._auto_timer.isActive()

    overlay.toggle_auto()
    assert overlay.auto_playing is True
    assert overlay._auto_timer.isActive()

    overlay.hide()
    assert not overlay._auto_timer.isActive()
    overlay.show()
    assert overlay._auto_timer.isActive()
    overlay.skip()


def test_auto_advance_walks_to_completion(overlay_factory):
    overlay = overlay_factory(auto=True)
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))
    for expected in (1, 2, 3):
        overlay._advance_auto()
        assert overlay.current_step == expected
    overlay._advance_auto()
    QTest.qWait(10)
    assert finished == [True]
    assert not overlay._auto_timer.isActive()


def test_keyboard_navigation_and_escape(overlay_factory):
    overlay = overlay_factory()
    finished: list[bool] = []
    overlay.finished.connect(lambda: finished.append(True))
    QTest.keyClick(overlay, Qt.Key.Key_Right)
    assert overlay.current_step == 1
    QTest.keyClick(overlay, Qt.Key.Key_Return)
    assert overlay.current_step == 2
    QTest.keyClick(overlay, Qt.Key.Key_Left)
    assert overlay.current_step == 1
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    QTest.qWait(10)
    assert finished == [True]


def test_window_hosts_and_cleans_up_onboarding(qapp):
    window = NotificationWindow(
        AppConfig(port=18766, token="test"),
        NotificationStore(),
        logging.getLogger("agentbell.tests"),
    )
    try:
        assert window.start_onboarding() is None
        window.show()
        overlay = window.start_onboarding()
        assert overlay is not None
        assert overlay.isVisible()
        assert overlay.geometry() == window._root.rect()
        finished: list[bool] = []
        window.onboarding_finished.connect(lambda: finished.append(True))

        overlay.skip()
        QTest.qWait(30)
        assert finished == [True]
        assert window._onboarding is None
    finally:
        window.shutdown()
        window.deleteLater()
        QTest.qWait(20)


def test_finish_onboarding_persists_seen_flag(tmp_path, monkeypatch):
    import agentbell.app as app_module
    from agentbell.app import AgentBellApp

    path = tmp_path / "config.json"
    saved = []

    def fake_save(target, config):
        saved.append((target, config))

    monkeypatch.setattr(app_module, "save_config", fake_save)

    class FakeCenter:
        def __init__(self) -> None:
            self.applied: list[AppConfig] = []

        def apply_config(self, config: AppConfig) -> None:
            self.applied.append(config)

    center = FakeCenter()
    owner = SimpleNamespace(
        config=AppConfig(port=18766),
        config_path=path,
        logger=logging.getLogger("agentbell.tests"),
        center=center,
    )

    AgentBellApp._finish_onboarding(owner)
    assert owner.config.onboarding_seen is True
    assert len(saved) == 1
    assert saved[0][0] == path
    assert saved[0][1].onboarding_seen is True
    assert len(center.applied) == 1

    AgentBellApp._finish_onboarding(owner)
    assert len(saved) == 1


def test_finish_onboarding_without_path_does_not_write(monkeypatch):
    import agentbell.app as app_module
    from agentbell.app import AgentBellApp

    calls: list[object] = []
    monkeypatch.setattr(
        app_module, "save_config", lambda *args: calls.append(args)
    )

    class FakeCenter:
        def apply_config(self, config: AppConfig) -> None:
            pass

    owner = SimpleNamespace(
        config=AppConfig(port=18766),
        config_path=None,
        logger=logging.getLogger("agentbell.tests"),
        center=FakeCenter(),
    )
    AgentBellApp._finish_onboarding(owner)
    assert owner.config.onboarding_seen is True
    assert calls == []
