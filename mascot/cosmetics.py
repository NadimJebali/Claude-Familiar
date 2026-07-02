"""The wardrobe: cosmetic headwear the pet wears on the card (PRD #33).

Pure catalog + transforms, mirroring :mod:`mascot.shop`. Cosmetics are delight,
never power — a piece has NO effects path at all, structurally; it can only be
worn. Two acquisition tiers, split by meaning:

  * **Shop tier** — bought with coins at real prices, level-gated (including
    post-adult gates, so leveling keeps paying after the last stage).
  * **Milestone tier** — unbuyable; earned by shared history (``days_active``,
    which never decreases — the gentleness rule means an earned piece can never
    be lost or missed).

One ``head`` slot for now; ``equipped`` is a dict keyed by slot so future slots
need no schema change. The egg and the gravestone never wear anything (handled
at render time). All transforms return a NEW pet dict.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import catalog

SLOT_HEAD = "head"

# id, name, tier data, min_level, desc. A shop piece has `price`; a milestone
# piece has `days_active` (the lifetime days-together requirement) instead —
# never both. Prices are a tuning pass; the ladder is meant to make the daily
# coin cap worth saving: the top piece is roughly a week of real work.
CATALOG: list[dict[str, Any]] = [
    {"id": "party_hat", "name": "Party Hat", "price": 100, "min_level": 3,
     "desc": "A little celebration cone."},
    {"id": "beanie", "name": "Cozy Beanie", "price": 150, "min_level": 5,
     "desc": "For long thinking sessions."},
    {"id": "top_hat", "name": "Top Hat", "price": 250, "min_level": 8,
     "desc": "Terribly distinguished."},
    {"id": "wizard_hat", "name": "Wizard Hat", "price": 400, "min_level": 12,
     "desc": "For the arcane arts of software."},
    {"id": "propeller_cap", "name": "Propeller Cap", "price": 500, "min_level": 15,
     "desc": "The long save. Whirrs faintly."},
    {"id": "flower", "name": "Flower", "days_active": 7, "min_level": 1,
     "desc": "A week together. It grew this for you."},
    {"id": "crown", "name": "Crown", "days_active": 30, "min_level": 1,
     "desc": "A month together. Royalty, clearly."},
]


def piece_by_id(piece_id: str) -> dict[str, Any] | None:
    for piece in CATALOG:
        if piece["id"] == piece_id:
            return piece
    return None


def is_milestone(piece: dict[str, Any]) -> bool:
    """Milestone pieces are earned, never sold."""
    return "days_active" in piece


def owns(pet: dict[str, Any], piece: dict[str, Any]) -> bool:
    return piece["id"] in pet.get("wardrobe", [])


def requirement_text(piece: dict[str, Any]) -> str:
    """The lock line shown for an unearned milestone piece."""
    days = piece.get("days_active", 0)
    return f"{days} days together"


def can_buy(pet: dict[str, Any], piece: dict[str, Any], level: int) -> tuple[bool, str]:
    """Whether the shop tier will sell `piece` now. Milestone pieces are never for
    sale; the level gate, ownership (all pieces are permanent), and price live in
    `catalog`."""
    if is_milestone(piece):
        return False, requirement_text(piece)
    return catalog.can_acquire(pet, piece, level, owns=owns(pet, piece))


def buy(pet: dict[str, Any], piece: dict[str, Any]) -> dict[str, Any]:
    """Spend the price and add the piece to the wardrobe (permanent). Assumes
    `can_buy`. `pet` is not mutated."""
    return catalog.acquire(pet, piece, into="wardrobe")


def equip(pet: dict[str, Any], piece_id: str | None) -> dict[str, Any]:
    """Wear a wardrobe piece (or take everything off with ``None``). Wearing an
    unowned piece is a no-op — the wardrobe is the source of truth. Free to
    switch, always. `pet` is not mutated."""
    equipped = dict(pet.get("equipped", {}))
    if piece_id is None:
        equipped.pop(SLOT_HEAD, None)
    elif piece_id in pet.get("wardrobe", []):
        equipped[SLOT_HEAD] = piece_id
    else:
        return dict(pet)
    return {**pet, "equipped": equipped}


def equipped_head(pet: Mapping[str, Any]) -> str | None:
    """The worn head piece's id, or None (bare)."""
    return pet.get("equipped", {}).get(SLOT_HEAD)


def grant_milestones(pet: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Add every milestone piece the pet's history has earned but doesn't own yet.

    Idempotent — call it after every tick; already-owned pieces are skipped, and
    since ``days_active`` never decreases, a granted piece can never be un-earned.
    Returns (new_pet, newly_earned_ids); the pet is unchanged (same dict contents)
    when nothing new was earned. `pet` is not mutated.
    """
    days = pet.get("days_active", 0)
    newly = [p["id"] for p in CATALOG
             if is_milestone(p) and days >= p["days_active"] and not owns(pet, p)]
    if not newly:
        return dict(pet), []
    return {**pet, "wardrobe": [*pet.get("wardrobe", []), *newly]}, newly
