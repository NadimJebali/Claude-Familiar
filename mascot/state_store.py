"""Read session state files written by hooks/emit.py.

Kept Qt-free and side-effect-light so the staleness logic is unit-testable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config
from .proc import pid_alive


def is_stale(state: dict[str, Any], now: float, timeout: float = config.STALE_TIMEOUT_S) -> bool:
    """A mascot is stale when its heartbeat is older than `timeout` seconds."""
    return (now - float(state.get("ts", 0.0))) > timeout


def is_owner_dead(state: dict[str, Any]) -> bool:
    """True when the session's owning claude.exe process is known to be gone.

    Returns False when the owner is unknown/unconfirmed, so the staleness timeout
    stays the backstop and we never prune a session we can't positively confirm
    has ended.
    """
    return not pid_alive(state.get("owner_pid"))


def load_states(
    state_dir: Path, now: float, timeout: float = config.STALE_TIMEOUT_S
) -> dict[str, dict[str, Any]]:
    """Return {session_id: state} for every live (non-stale) state file."""
    live: dict[str, dict[str, Any]] = {}
    if not state_dir.exists():
        return live
    for path in state_dir.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sid = state.get("session_id") or path.stem
        if is_stale(state, now, timeout) or is_owner_dead(state):
            continue
        live[sid] = state
    return live
