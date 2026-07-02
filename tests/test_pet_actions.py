"""Tests for pet_actions: the Tk-free Pet-window action seam (Deepen 5/6, #41).

pet_actions lifts the Pet window's buy / feed / play / equip / pet-tap handlers out of
the Tk widget into pure functions over a PetHost port, so the whole care flow — check
-> apply via shop/cosmetics -> persist through the host -> celebrate — is unit-tested
against a fake host with no Tk root (same style as test_tray's callback-routing seams).

The FakeHost is the PetHost port: it holds the pet, records every save, and counts the
notify_care / open_pet routing so a test can assert both the persisted pet and where
the action routed.
"""
from __future__ import annotations

from typing import Any

from mascot import cosmetics, pet_actions, pet_store, shop


class FakeHost:
    """In-memory PetHost: records saves + care/open routing, like test_tray's fakes."""

    def __init__(self, pet: dict, *, pet_enabled: bool = True) -> None:
        self._pet = dict(pet)
        self.pet_enabled = pet_enabled
        self.saved: list[dict] = []
        self.care_calls = 0
        self.open_calls = 0

    def get_pet(self) -> dict[str, Any]:
        return dict(self._pet)

    def save_pet(self, pet: dict[str, Any]) -> dict[str, Any]:
        self._pet = dict(pet)
        self.saved.append(dict(pet))
        return dict(self._pet)

    def notify_care(self) -> None:
        self.care_calls += 1

    def open_pet(self) -> None:
        self.open_calls += 1


def _pet(**over) -> dict:
    p = pet_store.default_pet(1000.0)
    p.update(over)
    return p


# --- tracer bullet -----------------------------------------------------------
def test_buy_persists_the_bought_item_through_the_host():
    host = FakeHost(_pet(coins=100))
    status = pet_actions.buy(host, shop.item_by_id("snack"))   # 10 coins, level 1
    assert host.saved, "buy did not persist through the host"
    saved = host.saved[-1]
    assert saved["inventory"].get("snack") == 1
    assert saved["coins"] == 90
    assert status == "Bought Snack."


def test_buy_that_cannot_be_afforded_returns_a_reason_and_does_not_persist():
    host = FakeHost(_pet(coins=0))
    status = pet_actions.buy(host, shop.item_by_id("snack"))
    assert host.saved == []            # nothing persisted
    assert status and "Bought" not in status   # a blocking reason, not success


# --- feeding: consumes food, restores a need, and celebrates the cards --------
def test_feed_consumes_the_food_persists_and_notifies_care():
    host = FakeHost(_pet(inventory={"snack": 1}, hunger=50.0))
    status = pet_actions.feed(host, shop.item_by_id("snack"))
    saved = host.saved[-1]
    assert saved["hunger"] > 50.0                    # the snack restored hunger
    assert saved["inventory"].get("snack", 0) == 0   # ...and was consumed
    assert host.care_calls == 1                      # feeding celebrates the cards
    assert "Fed" in status


def test_feed_you_do_not_own_returns_a_reason_without_persisting_or_celebrating():
    host = FakeHost(_pet(inventory={}))
    status = pet_actions.feed(host, shop.item_by_id("snack"))
    assert host.saved == []
    assert host.care_calls == 0
    assert status and "Fed" not in status


# --- playing: reusable toy, starts a cooldown, celebrates ---------------------
def test_play_with_a_toy_persists_notifies_care_and_starts_a_cooldown():
    host = FakeHost(_pet(inventory={"ball": 1}, happiness=40.0))
    status = pet_actions.play(host, shop.item_by_id("ball"), now=1000.0)
    saved = host.saved[-1]
    assert saved["happiness"] > 40.0                 # the ball raised happiness
    assert saved["cooldowns"].get("ball") == 1000.0  # ...and started its cooldown
    assert host.care_calls == 1
    assert "Played" in status


def test_play_while_resting_returns_a_reason_without_persisting():
    host = FakeHost(_pet(inventory={"ball": 1}, cooldowns={"ball": 1000.0}))
    status = pet_actions.play(host, shop.item_by_id("ball"), now=1100.0)  # 100s into 300s
    assert host.saved == []
    assert host.care_calls == 0
    assert status and "Played" not in status


# --- cosmetics: buying a hat celebrates; wearing it is free -------------------
def test_buy_cosmetic_persists_the_piece_and_notifies_care():
    host = FakeHost(_pet(coins=200, xp=200))   # level 3, affords the 100c Party Hat
    status = pet_actions.buy_cosmetic(host, cosmetics.piece_by_id("party_hat"))
    assert "party_hat" in host.saved[-1]["wardrobe"]
    assert host.care_calls == 1
    assert "Party Hat" in status


def test_wear_equips_an_owned_piece_and_persists_without_celebrating():
    host = FakeHost(_pet(wardrobe=["party_hat"]))
    status = pet_actions.wear(host, "party_hat")
    assert host.saved[-1]["equipped"].get("head") == "party_hat"
    assert host.care_calls == 0        # wearing is free — no celebration
    assert status


def test_wear_none_takes_the_hat_off():
    host = FakeHost(_pet(wardrobe=["party_hat"], equipped={"head": "party_hat"}))
    pet_actions.wear(host, None)
    assert "head" not in host.saved[-1]["equipped"]


# --- petting: the trickle shared by the card tap and the Pet-window pet tap ----
def test_pet_tap_applies_the_pet_trickle_and_persists():
    host = FakeHost(_pet(coins=0, xp=0))
    pet_actions.pet_tap(host, now=1000.0)
    saved = host.saved[-1]
    assert saved["coins"] > 0 and saved["xp"] > 0    # the [PET] event trickled in


def test_pet_tap_is_a_no_op_in_simple_mode():
    # Simple hook-visualiser mode: pet_enabled is False, so a card tap earns nothing.
    host = FakeHost(_pet(coins=0), pet_enabled=False)
    pet_actions.pet_tap(host, now=1000.0)
    assert host.saved == []
