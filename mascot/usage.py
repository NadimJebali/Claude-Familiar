"""Pure core for the card's 5-hour + weekly usage bars.

The account-global usage snapshot is written by ``hooks/status_emit.py`` (from
Claude Code's statusline JSON) to :data:`~mascot.statusline.USAGE_PATH`. This
module turns that snapshot into the two glanceable bars the card draws, applying
*reset decay* purely from the recorded ``resets_at`` and the clock — no staleness
timers — and picks each bar's color by a traffic-light threshold.

Kept Tk-free and clock-free (``now`` passed in) so it is unit-testable, mirroring
``effort`` / ``pet_logic``. The card supplies the live clock and draws the result.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .statusline import USAGE_PATH

RGB = tuple[int, int, int]

# Traffic-light thresholds (percent). Calm below WARN_AT; Claude's warning amber
# from WARN_AT; Claude's error red from ALARM_AT (its own 0.9 utilization alarm).
WARN_AT = 70.0
ALARM_AT = 90.0
CALM = (99, 132, 166)     # calm blue-grey — plenty of runway
WARN = (255, 193, 7)      # CLI warning amber
ALARM = (255, 107, 128)   # CLI error red (the softer error variant)

# The two windows and their short card labels (Claude Code's own abbreviations).
_WINDOWS = (("five_hour", "5h"), ("seven_day", "7d"))


@dataclass(frozen=True)
class UsageBar:
    """One usage limit as the card shows it: a short label and a 0..100 percent."""
    label: str
    pct: float


def _decayed_pct(window: Any, now: float) -> float | None:
    """The percentage to show for a raw limit window, or ``None`` when unusable.

    Reset decay: while ``now`` is before ``resets_at`` the recorded percentage
    stands; once the window's reset time has passed it has genuinely reset, so the
    bar reads 0 (no stale-file false alarms, no arbitrary timers)."""
    if not isinstance(window, dict):
        return None
    pct, reset = window.get("used_percentage"), window.get("resets_at")
    if not isinstance(pct, (int, float)) or not isinstance(reset, (int, float)):
        return None
    return float(pct) if now < reset else 0.0


def exhausted_until(snapshot: Any, now: float) -> float | None:
    """The epoch when usage returns, when the account is out — any window at
    ≥100% whose ``resets_at`` is still ahead. Both exhausted → the later reset
    (the account stays capped until the last window frees); a passed reset →
    ``None``, so revival is automatic even off a stale snapshot.

    This is the widget's reliable death signal (#91): the hook paths proved
    unusable in practice (real ``StopFailure`` payloads carry no ``error_type``,
    VS Code emits no limit ``Notification``), but the statusline/poller feed
    always knows — and a subscription limit is account-wide anyway."""
    if not isinstance(snapshot, dict):
        return None
    until: float | None = None
    for key, _label in _WINDOWS:
        window = snapshot.get(key)
        if not isinstance(window, dict):
            continue
        pct, reset = window.get("used_percentage"), window.get("resets_at")
        if (isinstance(pct, (int, float)) and isinstance(reset, (int, float))
                and float(pct) >= 100.0 and float(reset) > now):
            until = float(reset) if until is None else max(until, float(reset))
    return until


def usage_view(snapshot: dict[str, Any] | None, now: float) -> list[UsageBar]:
    """The bars to draw, in order (5h then 7d). Windows absent from the snapshot
    are omitted (API-key users have none); a window past its reset reads 0.
    A missing/malformed snapshot yields no bars."""
    if not isinstance(snapshot, dict):
        return []
    bars: list[UsageBar] = []
    for key, label in _WINDOWS:
        pct = _decayed_pct(snapshot.get(key), now)
        if pct is not None:
            bars.append(UsageBar(label, pct))
    return bars


def bar_color(pct: float) -> RGB:
    """Traffic-light color for a fill percentage: calm / warning / alarm."""
    if pct >= ALARM_AT:
        return ALARM
    if pct >= WARN_AT:
        return WARN
    return CALM


# A snapshot older than this is *labeled* stale on the card (#69) — the bars still
# show (reset decay keeps them honest), but the viewer learns the numbers are aged
# (e.g. VS Code-only workflows, where no statusline refreshes them).
STALE_AFTER_S = 15 * 60.0


def is_stale(snapshot: Any, now: float) -> bool:
    """Whether the snapshot's numbers should carry the "stale" label.

    ``False`` for no snapshot at all (nothing is drawn, so there is nothing to
    label); ``True`` for one with a missing/garbage ``ts`` (unknown age — can't
    vouch) or one written longer than :data:`STALE_AFTER_S` ago."""
    if not isinstance(snapshot, dict):
        return False
    ts = snapshot.get("ts")
    if not isinstance(ts, (int, float)):
        return True
    return (now - float(ts)) > STALE_AFTER_S


# --- snapshot loader (thin mtime-cached I/O shell) -------------------------
_cache: dict[Path, tuple[float, dict[str, Any] | None]] = {}


def load_usage(path: Path = USAGE_PATH) -> dict[str, Any] | None:
    """The latest usage snapshot, memoized by file mtime so the widget can call it
    every poll cheaply. Missing/unreadable/corrupt file → ``None``."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    if not isinstance(data, dict):
        data = None
    _cache[path] = (mtime, data)
    return data
