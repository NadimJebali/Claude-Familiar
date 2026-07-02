"""One pixel-grid primitive: walk / paint / validate a char-grid + palette (#39).

The blocky pixel art across the app is all the same shape — a list of equal-length
strings where every non-``.`` char indexes a color: creature bodies & faces, wardrobe
hats, the gravestone and mood emotes (``sprite_pixel``), shop-item icons (``item_art``),
and the ttk UI glyphs (``ui_icons``). This module owns the three things each of those
used to hand-roll: walk the lit cells (:func:`grid_cells`), paint them centered on a
canvas (:func:`draw_grid`), and check a grid is well-formed (:func:`validate_grid`).

``ui_icons`` rasterizes to a ``PhotoImage`` rather than a canvas, so it shares the walk
but keeps its own ``put``; the canvas painters share all of it.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk


def grid_cells(grid: list[str]) -> Iterator[tuple[int, int, str]]:
    """Yield ``(col, row, ch)`` for every lit (non-``.``) cell, row by row."""
    for row, line in enumerate(grid):
        for col, ch in enumerate(line):
            if ch != ".":
                yield col, row, ch


def draw_grid(c: tk.Canvas, grid: list[str], colors: Mapping[str, str],
              cx: float, cy: float, px: int, tag: str) -> None:
    """Paint ``grid`` centered at ``(cx, cy)``, one ``px``-sized square per lit cell
    filled from ``colors``. The shared canvas painter behind the creature parts,
    wardrobe hats, mood emotes, and shop-item icons."""
    x0 = cx - (len(grid[0]) * px) / 2
    y0 = cy - (len(grid) * px) / 2
    for col, row, ch in grid_cells(grid):
        x, y = x0 + col * px, y0 + row * px
        c.create_rectangle(x, y, x + px, y + px, fill=colors[ch], outline="", tags=tag)


def validate_grid(grid: list[str], *, colors: Mapping[str, str] | None = None,
                  size: int | None = None, name: str = "grid") -> None:
    """Assert ``grid`` is well-formed, naming ``name`` on the first fault: rectangular
    (every row as wide as the first), optionally a fixed ``size`` square, and — when
    ``colors`` is given — using only palette chars (plus ``.``). One check reused by
    every registry's import-time validation."""
    w = len(grid[0])
    assert all(len(r) == w for r in grid), f"{name}: ragged rows"
    if size is not None:
        assert len(grid) == size and w == size, f"{name}: not {size}x{size}"
    if colors is not None:
        allowed = {*colors, "."}
        for r in grid:
            assert set(r) <= allowed, f"{name}: unknown cell in {r!r}"
