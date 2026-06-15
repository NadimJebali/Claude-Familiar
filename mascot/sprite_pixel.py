"""Pixel-art mascot, styled after Claude Code's blocky terminal creature.

The character is defined as 16x16 character grids — one face per state — drawn
as a grid of square "pixels" on the Canvas. Designing in ASCII means the art is
readable and editable right here in the source: tweak a grid, see the change.

Legend:  '.' transparent · 'o' outline · 'O' body (Claude orange) ·
         'w' eye white · 'k' pupil · 'm' mouth · 'a' state accent (sparkle/mood)
"""
from __future__ import annotations

import tkinter as tk

# --- palette (Claude burnt-orange) -----------------------------------------
BODY = "#d97757"
OUTLINE = "#b05a34"
WHITE = "#f7f3ee"
PUPIL = "#2c2433"
MOUTH = "#7a3322"

COLORS = {"o": OUTLINE, "O": BODY, "w": WHITE, "k": PUPIL, "m": MOUTH}

GRID_W = 16
GRID_H = 16

# Constant top (sparkle "antenna" + head) and bottom (belly + feet).
_TOP = [
    "................",
    ".......a........",
    "......aaa.......",
    "....oooooooo....",
    "...oooooooooo...",
    "..ooOOOOOOOOoo..",
]
_BOTTOM = [
    "..ooOOOOOOOOoo..",
    "...oooooooooo...",
    "....oooooooo....",
    ".....o....o.....",
    "................",
]

# Per-state face (the 5 middle rows: eyes + mouth).
_FACES = {
    "idle": [
        "..oOwwwOOwwwOo..",
        "..oOwkwOOwkwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOmOOOOmOOo..",
        "..oOOmmmmmmOOo..",
    ],
    "thinking": [
        "..oOwkwOOwkwOo..",   # pupils up — looking away in thought
        "..oOwwwOOwwwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOmmmmOOOo..",
    ],
    "working": [
        "..oOOOOOOOOOOo..",
        "..oOkkkOOkkkOo..",   # squint — focused
        "..oOOOOOOOOOOo..",
        "..oOOmmmmmmOOo..",
        "..oOOOOOOOOOOo..",
    ],
    "waiting": [
        "..oOwwwOOwwwOo..",
        "..oOwkwOOwkwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOmmmmOOOo..",   # open "oh!" mouth
        "..oOOOmmmmOOOo..",
    ],
    "sleeping": [
        "..oOOOOOOOOOOo..",
        "..oOkkkOOkkkOo..",   # closed eyes
        "..oOOOOOOOOOOo..",
        "..oOOOOmmOOOOo..",
        "..oOOOOOOOOOOo..",
    ],
    "dizzy": [
        "..oOkOkOOkOkOo..",   # x-eyes
        "..oOOkOOOOkOOo..",
        "..oOOOOOOOOOOo..",
        "..oOmOmOmOmOOo..",   # wavy mouth
        "..oOOmOmOmOOOo..",
    ],
}


def _grid(state: str) -> list[str]:
    rows = _TOP + _FACES.get(state, _FACES["idle"]) + _BOTTOM
    # Cheap self-check: catch a mistyped row the moment this module loads.
    assert len(rows) == GRID_H, f"{state}: {len(rows)} rows"
    for r in rows:
        assert len(r) == GRID_W, f"{state}: bad row width {len(r)!r}"
    return rows


# Validate every face at import time.
for _s in _FACES:
    _grid(_s)


def draw_creature(
    c: tk.Canvas, cx: float, cy: float, state: str, accent: str,
    px: int = 5, tag: str = "creature",
) -> None:
    """Draw the pixel creature centered at (cx, cy), one square per grid cell.

    `px` is the size of each pixel; the default renders an ~80px character. All
    cells are tagged `tag` so the caller can bob or delete the whole group.
    """
    grid = _grid(state)
    x0 = cx - (GRID_W * px) / 2
    y0 = cy - (GRID_H * px) / 2
    for r, row in enumerate(grid):
        y = y0 + r * px
        for col, ch in enumerate(row):
            if ch == ".":
                continue
            color = accent if ch == "a" else COLORS[ch]
            x = x0 + col * px
            c.create_rectangle(x, y, x + px, y + px, fill=color, outline="", tags=tag)
