"""The Pet window's action seam, Tk-free (Deepen 5/6, #41).

The buy / feed / play / equip / pet-tap handlers as pure functions over a
:class:`~mascot.pet_host.PetHost`: each reads the pet from the host, checks the move
via the pure ``shop`` / ``cosmetics`` cores, persists the result through the host
(the single writer), celebrates care where the UI does, and returns the status line
to show. Lifting them out of the Tk widget lets the whole care flow be unit-tested
against a fake host with no Tk root.
"""
from __future__ import annotations

import time
from typing import Any

from . import cosmetics, pet_logic, shop
from .pet_host import PetHost


def _level(pet: dict[str, Any]) -> int:
    return pet_logic.level_for_xp(pet.get("xp", 0))


def buy(host: PetHost, item: dict[str, Any]) -> str:
    """Buy a shop item, spending coins into inventory. No-op with a reason when the
    level gate / price / one-toy rule blocks it (the shop core owns those reasons)."""
    pet = host.get_pet()
    ok, reason = shop.can_buy(pet, item, _level(pet))
    if not ok:
        return reason
    host.save_pet(shop.buy(pet, item))
    return f"Bought {item['name']}."


def feed(host: PetHost, item: dict[str, Any]) -> str:
    """Feed an owned food: apply its effects, consume one, earn care XP, celebrate."""
    pet = host.get_pet()
    ok, reason = shop.can_feed(pet, item)
    if not ok:
        return reason
    host.save_pet(shop.feed(pet, item))
    host.notify_care()
    return f"Fed {item['name']}. Yum!"


def play(host: PetHost, item: dict[str, Any], now: float) -> str:
    """Play with an owned toy (off cooldown): apply effects, start the cooldown, earn
    care XP, celebrate. The toy is reusable — not consumed."""
    pet = host.get_pet()
    ok, reason = shop.can_play(pet, item, now)
    if not ok:
        return reason
    host.save_pet(shop.play(pet, item, now))
    host.notify_care()
    return f"Played with {item['name']}!"


def buy_cosmetic(host: PetHost, piece: dict[str, Any]) -> str:
    """Buy a wardrobe piece (delight, never power): spend coins, add it, celebrate.
    Milestone pieces are never for sale — the cosmetics core owns that reason."""
    pet = host.get_pet()
    ok, reason = cosmetics.can_buy(pet, piece, _level(pet))
    if not ok:
        return reason
    host.save_pet(cosmetics.buy(pet, piece))
    host.notify_care()
    return f"Bought the {piece['name']}!"


def wear(host: PetHost, piece_id: str | None) -> str:
    """Wear an owned wardrobe piece (or take everything off with ``None``). Free,
    always — no celebration. Wearing an unowned piece is a no-op in the cosmetics core."""
    host.save_pet(cosmetics.equip(host.get_pet(), piece_id))
    if piece_id is None:
        return "Bare-headed again."
    piece = cosmetics.piece_by_id(piece_id)
    return f"Looking sharp in the {piece['name'] if piece else piece_id}."


def pet_tap(host: PetHost, now: float) -> None:
    """Pet the pet: a small daily-capped coin/XP trickle, persisted through the host.
    Shared by the on-card tap and the Pet-window pet tap. A no-op when the pet is off
    (simple mode), so the card's coin-on-tap is gated on the one ``pet_enabled`` flag.
    The caller owns any local reaction/celebration — petting sets no status line."""
    if not host.pet_enabled:
        return
    today = time.strftime("%Y-%m-%d", time.localtime(now))
    host.save_pet(pet_logic.apply_events(host.get_pet(), [pet_logic.PET], today=today))
