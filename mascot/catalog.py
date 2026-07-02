"""The shared acquisition core behind shop + cosmetics (Deepen 1/6, #36).

`shop` (food & toys, a coin `inventory`) and `cosmetics` (wardrobe hats) had the same
buy logic twice: a level gate, an affordability check, the coin-spend, and adding the
id to a collection. This is that logic, once — a pure, I/O-free core the two modules
are thin adapters over. What genuinely differs stays in them: how ownership is decided
(inventory count vs wardrobe membership) and their extra guards (a toy is a one-time
buy; a milestone piece is never for sale).
"""
from __future__ import annotations

from typing import Any


def can_acquire(pet: dict[str, Any], entry: dict[str, Any], level: int, *,
                owns: bool) -> tuple[bool, str]:
    """Whether `pet` may acquire catalog `entry` now: past its level gate, not already
    owned, and affordable — the checks shop and cosmetics share, in that order. The
    caller decides `owns` (stacking food is never "owned"; a toy or a hat is) and
    layers any domain guard (a milestone piece is never for sale) before calling."""
    if level < entry.get("min_level", 1):
        return False, f"Reach level {entry['min_level']} to unlock"
    if owns:
        return False, "Already owned"
    if pet.get("coins", 0) < entry["price"]:
        return False, "Not enough coins"
    return True, ""


def acquire(pet: dict[str, Any], entry: dict[str, Any], *, into: str) -> dict[str, Any]:
    """Spend `entry`'s price (coins floored at 0) and add its id to the `into`
    collection — appended to a list (a wardrobe) or +1 in a count dict (an inventory),
    matching whatever `into` already holds. Immutable: a new pet is returned, `pet` is
    untouched. Assumes `can_acquire` already said yes."""
    piece_id = entry["id"]
    coll = pet.get(into)
    if isinstance(coll, dict):
        added: dict[str, int] | list[str] = {**coll, piece_id: coll.get(piece_id, 0) + 1}
    else:
        added = [*(coll or []), piece_id]
    return {**pet, "coins": max(0, pet.get("coins", 0) - entry["price"]), into: added}
