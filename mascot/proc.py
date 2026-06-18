"""Process-liveness check for the widget (cross-platform via psutil).

The hook records the owning Claude PID in each session's state file (see
``hooks/proc.py``). The widget uses ``pid_alive()`` to drop a mascot the moment that
process is gone — which happens when the terminal is closed and ``SessionEnd`` never
fired.

psutil is imported **lazily and best-effort**: on any uncertainty (psutil missing,
an unexpected error, or an unknown/garbage pid) we return True, so we never prune a
session we can't positively confirm is dead — the staleness timeout is the backstop.
"""
from __future__ import annotations

from typing import Any


def pid_alive(pid: Any) -> bool:
    """True if ``pid`` names a running process (or we can't tell)."""
    if not pid:
        return True
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    try:
        import psutil
    except Exception:  # noqa: BLE001 — no psutil -> never prune (keep the mascot)
        return True
    try:
        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001 — unexpected error -> never prune
        return True
