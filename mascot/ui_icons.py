"""Tiny pixel-art UI icons (paw / coin / check), rendered to ``tk.PhotoImage`` so
they can stand in for emoji in ttk labels and buttons — same blocky technique as
the mascot, no image files or fonts.

Use ``photo(master, name, px)`` and keep a reference to the returned image (Tk
discards an image with no live reference).
"""
from __future__ import annotations

import tkinter as tk

from . import pixel_grid

PALETTE = {
    "p": "#d9885a",   # paw (warm Claude accent)
    "o": "#b5872f",   # coin rim (bronze)
    "y": "#ecc94b",   # coin gold
    "w": "#fdf2c0",   # coin shine
    "c": "#5fd08a",   # check (green)
}

_ICONS: dict[str, list[str]] = {
    "paw": [
        "............",
        ".....pp.....",
        "..pp.pp.pp..",
        "..pp....pp..",
        "............",
        "...pppppp...",
        "..pppppppp..",
        "..pppppppp..",
        "...pppppp...",
        "............",
        "............",
        "............",
    ],
    "coin": [
        "............",
        "....oooo....",
        "..ooyyyyoo..",
        ".oywwyyyyyo.",
        ".oyyyyyyyyo.",
        "oyyyyyyyyyyo",
        "oyyyyyyyyyyo",
        ".oyyyyyyyyo.",
        ".oyyyyyyyyo.",
        "..ooyyyyoo..",
        "....oooo....",
        "............",
    ],
    "check": [
        "............",
        "..........c.",
        ".........cc.",
        "........cc..",
        ".c.....cc...",
        ".cc...cc....",
        "..cc.cc.....",
        "...ccc......",
        "....c.......",
        "............",
        "............",
        "............",
    ],
}

# Grids are validated (rectangular, palette-covered) in
# tests/test_pixel_grid.py::test_every_registry_grid_is_wellformed.


def photo(master: tk.Misc, name: str, px: int = 2) -> tk.PhotoImage:
    """Render icon `name` to a transparent PhotoImage at `px` pixels per cell."""
    grid = _ICONS[name]
    img = tk.PhotoImage(master=master, width=len(grid[0]) * px, height=len(grid) * px)
    for x, y, ch in pixel_grid.grid_cells(grid):
        img.put(PALETTE[ch], to=(x * px, y * px, (x + 1) * px, (y + 1) * px))
    return img
