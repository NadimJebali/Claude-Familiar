"""Pixel-art mascot, styled after Claude Code's blocky terminal creature.

The character is defined as 16x16 character grids — one face per state — the single
source of truth the Qt renderer (:mod:`mascot.sprite_qt`) rasterizes to pixmaps.
Designing in ASCII means the art is readable and editable right here in the source:
tweak a grid, see the change.

Legend:  '.' transparent · 'o' outline · 'O' body (Claude orange) ·
         'w' eye white · 'k' pupil · 'm' mouth · 't' tear (always blue) ·
         'a' state accent (sparkle/mood)
"""
from __future__ import annotations

from typing import Any

# --- palette (Claude burnt-orange) -----------------------------------------
BODY = "#d97757"
OUTLINE = "#b05a34"
WHITE = "#f7f3ee"
PUPIL = "#2c2433"
MOUTH = "#7a3322"
TEAR = "#6db3e8"   # a soft sky blue — tears stay blue whatever the state accent

COLORS = {"o": OUTLINE, "O": BODY, "w": WHITE, "k": PUPIL, "m": MOUTH, "t": TEAR}

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

# The egg: a faceless shell with big dinosaur-egg speckles ('a' = speckle; drawn in
# a fixed grey, not the state accent — see draw_creature). No face is composed for it.
_EGG = [
    "................",
    "......oooo......",
    ".....oOOOOo.....",
    "....oOOOOOOo....",
    "...oOOaaOOOOo...",
    "...oOOaaOaaOo...",
    "..oOOOOOOaaOOo..",
    "..oOaaOOOOOOOo..",
    "..oOaaOOaaOOOo..",
    "...oOOOOaaOOo...",
    "...oOOaaOOOOo...",
    "....oOaaOOOo....",
    ".....oOOOOo.....",
    "......oooo......",
    "................",
    "................",
]
EGG_SPECKLE = "#6f7486"   # dino-egg spots: a steady grey, independent of mood

# The creature grows as it evolves: a per-stage pixel-size multiplier applied to
# the base cell size by the renderer. Tuning/visual, not structural.
STAGE_SCALE = {"egg": 0.85, "baby": 1.0, "teen": 1.2, "adult": 1.4}

# The gravestone (the "dead" state — out of usage): a full 16-row grid like the
# egg, with its own muted palette. Legend: 'e' stone edge · 's' stone · 'v' the
# engraved cross · 'd' a weathering crack · 'g' earth mound · 'G' grass tufts.
_GRAVE = [
    "................",
    ".....eeeeee.....",
    "....esssssse....",
    "...esssssssse...",
    "...esssvvssse...",
    "...esvvvvvvse...",
    "...esssvvssse...",
    "...esssvvssse...",
    "...esssssssse...",
    "...essssssdse...",
    "...esssssdsse...",
    "..GesssssssseG..",
    "..gggggggggggg..",
    ".gggggggggggggg.",
    "................",
    "................",
]
GRAVE_COLORS = {
    "e": "#4f535d",   # stone edge (the dead accent, darkened)
    "s": "#7a8090",   # stone face — matches STATE_COLORS["dead"]
    "v": "#303339",   # engraved cross
    "d": "#5f6472",   # weathering crack
    "g": "#39473b",   # earth mound
    "G": "#55684f",   # grass tufts
}


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
    # --- per-tool working variants (chosen by effective_state.working_face_for) --
    "working_read": [
        "..oOwwwOOwwwOo..",   # eyes cast down the middle — reading a page
        "..oOwwkOOkwwOo..",
        "..oOOOOOOOOOOo..",
        "..oOOOmmmmOOOo..",   # small absorbed line
        "..oOOOOOOOOOOo..",
    ],
    "working_edit": [
        "..oOOOOOwwwwOo..",   # left brow knitted flat, right eye wide open
        "..oOkkkOOwkwOo..",   # asymmetric concentration
        "..oOOOOOOOOOOo..",
        "..oOOOmmOOOOOo..",   # bitten lip, off-center
        "..oOOOOOOOOOOo..",
    ],
    "working_run": [
        "..oOkOOOOOOkOo..",   # brow tips angled in — effort
        "..oOOkkOOkkOOo..",   # tight determined squint
        "..oOOOOOOOOOOo..",
        "..oOmwmwwmwmOo..",   # gritted teeth (white glints)
        "..oOOOOOOOOOOo..",
    ],
    "working_web": [
        "..oOwwwOOOwwOo..",   # one eye wider than the other — scanning
        "..oOkwwOOOwkOo..",   # pupils darting to opposite edges
        "..oOOOOOOOOOOo..",
        "..oOOOmmmOOOOo..",   # slightly-open browsing mouth
        "..oOOOOOOOOOOo..",
    ],
    "planning": [
        "..oOkwwOOkwwOo..",   # pupils up-and-left — gazing off into the plan
        "..oOwwwOOwwwOo..",
        "..oOOOOOOOOaOo..",   # a little idea spark at the temple
        "..oOOOOmmOOOOo..",   # small pondering hum
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
    "compacting": [
        "..oOtOOOOOOOOo..",   # a blue sweat droplet at the temple
        "..oOOkkOOkkOOo..",   # eyes screwed tightly shut…
        "..oOkOOkkOOkOo..",   # …with strain lines underneath
        "..oOOOmmmmOOOo..",   # tight flat mouth — squeezing memories together
        "..oOOOOOOOOOOo..",
    ],
    "stumble": [
        "..oOwwwOOwwwOo..",   # eyes blown wide…
        "..oOwwwOOwwwOo..",   # …pupils gone — caught out
        "..oOtOOOOOOtOo..",   # a blue tear at each eye corner…
        "..oOtOOmmOOtOo..",   # …rolling down past a tiny gasp
        "..oOOOOOOOOOOo..",
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
    "idle_hungry": [         # round eyes (white-flanked pupils), small wistful mouth
        "..oOwwwOOwwwOo..",
        "..oOwkwOOwkwOo..",
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


# Every composed face (against each body + the egg) and the gravestone are validated
# in tests/test_pixel_grid.py::test_every_registry_grid_is_wellformed.


# A small milestone sparkle: a few accent pixels at the upper corners, drawn over
# the creature once it has leveled up enough (a visual reward, tuning not structural).
_FLOURISH = [(-7, -7), (-6, -6), (7, -7), (6, -6), (-8, -3), (8, -3)]


# --- wardrobe hats (cosmetics.py catalog art) --------------------------------
# One small grid + palette per piece, drawn OVER the creature so its bottom row
# sits on the stage's crown row (covering the sparkle — the hat is the sparkle
# now). Draft art like the stage bodies: iterate the grids, HITL.
_HATS: dict[str, dict[str, Any]] = {
    "party_hat": {
        "grid": ["...y...",
                 "..ppp..",
                 ".ppypp.",
                 "ppppppp"],
        "colors": {"p": "#f472b6", "y": "#ecc94b"},
    },
    "beanie": {
        "grid": ["..bbbb..",
                 ".bbbbbb.",
                 "BBBBBBBB"],
        "colors": {"b": "#4a6fa5", "B": "#6db3e8"},
    },
    "top_hat": {
        "grid": ["..TTTTTT..",
                 "..TTTTTT..",
                 "..TrrrrT..",
                 "TTTTTTTTTT"],
        "colors": {"T": "#2c2433", "r": "#e0556a"},
    },
    "wizard_hat": {
        "grid": ["....w....",
                 "...www...",
                 "..wwsww..",
                 ".wwwwwww.",
                 "wwwwwwwww"],
        "colors": {"w": "#7c5cd6", "s": "#ecc94b"},
    },
    "propeller_cap": {
        "grid": [".yy.k.bb.",
                 "..rrrrr..",
                 ".rrrrrrr."],
        "colors": {"y": "#ecc94b", "b": "#6db3e8", "k": "#2c2433", "r": "#e0556a"},
    },
    "flower": {
        "grid": [".f.",
                 "fyf",
                 ".f.",
                 ".g."],
        "colors": {"f": "#f7f3ee", "y": "#ecc94b", "g": "#6fcf83"},
    },
    "crown": {
        "grid": ["y.y.y",
                 "yjyjy",
                 "yyyyy"],
        "colors": {"y": "#ecc94b", "j": "#e0556a"},
    },
}

# The first head-outline row of each stage's body — a hat's bottom row sits here.
# (The egg never wears anything; render callers skip it.)
_HAT_ANCHOR_ROW = {"baby": 3, "teen": 3, "adult": 2}

# Every hat grid is validated (rectangular, no wider than the creature, palette-
# covered) in tests/test_pixel_grid.py::test_every_registry_grid_is_wellformed.


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


# --- mood emotes (popups above the creature) -------------------------------
# Tiny multi-color pixel art that pops up while the pet is in a low-need mood: a
# piece of food when hungry, a drifting "Z" when sleepy. Same blocky technique.
_FOOD = [          # a little apple (g = leaf, s = stem, r = apple body)
    "..g...",
    "..s...",
    ".rrrr.",
    "rrrrrr",
    "rrrrrr",
    ".rrrr.",
]
_FOOD_COLORS = {"r": "#e0556a", "g": "#6fcf83", "s": MOUTH}

_ZED = [           # a single "Z"; the widget staggers a few to read as "zzz"
    "ZZZZ",
    "...Z",
    "..Z.",
    ".Z..",
    "ZZZZ",
]
