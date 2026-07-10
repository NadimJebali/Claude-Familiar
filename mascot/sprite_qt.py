"""Qt pixel-sprite renderer — the SpriteRenderer seam's first implementation.

The migration renders the SAME 16x16 pixel grids the Tk view uses (the single
source of truth in ``sprite_pixel``), but to **cached QPixmaps** the Qt card can
blit, rather than re-creating canvas rectangles on every change. Sprite drawing
sits behind the :class:`SpriteRenderer` protocol so an alternate art style (e.g.
a vector skin) can be added later as a second implementation without touching the
card or the game logic — the seam is built here, the second renderer is not.

Grids are **integer-scaled** — one filled rect per lit cell at ``px`` size — so
pixels stay crisp at any size (never smooth-scaled). Rendering goes through a
QImage first, which needs no display, so the core is headless-testable; the public
pixmaps are a thin ``QPixmap.fromImage`` the card consumes under its QApplication.

Migration note: the grid data is imported from ``sprite_pixel``, which still hosts
the Tk draw functions too. At the Tk cutover (#63) that pure data moves to its own
module and this import updates — the renderer already only touches the data, never
the Tk drawing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap

from . import sprite_pixel
from .pixel_grid import grid_cells

# A margin (in cells) around the 16x16 creature so a tall hat (overhangs the head
# by ~3 cells) or a corner flourish isn't clipped. The creature is centered in the
# padded square, and everything is placed relative to that.
MARGIN = 3
_CANVAS = sprite_pixel.GRID_W + 2 * MARGIN   # 22 cells square


@dataclass(frozen=True)
class SpriteSpec:
    """The composed creature look to render.

    ``accent`` is the ``#rrggbb`` the sparkle (``'a'``) cells take — the card
    passes the state color. ``hat`` is a wardrobe id or None; ``flourish`` adds
    the milestone sparkle at the corners.
    """

    stage: str
    state: str
    accent: str
    hat: str | None = None
    flourish: bool = False


class SpriteRenderer(Protocol):
    """Produces blit-ready pixmaps for the card. The pixel implementation reads
    grids; a future vector skin would read paths — both output a QPixmap, so the
    card is written once against this protocol."""

    def creature(self, spec: SpriteSpec, px: int) -> QPixmap: ...

    def gravestone(self, px: int) -> QPixmap: ...


class QtPixmapRenderer:
    """A :class:`SpriteRenderer` that rasterizes the pixel grids to cached QPixmaps.

    Each (spec, px) — and the gravestone per px — is rendered once and reused, so
    an unchanged look costs nothing after the first paint.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[object, ...], QPixmap] = {}

    def creature(self, spec: SpriteSpec, px: int) -> QPixmap:
        key = ("creature", spec.stage, spec.state, spec.accent, spec.hat, spec.flourish, px)
        pm = self._cache.get(key)
        if pm is None:
            pm = QPixmap.fromImage(self._creature_image(spec, px))
            self._cache[key] = pm
        return pm

    def gravestone(self, px: int) -> QPixmap:
        key = ("gravestone", px)
        pm = self._cache.get(key)
        if pm is None:
            pm = QPixmap.fromImage(self._grave_image(px))
            self._cache[key] = pm
        return pm

    # --- rendering core (QImage; needs no display) -----------------------
    def _blank(self, px: int) -> QImage:
        img = QImage(_CANVAS * px, _CANVAS * px, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        return img

    def _paint_grid(self, p: QPainter, grid: list[str], colors, *,
                    x0: int, y0: int, px: int, accent: str | None = None,
                    egg: bool = False) -> None:
        spot = sprite_pixel.EGG_SPECKLE if egg else accent
        for col, row, ch in grid_cells(grid):
            color = spot if ch == "a" else colors[ch]
            p.fillRect(x0 + col * px, y0 + row * px, px, px, QColor(color))

    def _creature_image(self, spec: SpriteSpec, px: int) -> QImage:
        img = self._blank(px)
        p = QPainter(img)
        try:
            base = MARGIN * px   # top-left of the 16x16 creature in the padded canvas
            self._paint_grid(
                p, sprite_pixel.grid_for(spec.stage, spec.state), sprite_pixel.COLORS,
                x0=base, y0=base, px=px,
                accent=spec.accent, egg=(spec.stage == "egg"),
            )
            if spec.hat:
                self._paint_hat(p, spec.hat, spec.stage, px, base)
            if spec.flourish:
                self._paint_flourish(p, spec.accent, px, base)
        finally:
            p.end()
        return img

    def _grave_image(self, px: int) -> QImage:
        img = self._blank(px)
        p = QPainter(img)
        try:
            base = MARGIN * px
            self._paint_grid(p, sprite_pixel._GRAVE, sprite_pixel.GRAVE_COLORS,
                             x0=base, y0=base, px=px)
        finally:
            p.end()
        return img

    def _paint_hat(self, p: QPainter, hat_id: str, stage: str, px: int, base: int) -> None:
        hat = sprite_pixel._HATS.get(hat_id)
        if hat is None or stage == "egg":   # the egg wears nothing (mirrors draw_hat)
            return
        grid, colors = hat["grid"], hat["colors"]
        anchor = sprite_pixel._HAT_ANCHOR_ROW.get(stage, 3)
        # The hat's bottom row sits on the head-outline row; it grows upward, so the
        # top row can be above the creature — the margin absorbs the overhang.
        y0 = base + (anchor - len(grid) + 1) * px
        x0 = base + (sprite_pixel.GRID_W - len(grid[0])) * px // 2   # centered
        self._paint_grid(p, grid, colors, x0=x0, y0=y0, px=px)

    def _paint_flourish(self, p: QPainter, accent: str, px: int, base: int) -> None:
        # Sparkle cells at fixed offsets from the creature center (mirrors
        # sprite_pixel._draw_flourish); offsets are whole cells, so they align to
        # the pixel grid.
        cx = base + sprite_pixel.GRID_W * px // 2
        cy = base + sprite_pixel.GRID_H * px // 2
        color = QColor(accent)
        for gx, gy in sprite_pixel._FLOURISH:
            p.fillRect(cx + gx * px, cy + gy * px, px, px, color)
