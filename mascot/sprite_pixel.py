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

# Evolution exploits the sprite's split: a per-STAGE body (the 6 top + 5 bottom
# rows) wraps the shared per-STATE face (the 5 middle rows), so a render is
# ``body[stage] + face[state]`` and every face is reused at every stage. The egg
# is special — a faceless 16-row grid that hatches into the baby on first level-up.
#
# Stages advance at the engine's (level, age) thresholds (pet_logic.stage_for).
# These per-stage grids are first-draft art meant to be iterated on visually.
_BODIES = {
    "baby": {
        "top": [
            "................",
            ".......a........",
            "......aaa.......",
            "....oooooooo....",
            "...oooooooooo...",
            "..ooOOOOOOOOoo..",
        ],
        "bottom": [
            "..ooOOOOOOOOoo..",
            "...oooooooooo...",
            "....oooooooo....",
            ".....o....o.....",
            "................",
        ],
    },
    "teen": {                       # taller sparkle pair + four little feet
        "top": [
            "................",
            "......a.a.......",
            ".......a........",
            "....oooooooo....",
            "...oooooooooo...",
            "..ooOOOOOOOOoo..",
        ],
        "bottom": [
            "..ooOOOOOOOOoo..",
            "...oooooooooo...",
            "....oooooooo....",
            "....o.o..o.o....",
            "................",
        ],
    },
    "adult": {                      # ear tips, a broader body, sturdier legs
        "top": [
            "...a........a...",
            "...oo......oo...",
            "...oooooooooo...",
            "..oooooooooooo..",
            "..oooooooooooo..",
            "..ooOOOOOOOOoo..",
        ],
        "bottom": [
            "..ooOOOOOOOOoo..",
            "..oooooooooooo..",
            "...oooooooooo...",
            "...o..o..o..o...",
            "................",
        ],
    },
}

# The egg: a faceless shell with a few speckles (no face is composed for it).
_EGG = [
    "................",
    "......oooo......",
    ".....oOOOOo.....",
    "....oOOOOOOo....",
    "...oOOOaOOOoo...",
    "...oOOOOOOOOo...",
    "...oOOaOOOaOo...",
    "...oOOOOOOOOo...",
    "...oOOOOaOOOo...",
    "...oOOOOOOOOo...",
    "....oOOOOOOo....",
    "....oOOOOOOo....",
    ".....oOOOOo.....",
    "......oooo......",
    "................",
    "................",
]

# The creature grows as it evolves: a per-stage pixel-size multiplier applied to
# the base cell size by the renderer. Tuning/visual, not structural.
STAGE_SCALE = {"egg": 0.85, "baby": 1.0, "teen": 1.2, "adult": 1.4}

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
    "waiting_angry": [
        "..oOkOOOOOOkOo..",   # angry: brows slant down toward the nose…
        "..oOOkOOOOkOOo..",
        "..oOOwkOOkwOOo..",   # …into glaring eyes
        "..oOOmmmmmmOOo..",   # scowling, downturned mouth
        "..oOmOOOOOOmOo..",
    ],
    "sleeping": [
        "..oOOOOOOOOOOo..",
        "..oOkkkOOkkkOo..",   # closed eyes
        "..oOOOOOOOOOOo..",
        "..oOOOOmmOOOOo..",
        "..oOOOOOOOOOOo..",
    ],
    "dizzy": [
        "..oOkOkOOkOkOo..",   # x-eyes (full 3x3 X per eye)
        "..oOOkOOOOkOOo..",
        "..oOkOkOOkOkOo..",
        "..oOOmmmmmmOOo..",   # straight mouth
        "..oOOOOOOmmOOo..",   # drool
    ],
    "happy": [
        "..oOOOOOOOOOOo..",
        "..oOkkOOOOkkOo..",   # joyful squint eyes
        "..oOOOOOOOOOOo..",
        "..oOmOOOOOOmOo..",   # smile corners turned up
        "..oOOmmmmmmOOo..",   # big grin
    ],
    "idle_blink": [
        "..oOOOOOOOOOOo..",
        "..oOkkkOOkkkOo..",   # eyes closed for a blink
        "..oOOOOOOOOOOo..",
        "..oOOmOOOOmOOo..",   # (idle mouth, so it reads as "idle, blinking")
        "..oOOmmmmmmOOo..",
    ],
    # --- idle-mood variants (pet needs; chosen by effective_state when idle) ----
    "idle_happy": [          # well cared-for: a content, sparkly grin
        "..oOOOOOOOOOOo..",
        "..oOkkOOOOkkOo..",   # happy squint
        "..oOOOOOOOOOOo..",
        "..oOmOOOOOOmOo..",   # corners up
        "..oOOmmmmmmOOo..",   # gentle grin
    ],
    "idle_hungry": [         # droopy: pupils dropped low, small mouth
        "..oOwwwOOwwwOo..",
        "..oOOkOOOOkOOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOOmmOOOOo..",
        "..oOOOOOOOOOOo..",
    ],
    "idle_sad": [            # low happiness: down eyes, frown (corners down)
        "..oOwkwOOwkwOo..",
        "..oOwwwOOwwwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOmmmmmmOOo..",
        "..oOmOOOOOOmOo..",
    ],
    "idle_tired": [          # low energy: heavy-lidded, neutral mouth
        "..oOOOOOOOOOOo..",
        "..oOwkwOOwkwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOmmmmOOOo..",
        "..oOOOOOOOOOOo..",
    ],
}


def grid_for(stage: str, state: str) -> list[str]:
    """The 16x16 character grid for a (stage, state): ``body[stage] + face[state]``.

    The egg is faceless, so its grid ignores `state`. An unknown stage falls back to
    the baby body and an unknown state to the idle face, so a new face/stage can't
    crash the render.
    """
    if stage == "egg":
        rows = _EGG
    else:
        body = _BODIES.get(stage, _BODIES["baby"])
        rows = body["top"] + _FACES.get(state, _FACES["idle"]) + body["bottom"]
    # Cheap self-check: catch a mistyped row the moment this module loads.
    assert len(rows) == GRID_H, f"{stage}/{state}: {len(rows)} rows"
    for r in rows:
        assert len(r) == GRID_W, f"{stage}/{state}: bad row width {len(r)!r}"
    return rows


# Validate every face composed against every stage (+ the egg) at import time.
for _stage in (*_BODIES, "egg"):
    for _s in _FACES:
        grid_for(_stage, _s)


def draw_creature(
    c: tk.Canvas, cx: float, cy: float, state: str, accent: str,
    px: int = 5, tag: str = "creature", stage: str = "baby", flourish: bool = False,
) -> None:
    """Draw the pixel creature for `stage`/`state` centered at (cx, cy), one square
    per grid cell.

    `px` is the size of each pixel; the default renders an ~80px character. All
    cells are tagged `tag` so the caller can bob or delete the whole group. When
    `flourish` is set (a leveled-up milestone), a few accent sparkles are added.
    """
    grid = grid_for(stage, state)
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
    if flourish:
        _draw_flourish(c, cx, cy, px, accent, tag)


# A small milestone sparkle: a few accent pixels at the upper corners, drawn over
# the creature once it has leveled up enough (a visual reward, tuning not structural).
_FLOURISH = [(-7, -7), (-6, -6), (7, -7), (6, -6), (-8, -3), (8, -3)]


def _draw_flourish(c: tk.Canvas, cx: float, cy: float, px: int, accent: str, tag: str) -> None:
    for gx, gy in _FLOURISH:
        x = cx + gx * px
        y = cy + gy * px
        c.create_rectangle(x, y, x + px, y + px, fill=accent, outline="", tags=tag)


# --- pet hearts -------------------------------------------------------------
# A small hand-drawn heart, same blocky technique as the creature (no emoji).
# Drawn in a single flat color so it can be faded by lerping toward the panel.
_HEART = [
    ".OO..OO.",
    "OOOOOOOO",
    "OOOOOOOO",
    "OOOOOOOO",
    ".OOOOOO.",
    "..OOOO..",
    "...OO...",
]
_HEART_W = len(_HEART[0])
_HEART_H = len(_HEART)


def draw_heart(
    c: tk.Canvas, cx: float, cy: float, px: int, color: str, tag: str = "heart",
) -> None:
    """Draw a small pixel heart centered at (cx, cy), one square per cell."""
    x0 = cx - (_HEART_W * px) / 2
    y0 = cy - (_HEART_H * px) / 2
    for r, row in enumerate(_HEART):
        y = y0 + r * px
        for col, ch in enumerate(row):
            if ch == ".":
                continue
            x = x0 + col * px
            c.create_rectangle(x, y, x + px, y + px, fill=color, outline="", tags=tag)
