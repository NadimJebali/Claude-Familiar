"""Data-driven shop catalog + pure buy/feed/play operations (Tamagotchi, #10).

The catalog is plain data: each item has a `price`, an `effects` map (stat->delta,
may be negative for trade-off items), a `type` (consumable `FOOD` vs reusable
`TOY`), an optional `cooldown_s` (toys), and a `min_level` gate. The operations are
pure pet transforms (no I/O, no clock except a passed-in `now`) returning a NEW pet
— they reuse `pet_logic.apply_effects` so item effects are clamped/negative-safe,
and coins buy only care items, never power (PRD).

Validation is split out into `can_buy`/`can_feed`/`can_play` (each returns
`(ok, reason)`); the `buy`/`feed`/`play` transforms assume their precondition holds
and just apply the change. The GUI checks `can_*` first and surfaces the reason.
"""
from __future__ import annotations

from typing import Any

from . import catalog, pet_logic

FOOD = "food"
TOY = "toy"

# XP earned from a single act of care (feeding or playing). Caring builds the bond
# (PRD user story 19); uncapped like all XP. Tuning, not structural.
CARE_XP = 5

# id, name, price, type, effects, [cooldown_s], min_level, desc. Higher tiers are
# level-gated; trade-off items carry mixed-sign effects. Amounts are a tuning pass.
CATALOG: list[dict[str, Any]] = [
    {"id": "snack", "name": "Snack", "price": 10, "type": FOOD,
     "effects": {"hunger": 25}, "min_level": 1, "desc": "A quick bite."},
    {"id": "meal", "name": "Hearty Meal", "price": 25, "type": FOOD,
     "effects": {"hunger": 60}, "min_level": 1, "desc": "Fills the belly up."},
    {"id": "energy_drink", "name": "Energy Drink", "price": 30, "type": FOOD,
     "effects": {"energy": 40, "happiness": -15}, "min_level": 2,
     "desc": "Wires it up — but a little grumpy."},
    {"id": "feast", "name": "Feast", "price": 60, "type": FOOD,
     "effects": {"hunger": 100, "happiness": 10}, "min_level": 3,
     "desc": "A full spread — stuffed and happy."},
    {"id": "ball", "name": "Ball", "price": 20, "type": TOY,
     "effects": {"happiness": 20}, "cooldown_s": 300, "min_level": 1,
     "desc": "Fetch! Reusable, with a short rest."},
    {"id": "puzzle", "name": "Puzzle Cube", "price": 50, "type": TOY,
     "effects": {"happiness": 35, "energy": -10}, "cooldown_s": 600, "min_level": 4,
     "desc": "Engaging — fun but a bit tiring."},
]


def item_by_id(item_id: str) -> dict[str, Any] | None:
    for item in CATALOG:
        if item["id"] == item_id:
            return item
    return None


def is_unlocked(item: dict[str, Any], level: int) -> bool:
    """True when the pet's `level` meets the item's level gate."""
    return level >= item.get("min_level", 1)


def owned(pet: dict[str, Any], item: dict[str, Any]) -> int:
    """How many of `item` the pet owns."""
    return int(pet.get("inventory", {}).get(item["id"], 0))


def can_buy(pet: dict[str, Any], item: dict[str, Any], level: int) -> tuple[bool, str]:
    """Whether the pet can buy `item` now: unlocked by level, affordable, and — for
    reusable toys — not already owned (a toy is a one-time purchase; food stacks).
    The level gate, price, and the shared reasons live in `catalog`."""
    owns = item.get("type") == TOY and owned(pet, item) >= 1
    return catalog.can_acquire(pet, item, level, owns=owns)


def buy(pet: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Spend the item's price and add one to inventory. Assumes `can_buy`. Coins
    are floored at 0 defensively. `pet` is not mutated."""
    return catalog.acquire(pet, item, into="inventory")


def can_feed(pet: dict[str, Any], item: dict[str, Any]) -> tuple[bool, str]:
    """Whether the pet can eat `item`: it's food and at least one is owned."""
    if item.get("type") != FOOD:
        return False, "Not food"
    if owned(pet, item) < 1:
        return False, "You don't own this"
    return True, ""


def feed(pet: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    """Consume one of `item`, apply its effects (clamped/negative-safe), and earn
    care XP. Assumes `can_feed`. `pet` is not mutated."""
    nxt = pet_logic.apply_effects(pet, item["effects"])
    inv = dict(pet.get("inventory", {}))
    remaining = max(0, inv.get(item["id"], 0) - 1)
    if remaining:
        inv[item["id"]] = remaining
    else:
        inv.pop(item["id"], None)
    nxt["inventory"] = inv
    nxt["xp"] = pet.get("xp", 0) + CARE_XP
    return nxt


def cooldown_remaining(pet: dict[str, Any], item: dict[str, Any], now: float) -> float:
    """Seconds until `item` can be played again (0 when ready)."""
    last = pet.get("cooldowns", {}).get(item["id"])
    if last is None:
        return 0.0
    return max(0.0, item.get("cooldown_s", 0) - (now - last))


def can_play(pet: dict[str, Any], item: dict[str, Any], now: float) -> tuple[bool, str]:
    """Whether the pet can play with `item`: it's a toy, owned, and off cooldown."""
    if item.get("type") != TOY:
        return False, "Not a toy"
    if owned(pet, item) < 1:
        return False, "You don't own this"
    remaining = cooldown_remaining(pet, item, now)
    if remaining > 0:
        return False, f"Resting ({int(remaining) + 1}s)"
    return True, ""


def play(pet: dict[str, Any], item: dict[str, Any], now: float) -> dict[str, Any]:
    """Play with `item`: apply its effects (clamped), start its cooldown, and earn
    care XP. The toy is reusable (not consumed). Assumes `can_play`. Not mutated."""
    nxt = pet_logic.apply_effects(pet, item["effects"])
    cooldowns = dict(pet.get("cooldowns", {}))
    cooldowns[item["id"]] = now
    nxt["cooldowns"] = cooldowns
    nxt["xp"] = pet.get("xp", 0) + CARE_XP
    return nxt
