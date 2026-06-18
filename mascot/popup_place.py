"""Pure geometry for placing a popup (speech bubble / stats tooltip) next to a
mascot card.

Kept free of Tk so the multi-monitor clamping can be unit-tested. The key point
is that clamping happens against the bounds of the monitor the card is actually
on — passed in by the caller — not Tk's ``winfo_screenwidth()``, which on Windows
only ever reports the *primary* monitor and so yanks a popup back onto the main
screen when the card is dragged to another display.

`bounds` is the target monitor's work area as ``(x, y, width, height)`` in the
same virtual-desktop coordinates as the card position.
"""
from __future__ import annotations


def _clamp(value: int, lo: int, hi: int) -> int:
    """Clamp into [lo, hi], tolerating hi < lo (popup bigger than the monitor)."""
    return max(lo, min(value, hi)) if hi >= lo else lo


def beside(
    card_x: int, card_y: int, card_w: int, card_h: int,
    popup_w: int, popup_h: int, bounds: tuple[int, int, int, int], gap: int,
) -> tuple[int, int]:
    """Top-left for a popup placed beside the card, preferring its left side and
    falling to its right when there's no room, vertically centered — clamped to
    `bounds` so it stays on the card's own monitor."""
    bx, by, bw, bh = bounds
    x = card_x - popup_w - gap                 # prefer the left of the card
    if x < bx:
        x = card_x + card_w + gap              # no room left -> go right
    x = _clamp(x, bx, bx + bw - popup_w)
    y = card_y + (card_h - popup_h) // 2
    y = _clamp(y, by, by + bh - popup_h)
    return x, y


def above(
    card_x: int, card_y: int, card_w: int,
    popup_w: int, popup_h: int, bounds: tuple[int, int, int, int], gap: int,
) -> tuple[int, int]:
    """Top-left for a popup horizontally centered over the card and sitting just
    above it (dropping below it if it would clear the monitor's top) — clamped to
    `bounds` so it stays on the card's own monitor."""
    bx, by, bw, _bh = bounds
    x = card_x + card_w // 2 - popup_w // 2
    x = _clamp(x, bx, bx + bw - popup_w)
    y = card_y - popup_h - gap
    if y < by:
        y = card_y                             # no room above -> hug the card top
    return x, y
