"""Tests for the wardrobe PRD (#33): streak/days accounting through the tick seam.
Cosmetics-core tests join this file in the next slice. Same synthetic style as the
other pet tests.
"""
from __future__ import annotations

import time

from mascot import pet_logic, pet_store

THINKING = {"state": "thinking", "subagents": []}
IDLE = {"state": "idle", "subagents": []}


def _pet(**over):
    pet = pet_store.default_pet(now=1000.0)
    pet.update(over)
    return pet


def _first_prompt(pet, today):
    """One poll where a session enters thinking (claims the daily gate)."""
    nxt, _ = pet_logic.tick(pet, {"s": IDLE}, {"s": THINKING},
                            elapsed=0.0, working=True, today=today)
    return nxt


# --- streak accounting at the daily gate -------------------------------------
def test_first_prompt_of_day_advances_days_and_streak():
    pet = _first_prompt(_pet(), "2026-07-01")
    assert pet["days_active"] == 1
    assert pet["streak"] == 1
    assert pet["best_streak"] == 1


def test_consecutive_days_grow_the_streak():
    pet = _first_prompt(_pet(), "2026-07-01")
    pet = _first_prompt(pet, "2026-07-02")
    pet = _first_prompt(pet, "2026-07-03")
    assert pet["days_active"] == 3
    assert pet["streak"] == 3
    assert pet["best_streak"] == 3


def test_a_gap_resets_the_current_streak_but_never_the_history():
    pet = _first_prompt(_pet(), "2026-07-01")
    pet = _first_prompt(pet, "2026-07-02")
    pet = _first_prompt(pet, "2026-07-05")   # skipped two days
    assert pet["streak"] == 1                # current run restarts…
    assert pet["best_streak"] == 2           # …but the best is kept
    assert pet["days_active"] == 3           # and lifetime days only grow


def test_second_prompt_same_day_changes_nothing():
    pet = _first_prompt(_pet(), "2026-07-01")
    again, _ = pet_logic.tick(pet, {"s": IDLE}, {"s": THINKING},
                              elapsed=0.0, working=True, today="2026-07-01")
    assert again["days_active"] == 1
    assert again["streak"] == 1


def test_month_boundary_counts_as_consecutive():
    pet = _first_prompt(_pet(), "2026-06-30")
    pet = _first_prompt(pet, "2026-07-01")
    assert pet["streak"] == 2


def test_old_pet_json_without_counters_upgrades_cleanly():
    # A pre-wardrobe pet.json lacks the fields; .get defaults keep it safe.
    legacy = {k: v for k, v in _pet().items()
              if k not in ("days_active", "streak", "best_streak")}
    pet = _first_prompt(legacy, "2026-07-01")
    assert (pet["days_active"], pet["streak"], pet["best_streak"]) == (1, 1, 1)


def test_default_pet_ships_the_new_fields():
    pet = pet_store.default_pet(time.time())
    assert pet["days_active"] == 0 and pet["streak"] == 0 and pet["best_streak"] == 0
    assert pet["wardrobe"] == [] and pet["equipped"] == {}
