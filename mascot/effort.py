"""Pure core for the effort-reactive card background.

Claude Code runs each turn at a reasoning *effort* level; this module turns that
level into the card's panel color, matching the palette Claude Code uses for the
same levels (the values were read from the Claude Code binary's own theme, so the
card and the CLI speak one color language).

Kept Tk-free and clock-free (``now``/``t`` are passed in) so every branch is
unit-testable, mirroring ``state_logic`` / ``effective_state`` / ``pet_logic``.
The card supplies the live values; the thin ``read_settings_effort`` shell is the
only thing here that touches the filesystem.
"""
from __future__ import annotations

import json
from pathlib import Path

RGB = tuple[int, int, int]

LEVELS = ("low", "medium", "high", "xhigh", "max")

# ``ultracode`` runs at xhigh effort (+ dynamic workflows) — Claude Code aliases
# it to xhigh, so the card wears the same purple identity.
_ALIASES = {"ultracode": "xhigh"}

# The rainbow Claude Code animates for `max` effort (its "rainbow-animated" label),
# read from the Claude Code binary's theme (dark). The animation itself lands in a
# follow-up slice; `max`'s static placeholder here is the mean of these colors.
RAINBOW: tuple[RGB, ...] = (
    (235, 95, 87),    # red
    (245, 139, 87),   # orange
    (250, 195, 95),   # yellow
    (145, 200, 130),  # green
    (130, 170, 220),  # blue
    (155, 130, 200),  # indigo
    (200, 130, 180),  # violet
)

# The purple "shimmer" gradient Claude Code uses for `xhigh` (its
# "autoAccept-shimmer" label): a deep→bright purple sweep. The wave animation
# lands in a follow-up slice; the static tint here uses the bright end.
WAVE_LO: RGB = (62, 22, 118)
WAVE_HI: RGB = (140, 80, 240)


def _mean(colors: tuple[RGB, ...]) -> RGB:
    n = len(colors)
    return (
        round(sum(c[0] for c in colors) / n),
        round(sum(c[1] for c in colors) / n),
        round(sum(c[2] for c in colors) / n),
    )


# The representative color per level, matching Claude Code's own effort palette
# (warning / success / permission for low/medium/high). `xhigh`/`max` carry a
# static placeholder until the animated slice replaces them with live color math.
TINTS: dict[str, RGB] = {
    "low": (255, 193, 7),      # warning amber
    "medium": (78, 186, 101),  # success green
    "high": (177, 185, 249),   # permission periwinkle
    "xhigh": WAVE_HI,          # bright shimmer purple
    "max": _mean(RAINBOW),     # neutral placeholder = mean of the rainbow
}

# How strongly the panel is tinted toward the level's color. Subtle for the three
# quiet levels; a touch stronger for the two "special" levels so they still read
# once their animation arrives. Magnitudes are a tuning pass (tests assert the
# subtle-vs-base direction, not exact values).
_BLEND_STRENGTH: dict[str, float] = {
    "low": 0.18, "medium": 0.18, "high": 0.18, "xhigh": 0.32, "max": 0.32,
}


def normalize(raw: str | None) -> str:
    """A recognized effort level, or ``""`` for anything unknown.

    Case/whitespace tolerant; maps the ``ultracode`` alias to ``xhigh``; treats
    ``auto`` (and any unrecognized value, ``None``, or empty) as unknown so the
    card falls back to its default look rather than inventing a level.
    """
    if not raw:
        return ""
    key = raw.strip().lower()
    key = _ALIASES.get(key, key)
    return key if key in LEVELS else ""


def resolve(state_effort: str | None, fallback: str | None) -> str:
    """The effort to display: the per-session (per-turn) level from the state
    file wins; the global settings fallback fills in when it's blank/unknown.
    Both are normalized, so the alias and unknown-handling apply uniformly.
    """
    return normalize(state_effort) or normalize(fallback)


# --- color math ------------------------------------------------------------
def blend(base: RGB, target: RGB, strength: float) -> RGB:
    """Mix ``base`` toward ``target`` by ``strength`` (0 → base, 1 → target).

    Returns clamped integer channels, so the result is always a valid color even
    for out-of-range targets or strengths.
    """
    def mix(b: int, t: int) -> int:
        return max(0, min(255, round(b + (t - b) * strength)))

    return (mix(base[0], target[0]), mix(base[1], target[1]), mix(base[2], target[2]))


def panel_fill(effort: str | None, base: RGB, t: float = 0.0) -> RGB | None:
    """The card panel color for ``effort`` over the dark ``base``, or ``None`` for
    an unknown level (the card then keeps its exact default panel).

    ``t`` is the animation clock, unused by the static tints in this slice; the
    follow-up slice makes ``xhigh``/``max`` vary their color with it.
    """
    level = normalize(effort)
    if not level:
        return None
    return blend(base, TINTS[level], _BLEND_STRENGTH[level])


# --- settings fallback (thin I/O shell) ------------------------------------
# Claude Code stores the account-wide default effort as ``effortLevel`` in its
# global settings; the widget uses it only when a session's state file carries no
# per-turn effort of its own.
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

_cache: dict[Path, tuple[float, str]] = {}


def read_settings_effort(path: Path = SETTINGS_PATH) -> str:
    """The normalized ``effortLevel`` from a settings file, or ``""`` when the
    file is missing, unreadable, corrupt, or has no such key."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return normalize(data.get("effortLevel") if isinstance(data, dict) else "")


def settings_effort(path: Path = SETTINGS_PATH) -> str:
    """``read_settings_effort`` memoized by file mtime, so the widget can call it
    every poll without re-parsing the file until it actually changes."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return ""
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    value = read_settings_effort(path)
    _cache[path] = (mtime, value)
    return value
