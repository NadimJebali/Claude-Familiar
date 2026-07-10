#!/usr/bin/env python3
"""Generate the README showcase images straight from the mascot's own art.

The widget renders its creature from `sprite_pixel.grid_for(stage, state)` (16x16
character grids) tinted by `config.STATE_COLORS`. This script bakes polished PNG
"filmstrips" for the README — a row of tiles, each a creature glowing in its state
accent on a dark desktop-slate card — through the **same Qt renderer the widget
uses** (`sprite_qt.QtPixmapRenderer`), so the docs can never drift from the real
sprite. Re-run after editing the sprite:

    python scripts/gen_readme_art.py

Dev-only. Renders headless (forces the Qt "offscreen" platform) and composites
with QPainter/QImage — no Pillow, no display needed. Output: docs/images/*.png
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Render with no display: must be set before any Qt module is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPixmap,
    QRadialGradient,
)

from mascot import config
from mascot.sprite_qt import QtPixmapRenderer, SpriteSpec

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"

TILE = 160                      # square tile per creature
RADIUS = 26                     # rounded-card corner
GAP = 14                        # transparent gap between tiles
SLATE = QColor(32, 30, 41, 255)  # dark "desktop screen" the pet glows on
PAD = GAP                       # outer padding of a strip

# Base creature size (px per cell); stages scale relative to it so evolution shows
# real growth. These match the old Pillow strip exactly.
_BASE = 7
_STAGE_SCALE = {"egg": 5, "baby": 6, "teen": 7, "adult": 9}


def _accent(state: str) -> str:
    """The state accent as ``#rrggbb`` — the format the renderer expects for the
    sparkle (``'a'``) cells (mirrors ``sprite_gallery._accent``)."""
    r, g, b = config.STATE_COLORS.get(state, config.STATE_COLORS["idle"])
    return f"#{r:02x}{g:02x}{b:02x}"


def _creature(renderer: QtPixmapRenderer, stage: str, state: str, px: int) -> QPixmap:
    """The pixel creature (or gravestone) as a crisp, integer-scaled pixmap — the
    exact art the live card blits, so the README can't drift from it."""
    if state == "dead":
        return renderer.gravestone(px)
    return renderer.creature(SpriteSpec(stage=stage, state=state, accent=_accent(state)), px)


def _tile(renderer: QtPixmapRenderer, stage: str, state: str, px: int) -> QImage:
    """One rounded slate card: a soft accent glow behind the glowing creature.

    The Gaussian-blurred ellipse the Pillow version used is replaced by a native
    :class:`QRadialGradient` — a solid-ish core fading to transparent — which needs
    no blur filter and stays crisp at any size.
    """
    accent = _accent(state)
    img = QImage(TILE, TILE, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    try:
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = QPainterPath()
        card.addRoundedRect(QRectF(0, 0, TILE, TILE), RADIUS, RADIUS)
        p.setClipPath(card)          # keep the glow + any overhang inside the card
        p.fillPath(card, SLATE)

        c = TILE / 2
        glow = QRadialGradient(c, c, TILE * 0.5)
        for stop, alpha in ((0.0, 150), (0.35, 110), (1.0, 0)):
            tone = QColor(accent)
            tone.setAlpha(alpha)
            glow.setColorAt(stop, tone)
        p.fillRect(0, 0, TILE, TILE, glow)

        pm = _creature(renderer, stage, state, px)
        # The renderer centers the creature in a padded canvas, so centering the
        # pixmap centers the creature; any transparent overhang is clipped by the
        # card path. Integer coords keep the pixels crisp (no resampling).
        x = int((TILE - pm.width()) / 2)
        y = int((TILE - pm.height()) / 2) - 2
        p.drawPixmap(QPointF(x, y), pm)
    finally:
        p.end()
    return img


def _strip(name: str, tiles: list[QImage]) -> Path:
    """Lay tiles in a horizontal row with transparent gaps; save to docs/images."""
    width = PAD * 2 + len(tiles) * TILE + (len(tiles) - 1) * GAP
    strip = QImage(width, TILE + PAD * 2, QImage.Format.Format_ARGB32_Premultiplied)
    strip.fill(Qt.GlobalColor.transparent)
    p = QPainter(strip)
    try:
        x = PAD
        for tile in tiles:
            p.drawImage(x, PAD, tile)
            x += TILE + GAP
    finally:
        p.end()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    strip.save(str(path))
    return path


def main() -> None:
    QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QtPixmapRenderer()

    # The Claude-activity faces, each in its state accent (the hero strip).
    states = ["idle", "thinking", "working", "waiting", "happy", "sleeping"]
    _strip("states", [_tile(renderer, "baby", s, _BASE) for s in states])

    # The expressive faces: per-tool working looks, plan mode, compaction, the
    # post-error stumble, and the pixel gravestone.
    expressions = ["working_read", "working_edit", "working_run", "working_web",
                   "planning", "compacting", "stumble", "dead"]
    _strip("expressions", [_tile(renderer, "baby", s, _BASE) for s in expressions])

    # egg -> baby -> teen -> adult, growing as it goes.
    stages = ["egg", "baby", "teen", "adult"]
    _strip("evolution", [_tile(renderer, stage, "idle", _STAGE_SCALE[stage]) for stage in stages])

    # Tamagotchi idle moods (driven by the pet's needs).
    moods = ["idle_happy", "idle_hungry", "idle_tired", "idle_sad"]
    _strip("moods", [_tile(renderer, "baby", m, _BASE) for m in moods])

    for png in sorted(OUT_DIR.glob("*.png")):
        print("wrote", png.relative_to(OUT_DIR.parent.parent), f"({png.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
