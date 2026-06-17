"""The speech bubble shown above a mascot card while Claude needs the user.

A small frameless Toplevel; its on-screen placement is delegated to the pure
``popup_place`` helpers so it stays correct across multiple monitors and can be
unit-tested without a display.
"""
from __future__ import annotations

import tkinter as tk

from . import config, pet_logic, popup_place
from .scale import font as _font, s as _s

# Comic speech bubble (shown above the card while Claude needs the user).
BUBBLE_W = _s(196)
BUBBLE_PAD = _s(10)
BUBBLE_GAP = _s(6)
BUBBLE_FONT = _font(9)
BUBBLE_FILL = "#fdf6e3"
BUBBLE_TEXT = "#1c1e26"
BUBBLE_MAX_CHARS = 160


class BubbleWindow:
    """A speech bubble shown above a mascot while Claude needs the user.

    A small opaque, frameless Toplevel (Windows `-transparentcolor` layered
    windows render unreliably with `overrideredirect`, so we avoid them).
    """

    def __init__(self, manager_root: tk.Tk, message: str) -> None:
        self.message = ""
        self._width = BUBBLE_W
        self._height = 0

        self.top = tk.Toplevel(manager_root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=BUBBLE_TEXT)  # 2px dark border via padding below

        self.label = tk.Label(
            self.top,
            bg=BUBBLE_FILL,
            fg=BUBBLE_TEXT,
            font=BUBBLE_FONT,
            justify="center",
            wraplength=BUBBLE_W - 2 * BUBBLE_PAD,
            padx=BUBBLE_PAD,
            pady=BUBBLE_PAD,
        )
        self.label.pack(padx=2, pady=2)
        self.set_message(message)

    def set_message(self, message: str) -> None:
        message = (message or "Claude needs your attention")[:BUBBLE_MAX_CHARS]
        if message == self.message:
            return
        self.message = message
        self.label.config(text=message)
        self.top.update_idletasks()
        self._width = self.top.winfo_reqwidth()
        self._height = self.top.winfo_reqheight()

    def place_above(self, card_x: int, card_y: int, card_w: int,
                    bounds: tuple[int, int, int, int]) -> None:
        x, y = popup_place.above(card_x, card_y, card_w, self._width, self._height,
                                 bounds, BUBBLE_GAP)
        self.top.geometry(f"+{x}+{y}")

    def destroy(self) -> None:
        try:
            self.top.destroy()
        except tk.TclError:
            pass


# --- pet status tooltip (revived hover tooltip, driven by pet.json) ---------
TIP_W = _s(152)
TIP_PAD = _s(8)
TIP_BAR_X = _s(42)               # left of the bars (room for the need label)
TIP_BAR_H = _s(8)
TIP_HEIGHT = _s(90)
TIP_FILL = "#1d1f29"
TIP_BORDER = "#2a2d3b"
TIP_TRACK = "#2a2d3b"
TIP_FG = "#e8e8ef"
TIP_MUTED = "#9095a8"
TIP_NAME_FONT = _font(8, "bold")
TIP_SMALL_FONT = _font(7)
TIP_NEED_LABEL = {"hunger": "Food", "happiness": "Happy", "energy": "Energy"}


class StatsTooltip:
    """A compact hover tooltip showing the pet's status: name, level, coins, and
    three need bars. Frameless opaque Toplevel (like BubbleWindow); placed beside
    the card via the pure popup_place helper so it stays on the card's monitor."""

    def __init__(self, manager_root: tk.Tk, pet: dict | None) -> None:
        self.top = tk.Toplevel(manager_root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=TIP_BORDER)          # 1px border via the canvas padding
        self.canvas = tk.Canvas(self.top, width=TIP_W, height=TIP_HEIGHT,
                                bg=TIP_FILL, highlightthickness=0, bd=0)
        self.canvas.pack(padx=1, pady=1)
        self._pet: dict = {}
        self.set_pet(pet)

    def set_pet(self, pet: dict | None) -> None:
        self._pet = pet or {}
        self._draw()

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        pet = self._pet
        name = (pet.get("name") or "Your Pet")[:16]
        level = pet_logic.level_for_xp(pet.get("xp", 0))
        c.create_text(TIP_PAD, TIP_PAD, anchor="nw", text=name,
                      fill=TIP_FG, font=TIP_NAME_FONT)
        c.create_text(TIP_PAD, TIP_PAD + _s(16), anchor="nw",
                      text=f"Lv {level}  ·  {pet.get('coins', 0)} coins",
                      fill=TIP_MUTED, font=TIP_SMALL_FONT)
        y = TIP_PAD + _s(34)
        bar_w = TIP_W - TIP_BAR_X - TIP_PAD
        for need in ("hunger", "happiness", "energy"):
            value = max(0, min(pet_logic.MAX_STAT, pet.get(need, 0)))
            frac = value / pet_logic.MAX_STAT
            c.create_text(TIP_PAD, y + TIP_BAR_H / 2, anchor="w",
                          text=TIP_NEED_LABEL[need], fill=TIP_MUTED, font=TIP_SMALL_FONT)
            c.create_rectangle(TIP_BAR_X, y, TIP_BAR_X + bar_w, y + TIP_BAR_H,
                               fill=TIP_TRACK, outline="")
            if frac > 0:
                c.create_rectangle(TIP_BAR_X, y, TIP_BAR_X + bar_w * frac, y + TIP_BAR_H,
                                   fill=config.NEED_COLORS[need], outline="")
            y += _s(16)

    def place_beside(self, card_x: int, card_y: int, card_w: int, card_h: int,
                     bounds: tuple[int, int, int, int]) -> None:
        x, y = popup_place.beside(card_x, card_y, card_w, card_h,
                                  TIP_W, TIP_HEIGHT, bounds, gap=_s(6))
        self.top.geometry(f"+{x}+{y}")

    def destroy(self) -> None:
        try:
            self.top.destroy()
        except tk.TclError:
            pass
