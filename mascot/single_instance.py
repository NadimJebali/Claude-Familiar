"""Single-instance guard for the widget.

Two widget processes both polling the same state directory would each draw a
card per session at the same screen position — so every mascot appears doubled,
exactly overlapping. This guard lets only one widget run at a time: a second
launch detects the first and bows out.

Windows uses a named mutex (atomic — no stale-lock to clean up). Other platforms
take an exclusive advisory file lock (``flock``), which the OS drops the instant
the process dies, so a crash never leaves a stale lock behind.

``acquire()`` returns a *token* on success or ``None`` if another instance holds
the lock. Keep the token referenced for the whole process lifetime — dropping it
releases the lock.
"""
from __future__ import annotations

from typing import TextIO

from . import config, osplatform

# Session-local namespace (the unqualified name lands in ``Local\``), so each
# interactive user / RDP session gets its own single-instance scope.
_MUTEX_NAME = "ClaudeFamiliarWidget"
_ERROR_ALREADY_EXISTS = 183


class _WindowsGuard:
    """Holds a named-mutex handle alive for the process lifetime."""

    def __init__(self) -> None:
        self._handle = None

    def acquire(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]

        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True  # couldn't create the mutex — don't block startup over it
        if kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle  # keep the handle (and thus the lock) alive
        return True


class _PosixGuard:
    """Holds an exclusive ``flock`` on a lock file for the process lifetime."""

    def __init__(self) -> None:
        self._fd: TextIO | None = None

    def acquire(self) -> bool:
        import fcntl

        lock_path = config.STATE_DIR.parent / "widget.lock"
        try:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            fd = open(lock_path, "w")
        except OSError:
            return True  # can't open the lock file — don't block startup over it
        try:
            # fcntl is POSIX-only; mypy on Windows can't see its attrs (the whole
            # module is platform-gated). See the mypy.ini per-module override.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
        except OSError:
            fd.close()
            return False  # another instance already holds it
        self._fd = fd  # keep the fd (and thus the lock) open
        return True


def acquire() -> object | None:
    """Return a guard token if this is the only widget instance, else ``None``.

    The caller must keep the returned token alive for as long as it wants to
    remain the single instance (i.e. for the whole process)."""
    guard = _WindowsGuard() if osplatform.IS_WINDOWS else _PosixGuard()
    return guard if guard.acquire() else None
