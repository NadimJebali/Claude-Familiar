"""One pixel-grid primitive: walk / validate a char-grid + palette (#39).

The blocky pixel art across the app is all the same shape — a list of equal-length
strings where every non-``.`` char indexes a color: creature bodies & faces, wardrobe
hats, the gravestone and mood emotes (``sprite_pixel``), shop-item icons (``item_art``),
and the UI glyphs (``ui_icons``). This module owns the two pure things each of those
used to hand-roll: walk the lit cells (:func:`grid_cells`) and check a grid is
well-formed (:func:`validate_grid`). The Qt renderer (:mod:`mascot.pixel_qt`) does the
actual rasterizing to a ``QPixmap``.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping


def grid_cells(grid: list[str]) -> Iterator[tuple[int, int, str]]:
    """Yield ``(col, row, ch)`` for every lit (non-``.``) cell, row by row."""
    for row, line in enumerate(grid):
        for col, ch in enumerate(line):
            if ch != ".":
                yield col, row, ch


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
