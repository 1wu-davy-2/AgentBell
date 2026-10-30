from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from agentbell.ui import icons

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    yield app


def test_mark_svg_uses_brand_colors_and_can_be_recolored():
    svg = icons.mark_svg()
    assert 'viewBox="0 0 64 64"' in svg
    assert "#2F6BFF" in svg
    assert "#FFFFFF" in svg
    assert "<circle" in svg and "<path" in svg

    mono = icons.mark_svg(icons.MARK_MONO_PRIMARY, "#F4F6F9")
    assert icons.MARK_MONO_PRIMARY in mono
    assert "#F4F6F9" in mono


def test_mark_pixmap_is_transparent_outside_the_circle(qapp):
    pixmap = icons.mark_pixmap(64)
    image = pixmap.toImage()

    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(63, 0).alpha() == 0
    assert image.pixelColor(32, 8) == QColor("#2F6BFF")
    assert image.pixelColor(32, 32) == QColor("#FFFFFF")
    assert image.pixelColor(32, 49) == QColor("#FFFFFF")


def test_mono_mark_swaps_circle_color(qapp):
    pixmap = icons.mark_pixmap(32, primary=icons.MARK_MONO_PRIMARY)
    image = pixmap.toImage()
    assert image.pixelColor(16, 4) == QColor(icons.MARK_MONO_PRIMARY)


def test_make_app_icon_contains_required_sizes(qapp):
    icon = icons.make_app_icon()
    sizes = {size.width() for size in icon.availableSizes()}
    assert {16, 24, 32, 48, 64, 128, 256} <= sizes
    assert not icon.isNull()


def test_alert_icon_keeps_badge_visible(qapp):
    icon = icons.make_alert_icon()
    assert not icon.isNull()
    image = icon.pixmap(64, 64).toImage()
    assert image.pixelColor(49, 15).alpha() > 0
