from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from agentbell.config import OverlayAreaConfig
from agentbell.models import (
    OVERLAY_ANCHORS,
    OVERLAY_OFFSET_LIMIT,
    overlay_anchor_for_rect,
    overlay_anchor_origin,
    overlay_effective_margin,
)
from agentbell.ui.overlay_editor import OverlayAreaEditor

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_effective_margin_is_clamped():
    assert overlay_effective_margin(-5, 1920, 1080) == 0
    assert overlay_effective_margin(1000, 1920, 1080) == 460
    assert overlay_effective_margin(32, 300, 200) == 20


def test_anchor_roundtrip_keeps_each_anchor():
    width, height = 1920, 1080
    card_width, card_height = 540, 300
    margin = 32
    for anchor in OVERLAY_ANCHORS:
        x, y = overlay_anchor_origin(
            anchor, width, height, card_width, card_height, margin
        )
        mapped, dx, dy = overlay_anchor_for_rect(
            width,
            height,
            x + 7,
            y - 5,
            card_width,
            card_height,
            margin,
            anchor,
        )
        assert mapped == anchor
        assert (dx, dy) == (7, -5)


def test_anchor_mapping_clamps_position_and_offsets():
    anchor, dx, dy = overlay_anchor_for_rect(
        1920, 1080, 5000, 5000, 540, 300, 32, "center"
    )
    assert anchor == "bottom_right"
    assert abs(dx) <= OVERLAY_OFFSET_LIMIT
    assert abs(dy) <= OVERLAY_OFFSET_LIMIT
    origin = overlay_anchor_origin("bottom_right", 1920, 1080, 540, 300, 32)
    assert (origin[0] + dx, origin[1] + dy) == (1380, 780)


def test_editor_saves_dragged_geometry_as_anchor(qapp):
    editor = OverlayAreaEditor(
        OverlayAreaConfig(anchor="center", width=520, margin=28)
    )
    try:
        editor.resize(1280, 720)
        editor.show()
        QTest.qWait(40)
        editor._card.setGeometry(QRect(30, 36, 520, 260))
        saved: list[OverlayAreaConfig] = []
        editor.area_saved.connect(saved.append)

        editor._save()

        area = editor.result_area
        assert area is not None
        assert saved == [area]
        assert area.anchor == "top_left"
        assert (area.offset_x, area.offset_y) == (2, 8)
        assert area.width == 520
        assert area.margin == 28
    finally:
        editor.deleteLater()
        QTest.qWait(20)


def test_editor_cancels_when_backdrop_has_no_size(qapp):
    editor = OverlayAreaEditor(OverlayAreaConfig(anchor="center"))
    try:
        editor._backdrop.resize(0, 0)
        editor._save()
        assert editor.result_area is None
    finally:
        editor.deleteLater()
        QTest.qWait(20)
