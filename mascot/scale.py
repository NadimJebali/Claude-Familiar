"""Widget-size scaling primitives, shared by the card and its popups.

Every UI measurement is authored at the "small" size, then multiplied by
``config.UI_SCALE`` so "medium"/"large" scale the whole card uniformly.
"""
from __future__ import annotations

from . import config

UI_SCALE = config.UI_SCALE


def s(value: float) -> int:
    """Scale a base (small-size) measurement by the configured widget size."""
    return max(1, round(value * UI_SCALE))


def font(size: int, *opts: str) -> tuple:
    """A Segoe UI font tuple whose point size tracks the widget size."""
    return ("Segoe UI", s(size), *opts)
