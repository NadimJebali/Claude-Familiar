"""Real hook emitter.

Invoked by every Claude Code hook as:  python emit.py <EventName>
Reads the hook payload as JSON on stdin, updates this session's state file with
an atomic write, and ALWAYS exits 0 — a hook that errors can disrupt Claude.

Logic lives in state_logic.compute_next_state (pure, tested). This module is the
only thing that does I/O and stamps the heartbeat `ts`.
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state_logic import compute_next_state, default_state  # noqa: E402
from proc import find_owner_pid  # noqa: E402

STATE_DIR = Path.home() / ".claude" / "mascot" / "state"
_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _state_path(state_dir: Path, session_id: str) -> Path:
    return state_dir / f"{_SAFE.sub('_', session_id)}.json"


def load_state(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state_atomic(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


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
    write_state_atomic(path, nxt)
    return nxt


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    update_state(STATE_DIR, event, payload, time.time())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
