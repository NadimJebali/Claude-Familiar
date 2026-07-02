"""Pure pet -> look projection (Deepen 3/6, #38).

One place that turns a pet into the visual facts a card or the Pet window needs: its
evolution ``stage``, the worn ``hat`` (a bare egg never wears one), the milestone
``flourish``, and the ``mood`` that tints the idle face. Clock-free and I/O-free (the
age clock is passed in as ``now``), mirroring the other pure cores so it's unit-tested
with synthetic pets. ``tkinter_app`` / ``pet_window`` consume the result instead of
each re-deriving stage/hat/flourish.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, NamedTuple

from . import cosmetics, pet_logic


class PetView(NamedTuple):
    """The pet's visual facts. ``hat`` is None when bare (or an egg); ``mood`` feeds
    the idle-face overlay (content/happy/hungry/sad/tired)."""
    stage: str
    hat: str | None
    flourish: bool
    mood: str


def pet_view(pet: Mapping[str, Any], *, now: float) -> PetView:
    """Project ``pet`` into its :class:`PetView` at time ``now``."""
    level = pet_logic.level_for_xp(pet.get("xp", 0))
    age = max(0.0, now - pet.get("born", now))
    stage = pet_logic.stage_for(level, age)
    hat = None if stage == "egg" else cosmetics.equipped_head(pet)
    return PetView(
        stage=stage,
        hat=hat,
        flourish=level >= pet_logic.MILESTONE_LEVEL,
        mood=pet_logic.mood(pet),
    )
