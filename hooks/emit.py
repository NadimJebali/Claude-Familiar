"""Real hook emitter.

Invoked by every Claude Code hook as:  python emit.py <EventName>
Reads the hook payload as JSON on stdin, updates this session's state file with
an atomic write, and ALWAYS exits 0 — a hook that errors can disrupt Claude.

Logic lives in state_logic.compute_next_state (pure, tested). This module is the
only thing that does I/O and stamps the heartbeat `ts`.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from proc import find_owner_pid
from state_logic import compute_next_state, default_state

STATE_DIR = Path.home() / ".claude" / "mascot" / "state"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _state_path(state_dir: Path, session_id: str) -> Path:
    return state_dir / f"{_SAFE.sub('_', session_id)}.json"


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


# os.replace can transiently fail on Windows (PermissionError sharing violation)
# while the widget holds the destination open for its poll read. Retry briefly;
# if it still fails, clean up the temp file — an emit that leaks .tmp files under
# heavy concurrent hook traffic litters the state dir forever (observed live).
_REPLACE_ATTEMPTS = 3
_REPLACE_BACKOFF_S = 0.03


def write_state_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)  # atomic on the same filesystem
            return
        except OSError:
            if attempt < _REPLACE_ATTEMPTS - 1:
                time.sleep(_REPLACE_BACKOFF_S)
    # Still failing: this update is lost (best-effort, the next hook rewrites),
    # but never leave the temp file behind.
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass


def update_state(
    state_dir: Path, event: str, payload: dict[str, Any], now: float
) -> dict[str, Any] | None:
    """Apply one hook event to the session's state file.

    Returns the new state, or None if there was nothing to do (no session id)
    or the file was deleted (SessionEnd).
    """
    session_id = payload.get("session_id")
    if not session_id:
        return None

    path = _state_path(state_dir, session_id)

    if event == "SessionEnd":
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None

    current = load_state(path) or default_state(
        session_id, payload.get("cwd", ""), payload.get("model", "")
    )
    nxt = compute_next_state(current, event, payload)
    nxt["ts"] = now
    # Record the owning claude.exe PID once per session so the widget can prune
    # this mascot the instant that process dies (closed terminal, no SessionEnd).
    # Key-presence (not truthiness) so a None result isn't re-detected every hook.
    if "owner_pid" not in nxt:
        nxt["owner_pid"] = find_owner_pid()
    # Stamp the session's start time once, so the widget can show its duration.
    if "started" not in nxt:
        nxt["started"] = now
    write_state_atomic(path, nxt)
    return nxt


def _debug_log(event: str, payload: dict[str, Any]) -> None:
    """Opt-in: when CLAUDE_MASCOT_DEBUG is set, append a one-line record of each
    hook event to ~/.claude/mascot/debug.log, so rare flows (e.g. a usage/session
    limit hit) can be diagnosed from the real payloads. Best-effort and silent —
    it must never affect the hook's exit status."""
    if not os.environ.get("CLAUDE_MASCOT_DEBUG"):
        return
    try:
        keys = ("message", "reason", "title", "notification_type", "subtype",
                "tool_name", "error_type")
        fields = {k: payload.get(k) for k in keys if payload.get(k) is not None}
        line = f"{time.time():.0f}\t{event}\t{json.dumps(fields, ensure_ascii=False)}\n"
        log = STATE_DIR.parent / "debug.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 — debug logging must never crash the hook
        pass


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001 — malformed stdin JSON falls back to an empty payload
        payload = {}
    _debug_log(event, payload)
    update_state(STATE_DIR, event, payload, time.time())


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — the hook must never crash the Claude run
        pass
    sys.exit(0)
