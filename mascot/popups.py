"""The speech bubble shown above a mascot card while Claude needs the user.

A small frameless Toplevel; its on-screen placement is delegated to the pure
``popup_place`` helpers so it stays correct across multiple monitors and can be
unit-tested without a display.
"""
from __future__ import annotations

import tkinter as tk

from . import popup_place
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
