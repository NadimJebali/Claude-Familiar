"""Tk-free tests for the pixel_grid primitive (Deepen 6/6, #39).

pixel_grid owns the char-grid + palette shape every blocky sprite shares: walking
the non-'.' cells (grid_cells) and checking a grid is well-formed (validate_grid).
The rasterizing itself is the Qt renderer's job (mascot.pixel_qt / sprite_qt).
"""
from __future__ import annotations

import pytest

from mascot import pixel_grid


# --- grid_cells --------------------------------------------------------------
def test_grid_cells_yields_lit_cells_in_reading_order_and_skips_dots():
    assert list(pixel_grid.grid_cells(["a.", ".b"])) == [(0, 0, "a"), (1, 1, "b")]


# --- validate_grid -----------------------------------------------------------
def test_validate_grid_accepts_a_wellformed_grid():
    pixel_grid.validate_grid(["ab", "ba"], colors={"a": "#1", "b": "#2"}, size=2)


def test_validate_grid_rejects_ragged_rows():
    with pytest.raises(AssertionError):
        pixel_grid.validate_grid(["abc", "ab"])


def test_validate_grid_rejects_the_wrong_size():
    with pytest.raises(AssertionError):
        pixel_grid.validate_grid(["ab", "ab"], size=3)


def test_validate_grid_rejects_a_char_outside_the_palette():
    with pytest.raises(AssertionError):
        pixel_grid.validate_grid(["ax"], colors={"a": "#1"})


# --- every app registry conforms (one check, replacing the scattered import asserts) -
def test_every_registry_grid_is_wellformed():
    from mascot import item_art, sprite_pixel, ui_icons

    for name, grid in item_art._ITEMS.items():            # shop items: 12x12
        pixel_grid.validate_grid(grid, colors=item_art.PALETTE, size=item_art.GRID, name=name)

    for name, grid in ui_icons._ICONS.items():            # ttk glyphs: rectangular
        pixel_grid.validate_grid(grid, colors=ui_icons.PALETTE, name=name)

    for stage in (*sprite_pixel._BODIES, "egg"):          # every face on every body
        for state in sprite_pixel._FACES:
            pixel_grid.validate_grid(sprite_pixel.grid_for(stage, state),
                                     size=sprite_pixel.GRID_W, name=f"{stage}/{state}")

    pixel_grid.validate_grid(sprite_pixel._GRAVE,          # the gravestone: 16x16
                             colors=sprite_pixel.GRAVE_COLORS, size=sprite_pixel.GRID_W,
                             name="grave")

    for hid, hat in sprite_pixel._HATS.items():            # hats: rectangular, <= creature
        pixel_grid.validate_grid(hat["grid"], colors=hat["colors"], name=hid)
        assert len(hat["grid"][0]) <= sprite_pixel.GRID_W, hid
