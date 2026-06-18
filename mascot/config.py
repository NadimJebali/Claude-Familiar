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
STALE_TIMEOUT_S = 300          # backstop: prune an owner-less session this stale
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

# Which monitor the cards spawn on: an int index into the enumerated monitors, or
# -1 ("auto") for the primary. Resolved in tkinter_app via osplatform helpers; an
# out-of-range/garbage value falls back to primary, so no clamping is needed here.
HOME_MONITOR = _S["home_monitor"]

# Tamagotchi pet layer. When False the card is a *simple hook visualiser*: the same
# pixel state faces + subagent badges, but the manager never wires or pushes the pet
# (no paw button, tooltip, mood faces, food/zzz emotes, coins/XP, or tray "Pet…").
# Read once at startup, so the mode is restart-gated like the other settings here.
TAMAGOTCHI_ENABLED = bool(_S["tamagotchi_enabled"])

# Per-state accent colors (R, G, B).
STATE_COLORS = {
    "idle":     (120, 144, 168),
    "thinking": (236, 201, 75),
    "working":  (72, 187, 120),
    "waiting":  (237, 137, 54),
    "waiting_angry": (237, 137, 54),   # same accent as waiting; only the face changes
    "sleeping": (90, 103, 158),
    "dizzy":    (167, 139, 250),
    "happy":    (244, 114, 182),   # celebrate / petted — ties to the pink hearts
    "dead":     (122, 128, 144),
    # Idle-mood faces (pet needs): a cared-for pet sparkles pink, low needs stay
    # the calm idle accent so the mood reads from the face, not an alarming color.
    "idle_happy":  (244, 114, 182),
    "idle_hungry": (120, 144, 168),
    "idle_sad":    (120, 144, 168),
    "idle_tired":  (120, 144, 168),
}

SUBAGENT_COLOR = (159, 122, 234)

# Need-bar colors (hunger / happiness / energy), shared by the Pet window and the
# hover tooltip so the two read consistently.
NEED_COLORS = {"hunger": "#ed8936", "happiness": "#f472b6", "energy": "#48bb78"}
