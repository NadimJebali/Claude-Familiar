"""The Pet window — the home for caring for the Tamagotchi pet (issue #10).

Shows the pet, its three need bars, coins, name, level and inventory, plus a
data-driven shop with Buy / Feed / Play actions. Pure-stdlib Tk, styled with the
control panel's dark theme.

Persistence is abstracted behind two callbacks so the same window works either:
  * in the widget (manager) process, opened from the tray — sharing the manager's
    live in-memory pet (no cross-process write races); or
  * standalone, opened from Settings (``python -m mascot.pet_window``) — reading
    and writing ``pet.json`` directly via ``pet_store`` with a read-modify-write
    on every action so it never clobbers the manager's concurrent decay/awards.

Feeding and playing reuse the mascot's existing happy reaction + pixel hearts (on
the pet shown here, and — in-process — on the session cards via ``on_care``).
"""
from __future__ import annotations

import random
import time
import tkinter as tk
from collections.abc import Callable
from functools import partial
from tkinter import ttk
from typing import Any

from . import config, cosmetics, item_art, pet_logic, pet_store, shop, sprite_pixel, ui_icons
from .control_panel import (
    BG,
    MUTED,
    PANEL,
    _apply_theme,
)
from .pet_view import pet_view
from .tkinter_app import round_rect

NAME_MAX = 16
CELEBRATE_S = 1.5
HEART_LIFETIME_S = 0.85
ANIM_MS = 40
TICK_MS = 600

PET_PX = 6                      # creature pixel size in the window
PET_CANVAS_W, PET_CANVAS_H = 180, 150
BAR_W, BAR_H = 150, 14
BAR_LABEL_H = 13                # room for the need label above each bar
BAR_SLOT = BAR_LABEL_H + BAR_H + 6   # label + bar + gap, per need

# Need-bar colors (shared with the tooltip via config) + their display labels.
NEED_COLORS = config.NEED_COLORS
NEED_LABELS = {"hunger": "Hunger", "happiness": "Happy", "energy": "Energy"}
TRACK = "#2a2d3b"


def _effects_text(effects: dict[str, int]) -> str:
    """A compact, signed summary of an item's effects, e.g. '+40 energy, -15 happy'."""
    short = {"hunger": "hunger", "happiness": "happy", "energy": "energy"}
    parts = [f"{'+' if v >= 0 else ''}{v} {short.get(k, k)}" for k, v in effects.items()]
    return ", ".join(parts)


class PetWindow:
    """The pet dashboard + shop. Owns a Toplevel; persistence via callbacks."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        load_pet: Callable[[], dict[str, Any]],
        save_pet: Callable[[dict[str, Any]], dict[str, Any]],
        on_care: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        self._load_pet = load_pet
        self._save_pet = save_pet
        self._on_care = on_care
        self._on_close = on_close
        self._alive = True
        self._celebrate_until = 0.0
        self._hearts: list[dict[str, float]] = []
        self._list_sig: tuple | None = None
        self._cached_pet: dict[str, Any] = {}   # latest pet for the 25fps sprite loop
        # toy_id -> (item, play_btn, label) for the live cooldown countdown
        self._cooldowns: dict[str, tuple] = {}

        self.root = tk.Toplevel(parent)
        self.root.title("Claude Familiar — Pet")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        _apply_theme(self.root)
        try:
            from . import icon
            icon.apply(self.root)
        except Exception:  # noqa: BLE001 — the icon is cosmetic
            pass
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.name_var = tk.StringVar()
        self.coins_var = tk.StringVar()
        self.level_var = tk.StringVar()
        self.status = tk.StringVar(value="")

        self._build()
        self._refresh(force=True)
        # Pin the window to its natural size so rebuilding the shop/inventory lists
        # (which briefly empties their frames) can't make the window resize-flicker.
        self.root.update_idletasks()
        self.root.geometry(f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}")
        self.root.after(ANIM_MS, self._animate)
        self.root.after(TICK_MS, self._tick)

    # --- layout -----------------------------------------------------------
    def _build(self) -> None:
        header = ttk.Frame(self.root)
        header.pack(fill="x", padx=16, pady=(12, 4))
        self._paw_img = ui_icons.photo(self.root, "paw", px=2)
        self._coin_img = ui_icons.photo(self.root, "coin", px=2)
        ttk.Label(header, image=self._paw_img, background=BG).pack(side="left", padx=(0, 6))
        ttk.Label(header, textvariable=self.name_var, style="Header.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.coins_var, style="MutedBG.TLabel").pack(
            side="right", pady=(8, 0))
        ttk.Label(header, image=self._coin_img, background=BG).pack(
            side="right", padx=(0, 3), pady=(8, 0))
        ttk.Label(header, textvariable=self.level_var, style="MutedBG.TLabel").pack(
            side="right", padx=(0, 12), pady=(8, 0))

        body = ttk.Frame(self.root)
        body.pack(fill="both", expand=True, padx=14, pady=4)

        # Left: the pet + need bars + rename.
        left = ttk.Frame(body, style="Card.TFrame", padding=12)
        left.pack(side="left", fill="y")
        self.pet_canvas = tk.Canvas(left, width=PET_CANVAS_W, height=PET_CANVAS_H,
                                    bg=PANEL, highlightthickness=0, bd=0)
        self.pet_canvas.pack()
        self.pet_canvas.bind("<Button-1>", lambda _e: self._pet_tap())

        self.bars = tk.Canvas(left, width=BAR_W, height=BAR_SLOT * 3,
                              bg=PANEL, highlightthickness=0, bd=0)
        self.bars.pack(pady=(8, 6))

        # Shared history: the current streak + lifetime days together (never lost).
        self.streak_var = tk.StringVar()
        ttk.Label(left, textvariable=self.streak_var, style="Muted.TLabel").pack(
            anchor="w", pady=(0, 4))

        rename = ttk.Frame(left, style="Card.TFrame")
        rename.pack(fill="x")
        self.name_entry = ttk.Entry(rename, width=14)
        self.name_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(rename, text="Rename", command=self._rename).pack(side="right", padx=(6, 0))

        # Right: Shop + Items + Wardrobe tabs.
        nb = ttk.Notebook(body)
        nb.pack(side="right", fill="both", expand=True, padx=(12, 0))
        self.shop_tab = ttk.Frame(nb, style="Card.TFrame", padding=10)
        self.items_tab = ttk.Frame(nb, style="Card.TFrame", padding=10)
        self.wardrobe_tab = ttk.Frame(nb, style="Card.TFrame", padding=10)
        nb.add(self.shop_tab, text="  Shop  ")
        nb.add(self.items_tab, text="  Items  ")
        nb.add(self.wardrobe_tab, text="  Wardrobe  ")

        ttk.Label(self.root, textvariable=self.status, style="MutedBG.TLabel",
                  wraplength=440, justify="left").pack(anchor="w", padx=16, pady=(0, 10))

    # --- pet state helpers ------------------------------------------------
    def _pet(self) -> dict[str, Any]:
        return self._load_pet()

    def _level(self, pet: dict[str, Any]) -> int:
        return pet_logic.level_for_xp(pet.get("xp", 0))

    def _commit(self, pet: dict[str, Any]) -> None:
        """Persist a new pet and refresh the display."""
        self._save_pet(pet)
        self._refresh(force=True)

    # --- actions ----------------------------------------------------------
    def _rename(self) -> None:
        name = self.name_entry.get().strip()[:NAME_MAX]
        pet = dict(self._pet())
        pet["name"] = name
        self._commit(pet)
        self.status.set(f"Named your pet “{name}”." if name else "Cleared the pet's name.")

    def _buy(self, item: dict[str, Any]) -> None:
        pet = self._pet()
        ok, reason = shop.can_buy(pet, item, self._level(pet))
        if not ok:
            self.status.set(reason)
            return
        self._commit(shop.buy(pet, item))
        self.status.set(f"Bought {item['name']}.")

    def _feed(self, item: dict[str, Any]) -> None:
        pet = self._pet()
        ok, reason = shop.can_feed(pet, item)
        if not ok:
            self.status.set(reason)
            return
        self._commit(shop.feed(pet, item))
        self._celebrate()
        self.status.set(f"Fed {item['name']}. Yum!")

    def _play(self, item: dict[str, Any]) -> None:
        pet = self._pet()
        ok, reason = shop.can_play(pet, item, time.time())
        if not ok:
            self.status.set(reason)
            return
        self._commit(shop.play(pet, item, time.time()))
        self._celebrate()
        self.status.set(f"Played with {item['name']}!")

    def _buy_cosmetic(self, piece: dict[str, Any]) -> None:
        pet = self._pet()
        ok, reason = cosmetics.can_buy(pet, piece, self._level(pet))
        if not ok:
            self.status.set(reason)
            return
        self._commit(cosmetics.buy(pet, piece))
        self._celebrate()
        self.status.set(f"Bought the {piece['name']}!")

    def _wear(self, piece_id: str | None) -> None:
        """Wear a wardrobe piece (or take the current one off with None). Free."""
        self._commit(cosmetics.equip(self._pet(), piece_id))
        if piece_id:
            piece = cosmetics.piece_by_id(piece_id)
            self.status.set(f"Looking sharp in the {piece['name'] if piece else piece_id}.")
        else:
            self.status.set("Bare-headed again.")

    def _pet_tap(self) -> None:
        """Tapping the pet pets it: a happy reaction + hearts + a small coin trickle."""
        today = time.strftime("%Y-%m-%d", time.localtime())
        self._commit(pet_logic.apply_events(self._pet(), [pet_logic.PET], today=today))
        self._celebrate()

    def _celebrate(self) -> None:
        now = time.time()
        self._celebrate_until = now + CELEBRATE_S
        for _ in range(3):
            self._hearts.append({
                "x": PET_CANVAS_W / 2 + random.uniform(-16, 16),
                "y0": PET_CANVAS_H / 2,
                "t0": now + random.uniform(0.0, 0.15),
                "drift": random.uniform(-12.0, 12.0),
            })
        self._hearts = self._hearts[-6:]
        if self._on_care is not None:
            try:
                self._on_care()
            except Exception as exc:  # noqa: BLE001
                print("[mascot] pet on_care failed:", exc)

    # --- rendering --------------------------------------------------------
    def _refresh(self, force: bool = False) -> None:
        pet = self._pet()
        self._cached_pet = pet
        level = self._level(pet)
        name = pet.get("name") or "Your Pet"
        self.name_var.set(name)
        self.coins_var.set(str(pet.get("coins", 0)))
        self.level_var.set(f"Lv {level}")
        if self.name_entry.get() == "" and pet.get("name"):
            self.name_entry.insert(0, pet["name"])
        self._draw_bars(pet)
        streak, days = pet.get("streak", 0), pet.get("days_active", 0)
        self.streak_var.set(f"streak {streak} · {days} day{'s' if days != 1 else ''} together")

        # The lists only rebuild on these (coins/level/inventory/wardrobe); the toy
        # cooldown countdown updates live in _update_cooldowns, so it isn't in the sig.
        sig = (pet.get("coins", 0), level, tuple(sorted(pet.get("inventory", {}).items())),
               tuple(pet.get("wardrobe", [])), cosmetics.equipped_head(pet),
               pet.get("days_active", 0))
        if force or sig != self._list_sig:
            self._list_sig = sig
            self._build_shop(pet, level)
            self._build_items(pet)
            self._build_wardrobe(pet, level)
        self._update_cooldowns()

    def _draw_bars(self, pet: dict[str, Any]) -> None:
        c = self.bars
        c.delete("all")
        for i, need in enumerate(("hunger", "happiness", "energy")):
            top = i * BAR_SLOT
            value = max(0, min(pet_logic.MAX_STAT, pet.get(need, 0)))
            frac = value / pet_logic.MAX_STAT
            # label sits fully inside the canvas, above its bar (anchor nw at the slot top)
            c.create_text(1, top, anchor="nw", text=NEED_LABELS[need],
                          fill=MUTED, font=("Segoe UI", 7))
            bar_y = top + BAR_LABEL_H
            round_rect(c, 0, bar_y, BAR_W, bar_y + BAR_H, 6, fill=TRACK, outline="")
            if frac > 0:
                round_rect(c, 0, bar_y, max(8, BAR_W * frac), bar_y + BAR_H, 6,
                           fill=NEED_COLORS[need], outline="")
            c.create_text(BAR_W - 4, bar_y + BAR_H / 2, anchor="e", text=str(int(value)),
                          fill="#1c1e26", font=("Segoe UI", 7, "bold"))

    def _item_icon(self, parent: tk.Misc, item_id: str) -> tk.Canvas:
        """A small canvas showing the item's pixel art."""
        cv = tk.Canvas(parent, width=28, height=28, bg=PANEL, highlightthickness=0, bd=0)
        item_art.draw_item(cv, item_id, 14, 14, 2)
        return cv

    def _build_shop(self, pet: dict[str, Any], level: int) -> None:
        for child in self.shop_tab.winfo_children():
            child.destroy()
        for item in shop.CATALOG:
            row = ttk.Frame(self.shop_tab, style="Card.TFrame")
            row.pack(fill="x", pady=3)
            self._item_icon(row, item["id"]).pack(side="left", padx=(0, 6))
            ok, _ = shop.can_buy(pet, item, level)
            owned_toy = item["type"] == shop.TOY and shop.owned(pet, item) >= 1
            btn = ttk.Button(row, text="Owned" if owned_toy else "Buy",
                             command=partial(self._buy, item))
            if not ok:
                btn.state(["disabled"])
            btn.pack(side="right")
            info = ttk.Frame(row, style="Card.TFrame")
            info.pack(side="left", fill="x", expand=True)
            ttk.Label(info, text=item["name"], style="Card.TLabel").pack(anchor="w")
            unlocked = shop.is_unlocked(item, level)
            sub = (f"{item['price']} coins · {_effects_text(item['effects'])}" if unlocked
                   else f"Unlocks at level {item['min_level']}")
            ttk.Label(info, text=sub, style="Muted.TLabel").pack(anchor="w")

    def _build_items(self, pet: dict[str, Any]) -> None:
        for child in self.items_tab.winfo_children():
            child.destroy()
        self._cooldowns = {}
        inv = pet.get("inventory", {})
        if not inv:
            ttk.Label(self.items_tab, text="No items yet — buy some food or a toy in the Shop.",
                      style="Muted.TLabel", wraplength=240, justify="left").pack(anchor="w")
            return
        for item_id, count in sorted(inv.items()):
            item = shop.item_by_id(item_id)
            if item is None:
                continue
            row = ttk.Frame(self.items_tab, style="Card.TFrame")
            row.pack(fill="x", pady=3)
            self._item_icon(row, item_id).pack(side="left", padx=(0, 6))
            if item["type"] == shop.FOOD:
                ttk.Button(row, text="Feed",
                           command=partial(self._feed, item)).pack(side="right")
                # food stacks, so show the count
                ttk.Label(row, text=f"{item['name']}  ×{count}",
                          style="Card.TLabel").pack(side="left")
            else:
                # toys are one-time, reusable on a cooldown: a Play button + a live
                # countdown label (updated by _update_cooldowns), no quantity.
                btn = ttk.Button(row, text="Play", command=partial(self._play, item))
                btn.pack(side="right")
                cd = ttk.Label(row, text="", style="Muted.TLabel")
                cd.pack(side="right", padx=(0, 6))
                self._cooldowns[item_id] = (item, btn, cd)
                ttk.Label(row, text=item["name"], style="Card.TLabel").pack(side="left")

    def _hat_icon(self, parent: tk.Misc, piece_id: str) -> tk.Canvas:
        """A small canvas showing the hat's pixel art."""
        cv = tk.Canvas(parent, width=28, height=28, bg=PANEL, highlightthickness=0, bd=0)
        sprite_pixel.draw_hat_icon(cv, piece_id, 14, 14, 2)
        return cv

    def _build_wardrobe(self, pet: dict[str, Any], level: int) -> None:
        for child in self.wardrobe_tab.winfo_children():
            child.destroy()
        worn = cosmetics.equipped_head(pet)
        for piece in cosmetics.CATALOG:
            row = ttk.Frame(self.wardrobe_tab, style="Card.TFrame")
            row.pack(fill="x", pady=3)
            self._hat_icon(row, piece["id"]).pack(side="left", padx=(0, 6))
            if cosmetics.owns(pet, piece):
                wearing = worn == piece["id"]
                btn = ttk.Button(row, text="Wearing ✓" if wearing else "Wear",
                                 command=partial(self._wear,
                                                 None if wearing else piece["id"]))
                sub = piece["desc"]
            elif cosmetics.is_milestone(piece):
                btn = ttk.Button(row, text="Locked")
                btn.state(["disabled"])
                sub = (f"{cosmetics.requirement_text(piece)} "
                       f"({min(pet.get('days_active', 0), piece['days_active'])}"
                       f"/{piece['days_active']})")
            else:
                ok, _ = cosmetics.can_buy(pet, piece, level)
                btn = ttk.Button(row, text="Buy", command=partial(self._buy_cosmetic, piece))
                if not ok:
                    btn.state(["disabled"])
                sub = (f"{piece['price']} coins" if level >= piece.get("min_level", 1)
                       else f"Unlocks at level {piece['min_level']}")
            btn.pack(side="right")
            info = ttk.Frame(row, style="Card.TFrame")
            info.pack(side="left", fill="x", expand=True)
            ttk.Label(info, text=piece["name"], style="Card.TLabel").pack(anchor="w")
            ttk.Label(info, text=sub, style="Muted.TLabel",
                      wraplength=210, justify="left").pack(anchor="w")

    def _update_cooldowns(self) -> None:
        """Live-update each owned toy's Play button + countdown label every tick, so
        the cooldown actually ticks down (the list itself isn't rebuilt each second)."""
        now = time.time()
        pet = self._cached_pet
        for item, btn, cd in self._cooldowns.values():
            ok, reason = shop.can_play(pet, item, now)
            try:
                btn.state(["!disabled"] if ok else ["disabled"])
                cd.config(text="" if ok else reason)
            except tk.TclError:
                pass

    # --- animation --------------------------------------------------------
    def _animate(self) -> None:
        if not self._alive:
            return
        try:
            now = time.time()
            c = self.pet_canvas
            c.delete("all")
            celebrating = now < self._celebrate_until
            face = "happy" if celebrating else "idle"
            accent = sprite_pixel.BODY
            cx, cy = PET_CANVAS_W // 2, PET_CANVAS_H // 2
            pet = self._cached_pet
            view = pet_view(pet, now=now)
            sprite_pixel.draw_pet(c, cx, cy, view, state=face, accent=accent, px=PET_PX)
            self._animate_hearts(now)
        except tk.TclError:
            return
        self.root.after(ANIM_MS, self._animate)

    def _animate_hearts(self, now: float) -> None:
        alive: list[dict[str, float]] = []
        for h in self._hearts:
            prog = (now - h["t0"]) / HEART_LIFETIME_S
            if prog < 0.0:
                alive.append(h)
                continue
            if prog >= 1.0:
                continue
            x = h["x"] + h["drift"] * prog
            y = h["y0"] - prog * 40
            sprite_pixel.draw_heart(self.pet_canvas, x, y, 3, NEED_COLORS["happiness"])
            alive.append(h)
        self._hearts = alive

    def _tick(self) -> None:
        if not self._alive:
            return
        try:
            self._refresh()
        except tk.TclError:
            return
        self.root.after(TICK_MS, self._tick)

    # --- lifecycle --------------------------------------------------------
    def focus(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except tk.TclError:
            pass

    def close(self) -> None:
        self._alive = False
        try:
            self.root.destroy()
        except tk.TclError:
            pass
        if self._on_close is not None:
            self._on_close()


def main() -> None:
    """Standalone entry point (opened from Settings): its own Tk root, reading and
    writing pet.json directly via pet_store with a read-modify-write per action."""
    root = tk.Tk()
    root.withdraw()  # the PetWindow Toplevel is the visible window

    def _load() -> dict[str, Any]:
        return pet_store.load(pet_store.PET_PATH, time.time())

    def _save(pet: dict[str, Any]) -> dict[str, Any]:
        return pet_store.save(pet_store.PET_PATH, pet, time.time())

    PetWindow(root, load_pet=_load, save_pet=_save, on_close=root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
