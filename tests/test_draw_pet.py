"""Tk-free tests for draw_pet: the one wearing-pet renderer (Deepen 4/6, #40).

draw_pet turns a PetView into canvas paint — body(stage) + face + flourish + the
worn hat, with the egg staying bare. Like the other draw tests it never imports
tkinter: a tiny recording canvas captures each painted rectangle, so we assert on
*what got drawn* rather than pixels on a screen.
"""
from __future__ import annotations

import pytest

from mascot import sprite_pixel
from mascot.pet_view import PetView


class _RecordingCanvas:
    """Captures create_rectangle paints (as (x0, y0, x1, y1, fill)) so a test can
    assert what draw_pet emits without touching Tk — same spirit as the fake canvas
    in test_animation."""

    def __init__(self) -> None:
        self.rects: list[tuple] = []

    def create_rectangle(self, x0, y0, x1, y1, **kw):
        self.rects.append((x0, y0, x1, y1, kw.get("fill")))
        return len(self.rects)


def _paint(view: PetView, *, state: str = "idle", px: int = 5) -> list[tuple]:
    c = _RecordingCanvas()
    sprite_pixel.draw_pet(c, 100, 100, view, state=state, accent=sprite_pixel.BODY, px=px)
    return c.rects


# --- tracer bullet -----------------------------------------------------------
def test_draw_pet_paints_the_creature():
    rects = _paint(PetView(stage="baby", hat=None, flourish=False, mood="happy"))
    assert rects  # a baby renders some pixels


# --- the egg stays bare ------------------------------------------------------
def test_an_egg_wears_nothing_even_with_a_hat():
    # The bare-egg rule is double-guarded: the projection sets view.hat=None on an
    # egg, and draw_hat itself skips the egg. So even a hat id forced onto an egg
    # paints nothing extra — draw_pet needn't special-case it.
    bare = _paint(PetView(stage="egg", hat=None, flourish=False, mood="content"))
    forced = _paint(PetView(stage="egg", hat="party_hat", flourish=False, mood="content"))
    assert forced == bare


# --- the worn hat ------------------------------------------------------------
def test_a_worn_hat_adds_paint_on_a_hatched_pet():
    bare = _paint(PetView(stage="baby", hat=None, flourish=False, mood="happy"))
    worn = _paint(PetView(stage="baby", hat="party_hat", flourish=False, mood="happy"))
    assert len(worn) > len(bare)


def test_an_unknown_hat_id_is_safe():
    # A held-but-artless / unknown id renders no hat and doesn't crash.
    bare = _paint(PetView(stage="baby", hat=None, flourish=False, mood="happy"))
    unknown = _paint(PetView(stage="baby", hat="not_a_real_hat", flourish=False, mood="happy"))
    assert unknown == bare


# --- milestone flourish ------------------------------------------------------
def test_the_milestone_flourish_adds_sparkle_paint():
    plain = _paint(PetView(stage="baby", hat=None, flourish=False, mood="happy"))
    sparkly = _paint(PetView(stage="baby", hat=None, flourish=True, mood="happy"))
    assert len(sparkly) > len(plain)


# --- smoke: every stage x bare/wearing renders safely ------------------------
@pytest.mark.parametrize("stage", ["egg", "baby", "teen", "adult"])
@pytest.mark.parametrize("hat", [None, "party_hat"])
def test_draw_pet_smoke_across_stages_and_outfits(stage, hat):
    rects = _paint(PetView(stage=stage, hat=hat, flourish=False, mood="content"))
    assert rects  # even the egg paints a body
