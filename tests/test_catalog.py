"""Tests for the shared acquisition core (Deepen 1/6, #36).

catalog is the buy logic shop and cosmetics used to each implement: the level gate,
the affordability check, and the coin-spend + add-to-collection transform. A pure,
I/O-free core; the two modules are thin adapters over it. These tests pin the shared
invariants (the property suite mirrors test_properties' Hypothesis style).
"""
from __future__ import annotations

import copy

from hypothesis import given
from hypothesis import strategies as st

from mascot import catalog


# --- tracer bullet -----------------------------------------------------------
def test_can_acquire_allows_an_affordable_unlocked_unowned_entry():
    entry = {"id": "x", "price": 50, "min_level": 1}
    assert catalog.can_acquire({"coins": 100}, entry, 1, owns=False) == (True, "")


# --- shared strategies -------------------------------------------------------
coins_amt = st.integers(min_value=0, max_value=10_000)


@st.composite
def entries(draw):
    return {"id": draw(st.sampled_from(["a", "b", "c"])),
            "price": draw(st.integers(min_value=0, max_value=10_000)),
            "min_level": draw(st.integers(min_value=1, max_value=30))}


levels = st.integers(min_value=1, max_value=30)


# --- can_acquire invariants --------------------------------------------------
@given(coins=coins_amt, entry=entries(), level=levels, owns=st.booleans())
def test_the_level_gate_is_always_enforced(coins, entry, level, owns):
    ok, reason = catalog.can_acquire({"coins": coins}, entry, level, owns=owns)
    if level < entry["min_level"]:
        assert (ok, reason) == (False, f"Reach level {entry['min_level']} to unlock")


@given(coins=coins_amt, entry=entries(), level=levels)
def test_owning_it_blocks_the_buy_once_unlocked(coins, entry, level):
    if level >= entry["min_level"]:
        got = catalog.can_acquire({"coins": coins}, entry, level, owns=True)
        assert got == (False, "Already owned")


@given(coins=coins_amt, entry=entries(), level=levels)
def test_affordability_decides_an_unlocked_unowned_buy(coins, entry, level):
    if level >= entry["min_level"]:
        ok, reason = catalog.can_acquire({"coins": coins}, entry, level, owns=False)
        assert (ok, reason) == ((True, "") if coins >= entry["price"]
                                else (False, "Not enough coins"))


# --- acquire invariants ------------------------------------------------------
@given(coins=coins_amt, entry=entries())
def test_acquire_spends_exactly_the_price_and_never_goes_below_zero(coins, entry):
    nxt = catalog.acquire({"coins": coins, "wardrobe": []}, entry, into="wardrobe")
    assert nxt["coins"] == max(0, coins - entry["price"]) >= 0


@given(coins=coins_amt, entry=entries())
def test_acquire_appends_to_a_list_collection(coins, entry):
    nxt = catalog.acquire({"coins": coins, "wardrobe": ["hat"]}, entry, into="wardrobe")
    assert nxt["wardrobe"] == ["hat", entry["id"]]


@given(coins=coins_amt, entry=entries(), start=st.integers(min_value=0, max_value=9))
def test_acquire_increments_a_count_collection(coins, entry, start):
    nxt = catalog.acquire({"coins": coins, "inventory": {entry["id"]: start}},
                          entry, into="inventory")
    assert nxt["inventory"][entry["id"]] == start + 1


@given(coins=coins_amt, entry=entries())
def test_acquire_does_not_mutate_the_input_pet(coins, entry):
    pet = {"coins": coins, "wardrobe": [], "inventory": {}}
    before = copy.deepcopy(pet)
    catalog.acquire(pet, entry, into="wardrobe")
    assert pet == before
