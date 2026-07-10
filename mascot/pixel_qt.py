"""Rasterize a pixel-art char-grid + palette to a QPixmap — the Qt counterpart to
:func:`mascot.pixel_grid.draw_grid` (which paints the same grids to a Tk canvas).

Shared by the Qt card's paw icon and the Qt Pet window's item / hat icons, so the
one grid->pixmap loop isn't hand-rolled in each. Integer-scaled (one filled square
per lit cell) so pixels stay crisp, on a transparent canvas.
"""
from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from .pixel_grid import grid_cells


def grid_pixmap(grid: list[str], colors: Mapping[str, str], px: int) -> QPixmap:
    """Render ``grid`` to a QPixmap at ``px`` pixels per cell, each lit cell filled
    from ``colors`` (unlit ``.`` cells stay transparent)."""
    img = QImage(len(grid[0]) * px, len(grid) * px,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        for col, row, ch in grid_cells(grid):
            painter.fillRect(col * px, row * px, px, px, QColor(colors[ch]))
    finally:
        painter.end()
    return QPixmap.fromImage(img)
