"""Statusline domain: turn Claude Code's statusline JSON into the widget's
account-global usage snapshot, and format a compact terminal footer line.

Claude Code can run a *statusline command* on each update, handing it a JSON blob
on stdin that (for subscribers) carries the 5-hour and 7-day usage limits and the
live effort. The widget has no other official source for those limits, so the
mascot installs a statusline command (``hooks/status_emit.py``) that writes the
numbers to :data:`USAGE_PATH` for the card to read — and prints a useful footer
so the terminal gains the same at-a-glance view.

The functions here are pure (no I/O, no clock — ``now`` is passed in) so they are
unit-testable; the thin ``hooks/status_emit.py`` shell does the stdin read and the
atomic write. Only the ``USAGE_PATH`` constant touches the filesystem layout.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import effort as _effort

# Where the emitter writes, and the widget reads, the account-global usage
# snapshot. One file, last-writer-wins by design (the limits are account-wide, so
# every session sees the same numbers — no per-session races like the state dir).
USAGE_PATH = Path.home() / ".claude" / "mascot" / "usage.json"

_WINDOWS = ("five_hour", "seven_day")


def _window(raw: Any) -> dict[str, float] | None:
    """A ``{used_percentage, resets_at}`` window from a raw limit object, or
    ``None`` when it's missing/malformed (so the card simply doesn't show it)."""
    if not isinstance(raw, dict):
        return None
    pct, reset = raw.get("used_percentage"), raw.get("resets_at")
    if not isinstance(pct, (int, float)) or not isinstance(reset, (int, float)):
        return None
    return {"used_percentage": float(pct), "resets_at": float(reset)}


def merge_snapshots(existing: Any, incoming: Any) -> dict[str, Any]:
    """Merge a writer's snapshot into the one on disk — the two-writer discipline.

    ``usage.json`` has two independent writers (the statusline emitter and the
    opt-in usage-API poller), so a write must be a *merge*, not an overwrite:

    * **Freshest wins** — the incoming snapshot only lands if its ``ts`` is newer
      than the existing one's; an out-of-order (or ts-less) write changes nothing.
    * **No opinion, no erase** — fields the incoming snapshot doesn't carry are
      kept from the existing one (the poller has no ``effort``; the statusline's
      recorded level must survive its writes).

    Pure and tolerant: a missing/malformed side reads as an empty snapshot; the
    inputs are never mutated and the result is always a fresh dict.
    """
    old = existing if isinstance(existing, dict) else {}
    new = incoming if isinstance(incoming, dict) else {}

    def _ts(snap: dict[str, Any]) -> float:
        ts = snap.get("ts")
        return float(ts) if isinstance(ts, (int, float)) else 0.0

    if not new or _ts(new) <= _ts(old):
        return dict(old)
    return {**old, **new}


def snapshot_from_status(payload: dict[str, Any], now: float) -> dict[str, Any]:
    """The usage snapshot to persist, distilled from a statusline JSON payload.

    Carries whichever of the two limit windows are present (absent ones are simply
    omitted — API-key users have none), the reported effort level, and a written-at
    heartbeat. Tolerant of a missing/oddly-shaped ``rate_limits`` block.
    """
    snap: dict[str, Any] = {"ts": now}
    limits = payload.get("rate_limits")
    if isinstance(limits, dict):
        for key in _WINDOWS:
            window = _window(limits.get(key))
            if window is not None:
                snap[key] = window
    effort_block = payload.get("effort")
    if isinstance(effort_block, dict):
        level = effort_block.get("level")
        if isinstance(level, str):
            snap["effort"] = level
    return snap


# --- footer line -----------------------------------------------------------
_RESET = "\x1b[0m"


def _ansi(rgb: tuple[int, int, int], text: str) -> str:
    return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m{text}{_RESET}"


def _pct(window: Any) -> str | None:
    """A ``NN%`` label for a raw limit window, or ``None`` if unusable."""
    w = _window(window)
    return f"{round(w['used_percentage'])}%" if w is not None else None


def footer_line(payload: dict[str, Any], *, color: bool = True) -> str:
    """A compact one-line status for the terminal footer:
    ``<model> · <effort> · 5h NN% · wk NN% · <dir>``. Parts that are absent are
    dropped, so the separators never dangle; the effort token is tinted in its
    own palette color (matching the card) unless ``color`` is off.
    """
    parts: list[str] = []

    model = payload.get("model")
    if isinstance(model, dict) and isinstance(model.get("display_name"), str):
        parts.append(model["display_name"])

    level = _effort.normalize((payload.get("effort") or {}).get("level")
                              if isinstance(payload.get("effort"), dict) else "")
    if level:
        parts.append(_ansi(_effort.TINTS[level], level) if color else level)

    limits = payload.get("rate_limits")
    if isinstance(limits, dict):
        five = _pct(limits.get("five_hour"))
        if five is not None:
            parts.append(f"5h {five}")
        week = _pct(limits.get("seven_day"))
        if week is not None:
            parts.append(f"wk {week}")

    workspace = payload.get("workspace")
    if isinstance(workspace, dict) and isinstance(workspace.get("current_dir"), str):
        parts.append(Path(workspace["current_dir"]).name)

    return "   ·   ".join(parts)
