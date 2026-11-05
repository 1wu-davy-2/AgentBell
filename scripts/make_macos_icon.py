#!/usr/bin/env python3
"""Render AgentBell's SVG mark into a macOS .icns bundle."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

ICONSET_SIZES = (16, 32, 128, 256, 512)


def iconset_entries() -> list[tuple[int, int]]:
    return [(size, scale) for size in ICONSET_SIZES for scale in (1, 2)]


def iconset_name(size: int, scale: int) -> str:
    suffix = "@2x" if scale == 2 else ""
    return f"icon_{size}x{size}{suffix}.png"


def render_iconset(svg: Path, iconset: Path) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    app = QGuiApplication.instance() or QGuiApplication([])
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise SystemExit(f"无法读取 SVG：{svg}")
    iconset.mkdir(parents=True, exist_ok=True)
    for size, scale in iconset_entries():
        pixels = size * scale
        image = QImage(
            pixels, pixels, QImage.Format.Format_ARGB32_Premultiplied
        )
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter, QRectF(0, 0, pixels, pixels))
        painter.end()
        target = iconset / iconset_name(size, scale)
        if not image.save(str(target), "PNG"):
            raise SystemExit(f"无法写入 {target}")
    del app


def build_icns(
    svg: Path,
    destination: Path,
    *,
    iconutil: str = "iconutil",
) -> Path:
    iconset = destination.with_suffix(".iconset")
    if iconset.exists():
        shutil.rmtree(iconset)
    render_iconset(svg, iconset)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    try:
        subprocess.run(
            [iconutil, "-c", "icns", str(iconset), "-o", str(destination)],
            check=True,
        )
    finally:
        shutil.rmtree(iconset, ignore_errors=True)
    return destination


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--svg", type=Path, default=Path("assets/agentbell.svg")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("assets/agentbell.icns")
    )
    parser.add_argument("--iconutil", default="iconutil")
    args = parser.parse_args(argv)
    if not args.svg.is_file():
        parser.error(f"找不到 SVG：{args.svg}")
    created = build_icns(
        args.svg, args.out, iconutil=args.iconutil
    )
    print(f"{created}  {created.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
