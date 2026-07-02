"""Tests for the pet_view projection: the pet -> look mapping (Deepen 3/6, #38).

pet_view turns a pet (plus the clock) into the visual facts a card or the Pet window
needs — stage, worn hat, milestone flourish, and mood — as one pure, immutable
projection. Same synthetic style as the other pet cores.
"""
from __future__ import annotations

import pytest

from mascot import pet_logic, pet_store
from mascot.pet_view import PetView, pet_view


def _pet(**over):
    pet = pet_store.default_pet(now=1000.0)
    pet.update(over)
    return pet


# --- tracer bullet -----------------------------------------------------------
def test_a_brand_new_pet_is_a_bare_happy_egg():
    view = pet_view(_pet(), now=1000.0)
    assert view == PetView(stage="egg", hat=None, flourish=False, mood="happy")


# --- stage follows level AND age ---------------------------------------------
@pytest.mark.parametrize(("xp", "age_days", "stage"), [
    (0,   0, "egg"),     # level 1
    (100, 0, "baby"),    # level 2 — hatches on the first level-up
    (400, 1, "teen"),    # level 5 + a day
    (900, 3, "adult"),   # level 10 + three days
])
def test_stage_follows_level_and_age(xp, age_days, stage):
    pet = _pet(xp=xp, born=1000.0)
    now = 1000.0 + age_days * pet_logic.DAY_S
    assert pet_view(pet, now=now).stage == stage


def test_a_high_level_pet_still_waits_out_the_age_gate():
    # Level 10 reached in an instant is still a baby until the age gates pass.
    pet = _pet(xp=900, born=1000.0)
    assert pet_view(pet, now=1000.0).stage == "baby"


# --- the worn hat (and the egg-bare rule) ------------------------------------
def test_an_equipped_hat_shows_on_a_hatched_pet():
    pet = _pet(xp=100, wardrobe=["party_hat"], equipped={"head": "party_hat"})
    assert pet_view(pet, now=1000.0).hat == "party_hat"


def test_an_egg_never_wears_a_hat():
    # Even with a hat equipped, an egg is bare — the rule lives in the projection,
    # so draw_pet needn't special-case it.
    pet = _pet(xp=0, wardrobe=["party_hat"], equipped={"head": "party_hat"})
    assert pet_view(pet, now=1000.0).hat is None


# --- milestone flourish ------------------------------------------------------
def test_flourish_turns_on_at_the_milestone_level():
    below = _pet(xp=800)   # level 9
    at = _pet(xp=900)      # level 10 == MILESTONE_LEVEL
    assert pet_view(below, now=1000.0).flourish is False
    assert pet_view(at, now=1000.0).flourish is True
