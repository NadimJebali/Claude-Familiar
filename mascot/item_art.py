"""Pixel art for the shop items (Tamagotchi #10), same blocky grid technique as
the mascot. Each item is a 12x12 char grid; `draw_item` paints it on a canvas.

Drafts meant to be iterated on visually — tweak a grid and it shows up in the Pet
window shop/inventory immediately. Legend is the shared PALETTE below.
"""
from __future__ import annotations

import tkinter as tk

from . import pixel_grid

GRID = 12

PALETTE = {
    "k": "#2c2433",  # dark outline
    "r": "#e0556a",  # red
    "o": "#d97757",  # claude orange
    "y": "#ecc94b",  # yellow
    "g": "#5fd08a",  # green
    "b": "#5a8bd8",  # blue
    "p": "#a78bda",  # purple
    "w": "#f7f3ee",  # white
    "t": "#d2a679",  # tan / cookie
    "n": "#8a5a2b",  # brown
    "c": "#48bbcb",  # cyan
    "s": "#9095a8",  # grey
}

_ITEMS: dict[str, list[str]] = {
    "snack": [          # a cookie with chocolate chips
        "............",
        "....kkkk....",
        "..kkttttkk..",
        ".kttttttttk.",
        ".kttntttttk.",
        "kttttttntttk",
        "ktttnttttttk",
        ".kttttttttk.",
        ".kttttttttk.",
        "..kkttttkk..",
        "....kkkk....",
        "............",
    ],
    "meal": [           # a bowl of food
        "............",
        "....y..y....",
        "...wwwwww...",
        "..wwyywwyw..",
        ".bbbbbbbbbb.",
        ".bssssssssb.",
        ".bssssssssb.",
        "..bssssssb..",
        "...bssssb...",
        "....bbbb....",
        "............",
        "............",
    ],
    "energy_drink": [   # a can with a lightning bolt
        "............",
        "....ssss....",
        "...kssssk...",
        "...kyywyk...",
        "...kywwyk...",
        "...kywyyk...",
        "...kwwyyk...",
        "...kyywyk...",
        "...kyyyyk...",
        "...kyyyyk...",
        "...kkkkkk...",
        "............",
    ],
    "feast": [          # a roast turkey (two drumstick legs up) on a platter
        "..ww....ww..",
        "...w....w...",
        "..nnnnnnnn..",
        ".nnnnnnnnnn.",
        ".nnoonnoonn.",
        ".nnnnnnnnnn.",
        ".nnnnnnnnnn.",
        "..nnnnnnnn..",
        ".ssssssssss.",
        ".swwwwwwwws.",
        "..wwwwwwww..",
        "............",
    ],
    "ball": [           # a two-tone ball
        "............",
        "....kkkk....",
        "..kkrrwwkk..",
        ".krrrrwwwwk.",
        ".krrrrwwwwk.",
        "krrrrrwwwwwk",
        "krrrrrwwwwwk",
        ".krrrrwwwwk.",
        ".krrrrwwwwk.",
        "..kkrrwwkk..",
        "....kkkk....",
        "............",
    ],
    "puzzle": [         # a colorful 3x3 cube
        "............",
        ".kkkkkkkkkk.",
        ".krrkggkbbk.",
        ".krrkggkbbk.",
        ".kkkkkkkkkk.",
        ".kyykppkcck.",
        ".kyykppkcck.",
        ".kkkkkkkkkk.",
        ".kggkrrkyyk.",
        ".kggkrrkyyk.",
        ".kkkkkkkkkk.",
        "............",
    ],
}

# Every grid is validated (12x12, palette-covered) in
# tests/test_pixel_grid.py::test_every_registry_grid_is_wellformed.


def has_art(item_id: str) -> bool:
    return item_id in _ITEMS


def draw_item(c: tk.Canvas, item_id: str, cx: float, cy: float, px: int,
              tag: str = "item") -> None:
    """Draw item `item_id` centered at (cx, cy), one square per cell."""
    grid = _ITEMS.get(item_id)
    if grid is None:
        return
    pixel_grid.draw_grid(c, grid, PALETTE, cx, cy, px, tag)
