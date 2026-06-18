"""Find the owning Claude process for a hook invocation (cross-platform via psutil).

A hook runs as a short-lived python process spawned (through one or more shells) by
the long-lived Claude Code CLI process for that session. We walk the process
ancestor chain and return the PID of the nearest Claude ancestor, so the widget can
prune a session's mascot the instant that process dies — e.g. when the user closes
the terminal and `SessionEnd` never fires.

psutil is imported **lazily and best-effort**: any failure (psutil not installed, a
process that vanished mid-walk, access denied) returns None, and callers treat None
as "unknown owner" and fall back to the staleness timeout. ``emit`` stamps
``owner_pid`` once per session, so the import cost is paid at most once per session.
"""
from __future__ import annotations

# The Claude CLI process name across platforms: "claude.exe" on Windows, the comm
# "claude" (Linux truncates comm to 15 chars). A prefix match also covers
# "claude-code" and similar.
_OWNER_PREFIX = "claude"
_MAX_DEPTH = 32  # guard against runaway ancestor chains


def _is_owner_name(name: str) -> bool:
    """True if a process name is the Claude CLI (cross-platform, case-insensitive)."""
    return (name or "").lower().startswith(_OWNER_PREFIX)


def find_owner_pid() -> int | None:
    """PID of the nearest Claude ancestor of this process, or None if not found."""
    try:
        import psutil
    except Exception:  # noqa: BLE001 — no psutil -> "owner unknown" (staleness backstop)
        return None
    try:
        proc = psutil.Process()
        for _ in range(_MAX_DEPTH):
            if proc is None:
                break
            try:
                name = proc.name()
            except psutil.Error:
                break              # vanished / access denied — stop the walk
            if _is_owner_name(name):
                return proc.pid
            proc = proc.parent()
    except Exception:  # noqa: BLE001 — any walk failure just means "owner unknown"
        return None
    return None
