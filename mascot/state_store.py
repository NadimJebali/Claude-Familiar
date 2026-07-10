"""Read session state files written by hooks/emit.py.

Kept Qt-free and side-effect-light so the staleness logic is unit-testable.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config
from .proc import pid_alive

# emit.py's atomic writes go through "<session>.<pid>.tmp" files; a crash (or an
# exhausted replace-retry) can strand one. Sweep strays older than this while
# polling, so the state dir stays clean without ever racing a live write.
TMP_SWEEP_AGE_S = 300.0


def is_stale(state: dict[str, Any], now: float, timeout: float = config.STALE_TIMEOUT_S) -> bool:
    """A mascot's heartbeat is older than `timeout` seconds.

    The heartbeat only ticks on hook events, so an idle/sleeping-but-live session
    goes "stale" too — which is why staleness is now only a *backstop*, used to
    prune an abandoned file when the owning process can't be tracked. See
    `is_session_live`.
    """
    return (now - float(state.get("ts", 0.0))) > timeout


def _has_trackable_owner(state: dict[str, Any]) -> bool:
    """True when we recorded a usable owner PID we can poll for liveness."""
    pid = state.get("owner_pid")
    if not pid:
        return False
    try:
        int(pid)
    except (TypeError, ValueError):
        return False
    return True


def is_owner_dead(state: dict[str, Any]) -> bool:
    """True when the session's owning claude.exe process is known to be gone.

    Returns False when the owner is unknown/unconfirmed, so we never prune a
    session we can't positively confirm has ended.
    """
    return not pid_alive(state.get("owner_pid"))


def is_session_live(
    state: dict[str, Any], now: float, timeout: float = config.STALE_TIMEOUT_S
) -> bool:
    """Whether a session's card should stay on screen.

    A session stays as long as its owning `claude` process is alive — even when
    idle or sleeping (sleep is the pet's energy-recovery rhythm now, not death),
    so a quiet-but-live session is never timed out. When there is no trackable
    owner PID (unknown platform / lookup failed), the heartbeat-staleness timeout
    is the backstop that still prunes an abandoned file.

    A *positively dead* stamp is not the whole verdict (#83): the host can
    restart mid-session (a VS Code reload relaunches the CLI), leaving a dead
    PID stamped on a file that hooks are still writing. Evidence of life wins —
    the session survives while its heartbeat is fresher than the (tight)
    ``DEAD_OWNER_GRACE_S``, which still prunes a truly-ended session far faster
    than the ownerless backstop.
    """
    if _has_trackable_owner(state):
        if pid_alive(state.get("owner_pid")):
            return True
        return not is_stale(state, now, config.DEAD_OWNER_GRACE_S)
    return not is_stale(state, now, timeout)


def load_states(
    state_dir: Path, now: float, timeout: float = config.STALE_TIMEOUT_S
) -> dict[str, dict[str, Any]]:
    """Return {session_id: state} for every session whose card should be shown."""
    live: dict[str, dict[str, Any]] = {}
    if not state_dir.exists():
        return live
    _sweep_stale_tmp(state_dir, now)
    for path in state_dir.glob("*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sid = state.get("session_id") or path.stem
        if is_session_live(state, now, timeout):
            live[sid] = state
    return live


def _sweep_stale_tmp(state_dir: Path, now: float) -> None:
    """Best-effort removal of stranded emit temp files (never a fresh in-flight one)."""
    for tmp in state_dir.glob("*.tmp"):
        try:
            if now - tmp.stat().st_mtime > TMP_SWEEP_AGE_S:
                tmp.unlink(missing_ok=True)
        except OSError:
            continue
