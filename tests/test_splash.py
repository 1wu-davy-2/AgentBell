from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agentbell.ui.splash import SplashWindow, splash_lines

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_first_launch_and_reopen_lines():
    first = splash_lines(8765, first_run=True, open_center=True)
    assert first == (
        "正在唤起本机服务",
        "127.0.0.1:8765 · 已连接",
        "准备第一次介绍",
    )

    reopen = splash_lines(8765, first_run=False, open_center=True)
    assert reopen[-1] == "正在打开通知中心"

    tray = splash_lines(8765, first_run=False, open_center=False)
    assert tray[-1] == "AgentBell 已在托盘运行"


def test_splash_advances_lines_and_finishes_once(qapp):
    splash = SplashWindow(18765, first_run=False, animate=False)
    calls: list[int] = []
    splash.finished.connect(lambda: calls.append(1))
    splash.show()
    QTest.qWait(30)

    assert splash.current_line == "正在唤起本机服务"
    splash._apply_elapsed(700)
    assert splash.current_line == "127.0.0.1:18765 · 已连接"
    splash._apply_elapsed(1400)
    assert splash.current_line == "正在打开通知中心"
    assert splash._progress.value() > 0

    splash.finish()
    splash.finish()
    assert calls == [1]
    assert not splash.isVisible()
    splash.deleteLater()


def test_splash_progress_reaches_full_on_finish(qapp):
    splash = SplashWindow(18765, first_run=True, animate=False)
    splash.show()
    QTest.qWait(20)
    splash.finish()
    assert splash._progress.value() == 100
    assert splash.current_line == "准备第一次介绍"
    splash.deleteLater()
