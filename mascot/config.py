"""Shared constants and paths for the mascot widget."""
from __future__ import annotations

from pathlib import Path

from .settings import load_settings

_S = load_settings()


def _clamp(value: object, lo: float, hi: float, default: float) -> float:
    """Coerce a (possibly hand-edited) setting to a number within [lo, hi]."""
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, num))

STATE_DIR = Path.home() / ".claude" / "mascot" / "state"

# Timing
POLL_INTERVAL_MS = 1000        # how often the manager re-reads the state dir
STALE_TIMEOUT_S = 300          # drop a mascot if its heartbeat is older than this
SLEEP_AFTER_IDLE_S = _S["sleep_after_idle_s"]  # idle this long -> sleeping sprite
ANIM_INTERVAL_MS = 40          # ~25 fps bob animation

# Sizing (logical px)
MASCOT_SIZE = 96
SUBAGENT_SIZE = 28
SUBAGENT_GAP = 6
LABEL_HEIGHT = 16
WINDOW_MARGIN = 12             # gap from screen edge
WINDOW_SPACING = 8             # gap between stacked per-session mascots

# Mascot art style ("pixel" / "smooth") and transparent floating card. Both are
# user-configurable via the settings panel (mascot/control_panel.py); change
# them there, or edit ~/.claude/mascot/settings.json directly.
ART_STYLE = _S["art_style"]
TRANSPARENT_BG = _S["transparent_bg"]

# Widget size: scales the whole card (geometry, creature, fonts). "small" is the
# original size; "medium"/"large" are uniform multiples of it.
WIDGET_SIZE = _S["widget_size"]
UI_SCALE = {"small": 1.0, "medium": 1.3, "large": 1.6}.get(WIDGET_SIZE, 1.0)

# Attention shake (see tkinter_app): how long an unanswered permission/attention
# prompt waits before the card starts shaking, and how violent (wide) the sway
# becomes at full aggression. Both are user-configurable in the settings panel.
SHAKE_AFTER_S = _clamp(_S["shake_after_s"], 5, 600, 30)
SHAKE_MAX_AMP_PX = int(_clamp(_S["shake_max_amp_px"], 2, 60, 16))

# Per-state accent colors (R, G, B).
STATE_COLORS = {
    "idle":     (120, 144, 168),
    "thinking": (236, 201, 75),
    "working":  (72, 187, 120),
    "waiting":  (237, 137, 54),
    "sleeping": (90, 103, 158),
    "dizzy":    (167, 139, 250),
    "dead":     (122, 128, 144),
}

SUBAGENT_COLOR = (159, 122, 234)
