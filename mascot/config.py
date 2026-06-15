"""Shared constants and paths for the mascot widget."""
from __future__ import annotations

from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "mascot" / "state"

# Timing
POLL_INTERVAL_MS = 1000        # how often the manager re-reads the state dir
STALE_TIMEOUT_S = 300          # drop a mascot if its heartbeat is older than this
SLEEP_AFTER_IDLE_S = 30        # idle this long -> show the sleeping sprite
ANIM_INTERVAL_MS = 40          # ~25 fps bob animation

# Sizing (logical px)
MASCOT_SIZE = 96
SUBAGENT_SIZE = 28
SUBAGENT_GAP = 6
LABEL_HEIGHT = 16
WINDOW_MARGIN = 12             # gap from screen edge
WINDOW_SPACING = 8             # gap between stacked per-session mascots

VALID_STATES = ("idle", "thinking", "working", "waiting", "sleeping")

# Mascot art style: "pixel" (Claude-style blocky creature) or "smooth" (the
# original vector blob, kept on the side). Swap to change the character.
ART_STYLE = "pixel"

# Float the rounded card with a transparent window background (the square corners
# show the desktop). Set False if your Windows setup renders transparent
# overrideredirect windows oddly (then the card sits on a solid dark backdrop).
TRANSPARENT_BG = True

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
