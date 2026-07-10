"""Tiny pixel-art UI icons (paw / coin / check) as char-grids + palette — the same
blocky technique as the mascot, no image files or fonts. The Qt views rasterize a
grid to a ``QPixmap`` via :func:`mascot.pixel_qt.grid_pixmap`.
"""
from __future__ import annotations

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
