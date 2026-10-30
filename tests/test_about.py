from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QPushButton
from PySide6.QtTest import QTest

from agentbell.ui.about import AboutDialog

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_about_dialog_layout(qapp):
    dialog = AboutDialog(animate=False)
    try:
        assert dialog.windowTitle() == "关于 AgentBell"
        assert dialog.logo is not None
        assert dialog.minimumWidth() >= 640
        tiles = dialog.findChildren(QFrame, "aboutTile")
        assert len(tiles) == 7
        buttons = [button.text() for button in dialog.findChildren(QPushButton)]
        assert "重响" in buttons
        assert "保存 SVG…" in buttons
        assert "关闭" in buttons
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_export_svg_writes_mark(qapp, tmp_path):
    dialog = AboutDialog(animate=False)
    try:
        target = tmp_path / "mark.svg"
        dialog.export_svg(target)
        content = target.read_text(encoding="utf-8")
        assert content.startswith("<svg")
        assert 'viewBox="0 0 64 64"' in content
        assert 'fill="#2F6BFF"' in content
        assert "circle" in content
    finally:
        dialog.deleteLater()
        QTest.qWait(20)


def test_choose_svg_appends_extension_and_reports(qapp, tmp_path, monkeypatch):
    import agentbell.ui.about as about_module

    dialog = AboutDialog(animate=False)
    requested = tmp_path / "chosen-mark"
    monkeypatch.setattr(
        about_module.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: (str(requested), "SVG 图像 (*.svg)")),
    )
    try:
        dialog._choose_svg()
        target = requested.with_suffix(".svg")
        assert target.exists()
        assert dialog._status.text() == f"已保存到 {target}"
        assert dialog._status_timer.isActive()
    finally:
        dialog._status_timer.stop()
        dialog.deleteLater()
        QTest.qWait(20)


def test_choose_svg_cancel_does_not_write(qapp, tmp_path, monkeypatch):
    import agentbell.ui.about as about_module

    dialog = AboutDialog(animate=False)
    monkeypatch.setattr(
        about_module.QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *args, **kwargs: ("", "")),
    )
    try:
        dialog._choose_svg()
        assert dialog._status.text() == ""
        assert not list(tmp_path.iterdir())
    finally:
        dialog.deleteLater()
        QTest.qWait(20)
