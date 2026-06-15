"""Shared constants and paths for the mascot widget."""
from __future__ import annotations

from pathlib import Path

from .settings import load_settings

_S = load_settings()

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

VALID_STATES = ("idle", "thinking", "working", "waiting", "sleeping")

# Mascot art style ("pixel" / "smooth") and transparent floating card. Both are
# user-configurable via the settings panel (mascot/control_panel.py); change
# them there, or edit ~/.claude/mascot/settings.json directly.
ART_STYLE = _S["art_style"]
TRANSPARENT_BG = _S["transparent_bg"]

# Per-state accent colors (R, G, B).
STATE_COLORS = {
    "idle":     (120, 144, 168),
    "thinking": (236, 201, 75),
    "working":  (72, 187, 120),
    "waiting":  (237, 137, 54),
    "sleeping": (90, 103, 158),
    "dizzy":    (167, 139, 250),
}

SUBAGENT_COLOR = (159, 122, 234)
