"""Process-liveness check for the widget (Windows).

The hook records the owning `claude.exe` PID in each session's state file (see
hooks/proc.py). The widget uses `pid_alive()` to drop a mascot the moment that
process is gone — which happens when the terminal is closed and `SessionEnd`
never fired.

Stdlib only (ctypes). On non-Windows, or on any uncertainty, returns True so we
never prune a session we can't positively confirm is dead — the staleness
timeout remains the backstop.
"""
from __future__ import annotations

import sys
from typing import Any

_PROCESS_SYNCHRONIZE = 0x00100000
_WAIT_TIMEOUT = 0x00000102      # process still running
_ERROR_ACCESS_DENIED = 5        # process exists, we just can't sync on it


def pid_alive(pid: Any) -> bool:
    """True if `pid` names a running process (or we can't tell)."""
    if not pid or sys.platform != "win32":
        return True
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return True
    try:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(_PROCESS_SYNCHRONIZE, False, pid)
        if not handle:
            # No handle: distinguish "gone" from "access denied" (still alive).
            return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
        try:
            return kernel32.WaitForSingleObject(handle, 0) == _WAIT_TIMEOUT
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return True  # never prune on an unexpected error
