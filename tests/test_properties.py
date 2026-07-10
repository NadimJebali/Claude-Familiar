"""Property-based tests for the pure cores (issue #13).

These complement the example-based cases in ``test_phase1.py``: instead of fixed
inputs they fuzz the *invariants* the cores promise — clamping, immutability, the
daily coin cap, level monotonicity, and stage non-regression — across a wide swath
of inputs (negative / huge elapsed, negative deltas, arbitrary event streams).

Hypothesis is a **dev/test-only** dependency (``requirements-dev.txt``); it is never
imported by the shipped widget, which stays pure standard library.
"""
from __future__ import annotations

import copy

from hypothesis import given
from hypothesis import strategies as st

from mascot import pet_logic, roster, shop

# --- shared strategies ----------------------------------------------------
# Stats live on a 0..MAX_STAT bar; that's their valid input domain.
stats = st.integers(min_value=0, max_value=pet_logic.MAX_STAT)
# Elapsed seconds span clock-skew (negative) through years (huge) — the cores
# promise both are safe.
elapsed = st.floats(min_value=-1e6, max_value=1e9, allow_nan=False, allow_infinity=False)


def _pet(**over):
    p = {
        "name": "", "born": 0.0, "last_seen": 0.0,
        "hunger": 100, "happiness": 100, "energy": 100,
        "coins": 0, "xp": 0, "coins_today": 0, "last_award_date": "",
        "inventory": {}, "cooldowns": {},
    }
    p.update(over)
    return p


def _in_range(value: float) -> bool:
    return 0.0 <= value <= pet_logic.MAX_STAT


# --- decay ----------------------------------------------------------------

@given(hunger=stats, happiness=stats, energy=stats, secs=elapsed, working=st.booleans())
def test_decay_keeps_every_stat_in_range_and_never_mutates(
        hunger, happiness, energy, secs, working):
    pet = _pet(hunger=hunger, happiness=happiness, energy=energy)
    before = copy.deepcopy(pet)
    out = pet_logic.decay(pet, secs, working=working)
    assert _in_range(out["hunger"])
    assert _in_range(out["happiness"])
    assert _in_range(out["energy"])
    assert pet == before  # input dict untouched


# --- apply_effects --------------------------------------------------------
# Effects map arbitrary stat names (needs + junk) to arbitrary deltas.
_effect_keys = st.sampled_from(["hunger", "happiness", "energy", "coins", "xp", "level", "bogus"])
_effect_deltas = st.floats(min_value=-1000.0, max_value=1000.0,
                           allow_nan=False, allow_infinity=False)
effects = st.dictionaries(_effect_keys, _effect_deltas, max_size=7)


@given(hunger=stats, happiness=stats, energy=stats, fx=effects)
def test_apply_effects_clamps_needs_touches_only_needs_and_never_mutates(
        hunger, happiness, energy, fx):
    pet = _pet(hunger=hunger, happiness=happiness, energy=energy, coins=50, xp=50)
    before = copy.deepcopy(pet)
    out = pet_logic.apply_effects(pet, fx)
    for need in pet_logic.NEED_STATS:
        assert _in_range(out[need])          # every need stays clamped
    assert out["coins"] == 50 and out["xp"] == 50  # needs-only: never grants power
    assert pet == before


# --- award ----------------------------------------------------------------
_TODAY = "2026-06-17"
# coins_today must enter the day within its valid bound; the cap is the invariant.
coins_today = st.integers(min_value=0, max_value=pet_logic.DAILY_COIN_CAP)
coin_award = st.integers(min_value=-100, max_value=1000)   # incl. negative (ignored)
xp_award = st.integers(min_value=-100, max_value=100_000)  # uncapped; negative ignored


@given(start_today=coins_today, lifetime=st.integers(0, 10_000), coins=coin_award, xp=xp_award)
def test_award_respects_daily_cap_grows_coins_and_leaves_xp_uncapped(
        start_today, lifetime, coins, xp):
    pet = _pet(coins=lifetime, coins_today=start_today, last_award_date=_TODAY, xp=0)
    before = copy.deepcopy(pet)
    out = pet_logic.award(pet, coins=coins, xp=xp, today=_TODAY)
    assert out["coins_today"] <= pet_logic.DAILY_COIN_CAP   # the cap binds, always
    assert out["coins"] >= pet["coins"]                     # earning never decreases coins
    assert out["coins_today"] >= start_today                # nor the daily counter (same day)
    assert out["xp"] == pet["xp"] + max(0, xp)              # XP is uncapped, negatives ignored
    assert pet == before


# --- apply_events ---------------------------------------------------------
_event_names = st.sampled_from([*pet_logic.EVENT_REWARDS, "nonsense", ""])
event_streams = st.lists(_event_names, max_size=200)


@given(events=event_streams, start_today=coins_today)
def test_apply_events_never_beats_the_cap_and_only_adds(events, start_today):
    pet = _pet(coins=0, coins_today=start_today, last_award_date=_TODAY, xp=0)
    before = copy.deepcopy(pet)
    out = pet_logic.apply_events(pet, events, today=_TODAY)
    assert out["coins_today"] <= pet_logic.DAILY_COIN_CAP   # a flood of events can't beat the cap
    assert out["coins"] >= pet["coins"]                     # only ever adds
    assert out["xp"] >= pet["xp"]
    assert pet == before


# --- level_for_xp ---------------------------------------------------------

@given(pair=st.tuples(st.integers(-500, 1_000_000), st.integers(-500, 1_000_000)))
def test_level_is_monotonic_non_decreasing_in_xp(pair):
    lo, hi = sorted(pair)
    assert pet_logic.level_for_xp(lo) <= pet_logic.level_for_xp(hi)


# --- stage_for ------------------------------------------------------------
# Ascending life stages: a pet must never evolve *backwards* as level/age grow.
_STAGE_ORDER = ("egg", "baby", "teen", "adult")
_age = st.floats(min_value=0.0, max_value=30 * pet_logic.DAY_S,
                 allow_nan=False, allow_infinity=False)


@given(levels=st.tuples(st.integers(0, 60), st.integers(0, 60)),
       ages=st.tuples(_age, _age))
def test_stage_never_regresses_as_level_and_age_increase(levels, ages):
    lo_lvl, hi_lvl = sorted(levels)
    lo_age, hi_age = sorted(ages)
    earlier = pet_logic.stage_for(lo_lvl, lo_age)
    later = pet_logic.stage_for(hi_lvl, hi_age)
    assert _STAGE_ORDER.index(earlier) <= _STAGE_ORDER.index(later)


# --- shop: buy / feed / play ---------------------------------------------
# Draw real catalog rows so the transforms see the exact data the GUI hands them.
_foods = [it for it in shop.CATALOG if it["type"] == shop.FOOD]
_toys = [it for it in shop.CATALOG if it["type"] == shop.TOY]
food_items = st.sampled_from(_foods)
toy_items = st.sampled_from(_toys)
owned_count = st.integers(min_value=1, max_value=5)
now = st.floats(min_value=0.0, max_value=1e9, allow_nan=False, allow_infinity=False)


@given(item=st.sampled_from(shop.CATALOG), coins=st.integers(0, 1000), held=st.integers(0, 5))
def test_buy_spends_price_floored_adds_one_and_never_mutates(item, coins, held):
    pet = _pet(coins=coins, inventory={item["id"]: held} if held else {})
    before = copy.deepcopy(pet)
    out = shop.buy(pet, item)
    assert out["coins"] == max(0, coins - item["price"])        # spent, floored at 0
    assert out["inventory"][item["id"]] == held + 1            # exactly one added
    assert pet == before


@given(item=food_items, hunger=stats, happiness=stats, energy=stats,
       held=owned_count, xp=st.integers(0, 10_000))
def test_feed_consumes_one_clamps_needs_grants_xp_and_never_mutates(
        item, hunger, happiness, energy, held, xp):
    pet = _pet(hunger=hunger, happiness=happiness, energy=energy, xp=xp,
               inventory={item["id"]: held})
    before = copy.deepcopy(pet)
    out = shop.feed(pet, item)
    for need in pet_logic.NEED_STATS:
        assert _in_range(out[need])                            # effects stay clamped
    assert out["inventory"].get(item["id"], 0) == held - 1     # exactly one consumed
    assert out["xp"] == xp + shop.CARE_XP                      # caring earns XP
    assert pet == before


@given(item=toy_items, hunger=stats, happiness=stats, energy=stats, held=owned_count,
       xp=st.integers(0, 10_000), played_at=now)
def test_play_keeps_toy_clamps_needs_sets_cooldown_and_never_mutates(
        item, hunger, happiness, energy, held, xp, played_at):
    pet = _pet(hunger=hunger, happiness=happiness, energy=energy, xp=xp,
               inventory={item["id"]: held})
    before = copy.deepcopy(pet)
    out = shop.play(pet, item, now=played_at)
    for need in pet_logic.NEED_STATS:
        assert _in_range(out[need])
    assert out["inventory"][item["id"]] == held               # toys are reusable, not consumed
    assert out["cooldowns"][item["id"]] == played_at          # cooldown stamped at now
    assert out["xp"] == xp + shop.CARE_XP
    assert pet == before


# --- roster: reconcile (issue #54) ---------------------------------------
# A small id alphabet so `shown` and `live` overlap often (the interesting cases).
_session_ids = st.text(alphabet="abcde", min_size=1, max_size=3)


def _live(ids):
    return {sid: {"session_id": sid, "state": "idle", "ts": 1.0, "subagents": []}
            for sid in ids}


@given(shown=st.sets(_session_ids, max_size=6), live_ids=st.sets(_session_ids, max_size=6))
def test_reconcile_partitions_every_session_and_bounds_the_roster(shown, live_ids):
    cmds = roster.reconcile(shown, _live(live_ids))
    create_ids = {sid for sid, _s, _i in cmds.create}
    update_ids = {sid for sid, _s in cmds.update}
    destroy_ids = set(cmds.destroy)

    # No session is ever in two buckets — in particular never both created and
    # destroyed (the ticket's key invariant).
    assert create_ids.isdisjoint(destroy_ids)
    assert create_ids.isdisjoint(update_ids)
    assert update_ids.isdisjoint(destroy_ids)
    # Every live session is shown exactly once; destroy is exactly shown-not-live.
    assert create_ids | update_ids == set(live_ids)
    assert destroy_ids == set(shown) - set(live_ids)
    # Applying the commands leaves a roster that IS the live set — bounded by it.
    resulting = (set(shown) - destroy_ids) | create_ids
    assert resulting == set(live_ids)


@given(live_ids=st.sets(_session_ids, min_size=1, max_size=6))
def test_reconcile_create_indices_are_the_sorted_positions(live_ids):
    # From an empty roster every session is created, each carrying its rank in the
    # sorted order — so the shell can place cards with no ordering logic of its own.
    cmds = roster.reconcile([], _live(live_ids))
    assert [(sid, i) for sid, _s, i in cmds.create] == \
        [(sid, i) for i, sid in enumerate(sorted(live_ids))]
