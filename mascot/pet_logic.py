"""Pure pet-logic core for Tamagotchi mode (see PRD #8, issue #9).

The engine that turns Claude activity + elapsed time into a virtual pet's stats,
mood, coins, XP, level and life stage. Every function here is **clock-free and
I/O-free**: elapsed time, "today", and the working/idle flag are passed in, and
each function returns a NEW pet dict (never mutates its input). That mirrors the
existing pure cores (`state_logic.compute_next_state`, `effective_state.compute`,
`osplatform.choose_work_area`) so it can be unit-tested with synthetic inputs.

The thin persistence wrapper (`pet_store`) owns `pet.json` and the clock; the
widget (`manager`) is the single writer and feeds this core real elapsed time and
session-state transitions.

Soft-needs tone (PRD): needs only ever *dull the mood* — they never sicken or kill
the pet, and 0 is just "very hungry/tired/sad", not a failure state. The gravestone
stays reserved for usage limits (handled by `state_logic`, not here).

Tuning note: the decay rates and coin/XP amounts below are deliberately gentle and
are a *balancing pass*, not structural — they can change without breaking the
behavioral tests, which assert direction/clamping/monotonicity, not magnitudes.
"""
from __future__ import annotations

from typing import Any

# Stats are 0..MAX_STAT. This is the bar range, not a tuning knob.
MAX_STAT = 100

# The three needs the user tends. Item effects may only ever touch these — never
# coins/XP — so a shop item can grant care/cosmetics but never power (PRD).
NEED_STATS = ("hunger", "happiness", "energy")

# Gentle per-hour need rates. Hunger/happiness always drift down; energy drains
# while Claude works and *refills* while idle/asleep, reusing the work rhythm.
HUNGER_DECAY_PER_HOUR = 8.0
HAPPINESS_DECAY_PER_HOUR = 6.0
ENERGY_DRAIN_PER_HOUR = 15.0    # while working
ENERGY_REFILL_PER_HOUR = 25.0   # while idle/asleep (recovers faster than it drains)

# A global daily ceiling on *coins* (not XP), shared across all sessions, so it
# never pays to make extra Claude calls just to farm currency (PRD user story 3).
# The counter resets on the first award of a new calendar day.
DAILY_COIN_CAP = 200


def _clamp_stat(value: float) -> float:
    """Keep a stat within [0, MAX_STAT] (negative-safe, never above max)."""
    return max(0.0, min(float(MAX_STAT), value))


def decay(pet: dict[str, Any], elapsed_s: float, working: bool) -> dict[str, Any]:
    """Apply time-based need decay over `elapsed_s` seconds.

    Hunger and happiness drift down; energy drains while `working` and refills
    while idle/asleep. All stats are clamped to [0, MAX_STAT]. A zero or negative
    elapsed (e.g. clock skew on load) is a safe no-op. `pet` is not mutated.
    """
    hours = max(0.0, elapsed_s) / 3600.0
    nxt = dict(pet)
    nxt["hunger"] = _clamp_stat(pet["hunger"] - HUNGER_DECAY_PER_HOUR * hours)
    nxt["happiness"] = _clamp_stat(pet["happiness"] - HAPPINESS_DECAY_PER_HOUR * hours)
    rate = -ENERGY_DRAIN_PER_HOUR if working else ENERGY_REFILL_PER_HOUR
    nxt["energy"] = _clamp_stat(pet["energy"] + rate * hours)
    return nxt


def apply_effects(pet: dict[str, Any], effects: dict[str, float]) -> dict[str, Any]:
    """Apply a shop item's `effects` map (stat -> delta) to the pet's needs.

    Deltas may be negative (trade-off items, e.g. +energy/-happiness); each
    affected stat is clamped to [0, MAX_STAT]. Keys outside `NEED_STATS` are
    ignored, so an item can never grant coins, XP, or any other advantage.
    `pet` is not mutated.
    """
    nxt = dict(pet)
    for stat, delta in effects.items():
        if stat in NEED_STATS:
            nxt[stat] = _clamp_stat(pet[stat] + delta)
    return nxt


def award(pet: dict[str, Any], *, coins: int = 0, xp: int = 0, today: str) -> dict[str, Any]:
    """Award coins (daily-capped) and XP (uncapped) for the calendar day `today`.

    `coins` is added only up to the remaining `DAILY_COIN_CAP` for `today`; on the
    first award of a new day the daily counter resets. The lifetime `coins` total
    only ever grows. `xp` is added in full. Negative awards are ignored (this is an
    earning path; spending lives elsewhere). `pet` is not mutated.
    """
    nxt = dict(pet)
    if pet.get("last_award_date") != today:
        nxt["coins_today"] = 0
        nxt["last_award_date"] = today
    allowed = max(0, DAILY_COIN_CAP - nxt["coins_today"])
    gained = max(0, min(coins, allowed))
    nxt["coins"] = pet["coins"] + gained
    nxt["coins_today"] = nxt["coins_today"] + gained
    nxt["xp"] = pet["xp"] + max(0, xp)
    return nxt


# Earnable events. The widget derives turn_completed / subagent_finished from
# polled session-state transitions; first_prompt_of_day (a daily streak bonus) and
# pet (a petting trickle) are emitted by the widget directly from their triggers.
TURN_COMPLETED = "turn_completed"
SUBAGENT_FINISHED = "subagent_finished"
FIRST_PROMPT_OF_DAY = "first_prompt_of_day"
PET = "pet"


def events_for_transition(prev: dict[str, Any], nxt: dict[str, Any]) -> list[str]:
    """Derive earnable events from one session-state transition (no clock).

    A `working`/`thinking` -> `idle` transition is a completed turn. Every
    sub-agent badge that was present in `prev` but gone in `nxt` is a finished
    sub-agent (a Stop that both ends the turn and clears leftover badges yields
    both). `waiting`/`dead` transitions are never a completed turn (mirrors the
    happy-celebrate trigger).
    """
    events: list[str] = []
    if prev.get("state") in ("working", "thinking") and nxt.get("state") == "idle":
        events.append(TURN_COMPLETED)
    prev_ids = {s.get("id") for s in prev.get("subagents", [])}
    nxt_ids = {s.get("id") for s in nxt.get("subagents", [])}
    events.extend(SUBAGENT_FINISHED for _ in (prev_ids - nxt_ids))
    return events


# event -> (coins, xp). Varied so earning feels tied to how you actually work
# (PRD user story 4). All amounts are a tuning pass, not structural.
EVENT_REWARDS: dict[str, tuple[int, int]] = {
    TURN_COMPLETED:      (5, 10),
    SUBAGENT_FINISHED:   (3, 5),
    FIRST_PROMPT_OF_DAY: (20, 0),   # a daily streak bonus
    PET:                 (1, 1),    # a gentle petting trickle
}


def apply_events(pet: dict[str, Any], events: list[str], *, today: str) -> dict[str, Any]:
    """Award the coins/XP for a sequence of earnable `events` on day `today`.

    Each known event is looked up in `EVENT_REWARDS` and funneled through `award`,
    so the global daily coin cap still binds no matter how many events arrive.
    Unknown events are ignored. `pet` is not mutated.
    """
    for event in events:
        coins, xp = EVENT_REWARDS.get(event, (0, 0))
        if coins or xp:
            pet = award(pet, coins=coins, xp=xp, today=today)
    return pet


# Mood thresholds (tuning, not structural). A need at/below LOW_NEED drags the
# mood down; all needs at/above HIGH_NEED make the pet sparkle.
LOW_NEED = 25
HIGH_NEED = 70


def mood(pet: dict[str, Any]) -> str:
    """Derive the pet's mood from its needs (for the idle-face overlay, #11).

    The single most-depleted need decides a low mood (`hungry`/`tired`/`sad`); if
    nothing is depleted and every need is high, the pet is `happy`; otherwise it is
    `content`. Ties break deterministically hunger -> energy -> happiness.
    """
    h, hap, e = pet["hunger"], pet["happiness"], pet["energy"]
    by_need = {"hungry": h, "tired": e, "sad": hap}   # insertion order = tie-break
    label, lowest = min(by_need.items(), key=lambda kv: kv[1])
    if lowest <= LOW_NEED:
        return label
    if min(h, hap, e) >= HIGH_NEED:
        return "happy"
    return "content"


# A gentle, flat level curve: every level costs the same XP. Level 1 is a new pet;
# the first level-up (hatching the egg) lands at XP_PER_LEVEL. Tuning, not structural.
XP_PER_LEVEL = 100


def level_for_xp(xp: int) -> int:
    """The pet's level for a given lifetime XP. Level 1 at 0 XP, +1 per XP_PER_LEVEL."""
    return 1 + max(0, int(xp)) // XP_PER_LEVEL


DAY_S = 86400.0

# (stage, min_level, min_age_s), ascending. A stage applies only when BOTH its
# level and age gates are met; the highest satisfied stage wins. The egg is the
# base (always satisfied for a level>=1 pet) and hatches to baby on the first
# level-up. The age gates make evolution honor real elapsed time. Tuning, not
# structural — art for each stage arrives in #12.
_STAGE_THRESHOLDS: tuple[tuple[str, int, float], ...] = (
    ("egg",   1, 0.0),
    ("baby",  2, 0.0),
    ("teen",  5, 1 * DAY_S),
    ("adult", 10, 3 * DAY_S),
)


def stage_for(level: int, age_s: float) -> str:
    """The pet's life stage from its level and age (egg/baby/teen/adult).

    A stage requires both its minimum level and minimum age; the highest stage
    that qualifies wins, so a high level reached too quickly still waits out the
    age gate before evolving.
    """
    stage = "egg"
    for name, min_level, min_age in _STAGE_THRESHOLDS:
        if level >= min_level and age_s >= min_age:
            stage = name
    return stage
