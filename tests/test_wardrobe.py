"""Tests for the wardrobe PRD (#33): streak/days accounting through the tick seam.
Cosmetics-core tests join this file in the next slice. Same synthetic style as the
other pet tests.
"""
from __future__ import annotations

import time

from mascot import cosmetics, pet_logic, pet_store

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


# --- cosmetics: the shop tier -------------------------------------------------
def _piece(pid):
    piece = cosmetics.piece_by_id(pid)
    assert piece is not None
    return piece


def test_buy_moves_coins_into_the_wardrobe_permanently():
    pet = _pet(coins=150)
    hat = _piece("party_hat")
    ok, _ = cosmetics.can_buy(pet, hat, level=3)
    assert ok

    nxt = cosmetics.buy(pet, hat)

    assert nxt["coins"] == 50
    assert "party_hat" in nxt["wardrobe"]
    assert pet["wardrobe"] == []              # input never mutated


def test_can_buy_gates_on_level_coins_and_ownership():
    hat = _piece("party_hat")
    assert cosmetics.can_buy(_pet(coins=999), hat, level=1)[1].startswith("Reach level")
    assert cosmetics.can_buy(_pet(coins=10), hat, level=3)[1] == "Not enough coins"
    owned_pet = _pet(coins=999, wardrobe=["party_hat"])
    assert cosmetics.can_buy(owned_pet, hat, level=3)[1] == "Already owned"


def test_milestone_pieces_are_never_for_sale():
    flower = _piece("flower")
    ok, reason = cosmetics.can_buy(_pet(coins=99999), flower, level=99)
    assert not ok
    assert reason == "7 days together"


def test_cosmetics_have_no_stat_effects_ever():
    # Delight, never power — structurally: no piece carries an effects map.
    assert all("effects" not in piece for piece in cosmetics.CATALOG)


# --- cosmetics: equipping -------------------------------------------------------
def test_equip_wears_an_owned_piece_and_switching_is_free():
    pet = _pet(wardrobe=["party_hat", "beanie"])
    pet = cosmetics.equip(pet, "party_hat")
    assert cosmetics.equipped_head(pet) == "party_hat"
    pet = cosmetics.equip(pet, "beanie")      # no cost, no cooldown
    assert cosmetics.equipped_head(pet) == "beanie"
    pet = cosmetics.equip(pet, None)          # take it off
    assert cosmetics.equipped_head(pet) is None


def test_equip_of_an_unowned_piece_is_a_noop():
    pet = cosmetics.equip(_pet(), "crown")
    assert cosmetics.equipped_head(pet) is None


# --- cosmetics: milestone grants ------------------------------------------------
def test_grant_milestones_awards_earned_history_pieces():
    pet, newly = cosmetics.grant_milestones(_pet(days_active=7))
    assert newly == ["flower"]
    assert "flower" in pet["wardrobe"]


def test_grant_milestones_is_idempotent_and_never_regresses():
    pet, first = cosmetics.grant_milestones(_pet(days_active=30))
    assert set(first) == {"flower", "crown"}
    again, newly = cosmetics.grant_milestones(pet)
    assert newly == []                        # nothing granted twice
    assert set(again["wardrobe"]) == {"flower", "crown"}


def test_grant_milestones_before_the_threshold_gives_nothing():
    _, newly = cosmetics.grant_milestones(_pet(days_active=6))
    assert newly == []


# --- hat art parity + anchors ---------------------------------------------------
def test_every_catalog_piece_has_valid_hat_art():
    from mascot import sprite_pixel
    for piece in cosmetics.CATALOG:
        hat = sprite_pixel._HATS.get(piece["id"])
        assert hat is not None, piece["id"]
        grid, colors = hat["grid"], hat["colors"]
        assert all(len(r) == len(grid[0]) for r in grid), piece["id"]
        assert len(grid[0]) <= sprite_pixel.GRID_W, piece["id"]
        for row in grid:
            assert set(row) <= {*colors, "."}, piece["id"]


def test_hat_anchor_exists_for_every_wearing_stage():
    from mascot import sprite_pixel
    # Every stage except the egg wears hats; each needs a crown-row anchor.
    for stage in ("baby", "teen", "adult"):
        assert stage in sprite_pixel._HAT_ANCHOR_ROW
    assert "egg" not in sprite_pixel._HAT_ANCHOR_ROW   # the egg stays bare
