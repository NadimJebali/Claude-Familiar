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


def _heartbeat_key(state: dict[str, Any]) -> tuple[float, float, str]:
    """Freshness ordering for same-owner files: heartbeat, then birth, then id.

    Coerces defensively — a reader never raises on a malformed file (see
    mascot/schema.py), and a garbage `ts` simply sorts as oldest.
    """
    def _num(key: str) -> float:
        try:
            return float(state.get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0
    return (_num("ts"), _num("started"), str(state.get("session_id", "")))


def _prune_owner_ghosts(
    live: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Keep at most one session per owning claude process: the freshest heartbeat.

    A claude process hosts one live session at a time, but a session id can be
    abandoned without a `SessionEnd` — observed with `/login`, which re-keys the
    session under a fresh id in the same process, stranding the pre-login file
    (written once, by the auth_success Notification). That ghost shares its alive
    `owner_pid` with the successor session, so per-file liveness keeps it forever
    and the widget over-counts. The successor always heartbeats after the
    abandoned id's last event, so freshest-`ts`-wins never hides a real session.
    Ownerless files share only ignorance, never a process — left untouched.
    """
    by_owner: dict[int, list[str]] = {}
    for sid, state in live.items():
        if _has_trackable_owner(state):
            by_owner.setdefault(int(state["owner_pid"]), []).append(sid)
    ghosts: set[str] = set()
    for sids in by_owner.values():
        if len(sids) > 1:
            sids.sort(key=lambda sid: _heartbeat_key(live[sid]))
            ghosts.update(sids[:-1])
    return {sid: state for sid, state in live.items() if sid not in ghosts}


def load_states(
    state_dir: Path, now: float, timeout: float = config.STALE_TIMEOUT_S
) -> dict[str, dict[str, Any]]:
    """Return {session_id: state} for every session whose card should be shown.

    Per-file liveness (`is_session_live`) first, then the cross-file rule: one
    card per owning claude process (`_prune_owner_ghosts`).
    """
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
    return _prune_owner_ghosts(live)


def _sweep_stale_tmp(state_dir: Path, now: float) -> None:
    """Best-effort removal of stranded emit temp files (never a fresh in-flight one)."""
    for tmp in state_dir.glob("*.tmp"):
        try:
            if now - tmp.stat().st_mtime > TMP_SWEEP_AGE_S:
                tmp.unlink(missing_ok=True)
        except OSError:
            continue
