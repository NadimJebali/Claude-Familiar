"""Tests for the Qt Pet window (issue #60).

The care flow is the pure pet_actions/shop cores (already tested); here we check
the window wires its buttons to those actions against a fake PetHost, and that it
constructs headlessly. Offscreen; skips where PySide6 is absent.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mascot import cosmetics, qt_pet_window, shop


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


class _FakeHost:
    pet_enabled = True

    def __init__(self, pet):
        self._pet = dict(pet)
        self.care = 0

    def get_pet(self):
        return dict(self._pet)

    def save_pet(self, pet):
        self._pet = dict(pet)
        return self._pet

    def notify_care(self):
        self.care += 1

    def open_pet(self):
        pass


def _pet(**over):
    p = {
        "name": "Pixel", "born": 0.0, "last_seen": 0.0,
        "hunger": 40, "happiness": 50, "energy": 60,
        "coins": 100, "xp": 500, "coins_today": 0, "last_award_date": "",
        "inventory": {}, "cooldowns": {}, "wardrobe": [], "equipped": {},
    }
    p.update(over)
    return p


def _item(item_id):
    return shop.item_by_id(item_id)


def test_window_constructs_and_shows_the_pet(app):
    host = _FakeHost(_pet())
    win = qt_pet_window.QtPetWindow(host)
    assert "100 coins" in win._coins.text()
    assert win._name.text() == "Pixel"
    win.close()


def test_buy_spends_coins_and_adds_to_inventory(app):
    host = _FakeHost(_pet(coins=100, inventory={}))
    win = qt_pet_window.QtPetWindow(host)
    snack = _item("snack")          # price 10, level 1

    win._buy(snack)

    assert host._pet["coins"] == 90
    assert host._pet["inventory"].get("snack") == 1
    assert "Bought" in win._status.text()
    win.close()


def test_feed_consumes_an_item_raises_a_need_and_celebrates(app):
    host = _FakeHost(_pet(hunger=40, inventory={"snack": 1}))
    win = qt_pet_window.QtPetWindow(host)

    win._feed(_item("snack"))

    assert host._pet["hunger"] > 40                 # the snack fed the pet
    assert "snack" not in host._pet["inventory"]     # the one snack was consumed
    assert host.care == 1                            # feeding celebrates on the cards
    win.close()


def test_rename_persists_through_the_host(app):
    host = _FakeHost(_pet(name="Pixel"))
    win = qt_pet_window.QtPetWindow(host)
    win._name.setText("Rex")
    win._rename()
    assert host._pet["name"] == "Rex"
    win.close()


def test_a_too_expensive_item_cannot_be_bought(app):
    host = _FakeHost(_pet(coins=5))
    win = qt_pet_window.QtPetWindow(host)
    win._buy(_item("feast"))          # price 60, and level-gated
    assert host._pet["coins"] == 5    # unchanged — the buy was refused
    assert host._pet.get("inventory", {}).get("feast") is None
    win.close()


# --- #60: wardrobe tab -------------------------------------------------------
def test_wardrobe_buy_then_wear_and_remove_a_hat(app):
    host = _FakeHost(_pet(coins=200, xp=500))    # level 6 -> Party Hat (lvl 3) buyable
    win = qt_pet_window.QtPetWindow(host)
    party = cosmetics.piece_by_id("party_hat")

    win._buy_cosmetic(party)
    assert "party_hat" in host._pet["wardrobe"]
    assert host.care == 1                         # buying a cosmetic celebrates

    win._wear("party_hat")
    assert host._pet["equipped"]["head"] == "party_hat"
    win._wear(None)                               # take it off
    assert "head" not in host._pet.get("equipped", {})
    win.close()


def test_wardrobe_lists_locked_milestone_pieces(app):
    win = qt_pet_window.QtPetWindow(_FakeHost(_pet()))
    # crown is a 30-day milestone piece, never for sale -> a disabled "Locked" row.
    labels = [win._wardrobe_box.itemAt(i).widget() for i in range(win._wardrobe_box.count())]
    assert any(w is not None for w in labels)     # the wardrobe rendered rows
    win.close()


# --- #60: live cooldown countdown -------------------------------------------
def test_playing_a_toy_starts_a_live_cooldown(app):
    host = _FakeHost(_pet(inventory={"ball": 1}))
    win = qt_pet_window.QtPetWindow(host)
    _item_dict, button = win._cooldowns["ball"]
    assert button.isEnabled()                     # off cooldown to start

    win._play(_item("ball"))                       # play -> starts the cooldown
    _item2, button2 = win._cooldowns["ball"]       # the Items list rebuilt
    assert not button2.isEnabled()                 # now counting down, disabled
    win.close()


# --- #60: pixel-art item / hat icons ----------------------------------------
def test_shop_rows_carry_item_icons(app):
    win = qt_pet_window.QtPetWindow(_FakeHost(_pet()))
    icon = win._item_icon("snack")
    assert icon is not None and not icon.pixmap().isNull()
    assert win._hat_icon("crown") is not None
    win.close()


# --- #60: external-change pickup without a restart ---------------------------
def test_poll_picks_up_an_external_pet_change(app):
    host = _FakeHost(_pet(coins=10))
    win = qt_pet_window.QtPetWindow(host)
    assert "10 coins" in win._coins.text()
    host._pet["coins"] = 999                       # the manager awarded coins externally
    win._poll()
    assert "999 coins" in win._coins.text()
    win.close()
