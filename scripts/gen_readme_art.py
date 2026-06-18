#!/usr/bin/env python3
"""Generate the README showcase images straight from the mascot's own art.

The widget renders its creature from `sprite_pixel.grid_for(stage, state)` (16x16
character grids) tinted by `config.STATE_COLORS`. This script reuses that exact
source of truth to bake polished PNG "filmstrips" for the README — a row of tiles,
each a creature glowing in its state accent on a dark desktop-slate card — so the
docs can never drift from the real sprite. Re-run after editing the sprite:

    python scripts/gen_readme_art.py

Dev-only (uses Pillow, already a runtime dep). Output: docs/images/*.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mascot import config
from mascot import sprite_pixel as sp

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"

TILE = 160                      # square tile per creature
RADIUS = 26                     # rounded-card corner
GAP = 14                        # transparent gap between tiles
SLATE = (32, 30, 41, 255)       # dark "desktop screen" the pet glows on
PAD = GAP                       # outer padding of a strip


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _creature(stage: str, state: str, accent: tuple[int, int, int], scale: int) -> Image.Image:
    """The pixel creature as a transparent RGBA image, NEAREST-upscaled by `scale`."""
    grid = sp.grid_for(stage, state)
    base = Image.new("RGBA", (sp.GRID_W, sp.GRID_H), (0, 0, 0, 0))
    px = base.load()
    spot = _rgb(sp.EGG_SPECKLE) if stage == "egg" else accent
    for y, row in enumerate(grid):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            color = spot if ch == "a" else _rgb(sp.COLORS[ch])
            px[x, y] = (*color, 255)
    return base.resize((sp.GRID_W * scale, sp.GRID_H * scale), Image.NEAREST)


def _tile(stage: str, state: str, scale: int) -> Image.Image:
    """One rounded slate card: an accent glow behind the glowing creature."""
    accent = config.STATE_COLORS.get(state, config.STATE_COLORS["idle"])
    card = Image.new("RGBA", (TILE, TILE), SLATE)

    glow = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    r = TILE * 0.30
    c = TILE / 2
    ImageDraw.Draw(glow).ellipse([c - r, c - r, c + r, c + r], fill=(*accent, 150))
    card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(22)))

    creature = _creature(stage, state, accent, scale)
    card.alpha_composite(creature, (TILE // 2 - creature.width // 2,
                                    TILE // 2 - creature.height // 2 - 2))

    mask = Image.new("L", (TILE, TILE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, TILE - 1, TILE - 1], radius=RADIUS, fill=255)
    out = Image.new("RGBA", (TILE, TILE), (0, 0, 0, 0))
    out.paste(card, (0, 0), mask)
    return out


def _strip(name: str, tiles: list[Image.Image]) -> Path:
    """Lay tiles in a horizontal row with transparent gaps; save to docs/images."""
    width = PAD * 2 + len(tiles) * TILE + (len(tiles) - 1) * GAP
    strip = Image.new("RGBA", (width, TILE + PAD * 2), (0, 0, 0, 0))
    x = PAD
    for tile in tiles:
        strip.alpha_composite(tile, (x, PAD))
        x += TILE + GAP
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.png"
    strip.save(path)
    return path


# Base creature size; stages scale relative to it so evolution shows real growth.
_BASE = 7
_STAGE_SCALE = {"egg": 5, "baby": 6, "teen": 7, "adult": 9}


def main() -> None:
    # The Claude-activity faces, each in its state accent (the hero strip).
    states = ["idle", "thinking", "working", "waiting", "happy", "sleeping"]
    _strip("states", [_tile("baby", s, _BASE) for s in states])

    # egg -> baby -> teen -> adult, growing as it goes.
    stages = ["egg", "baby", "teen", "adult"]
    _strip("evolution", [_tile(stage, "idle", _STAGE_SCALE[stage]) for stage in stages])

    # Tamagotchi idle moods (driven by the pet's needs).
    moods = ["idle_happy", "idle_hungry", "idle_tired", "idle_sad"]
    _strip("moods", [_tile("baby", m, _BASE) for m in moods])

    for png in sorted(OUT_DIR.glob("*.png")):
        print("wrote", png.relative_to(OUT_DIR.parent.parent), f"({png.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
