"""Find the owning Claude process for a hook invocation (Windows).

A hook runs as a short-lived python.exe spawned (through one or more shells) by
the long-lived `claude.exe` CLI process for that session. We walk the process
ancestor chain and return the PID of the nearest `claude.exe` ancestor so the
widget can prune a session's mascot the instant that process dies — e.g. when
the user closes the terminal and `SessionEnd` never fires.

Stdlib only (ctypes). Returns None on non-Windows or any failure — callers must
treat None as "unknown owner" and fall back to the staleness timeout.
"""
from __future__ import annotations

import os
import sys

OWNER_PROCESS_NAME = "claude.exe"
_MAX_DEPTH = 32  # guard against cycles / runaway chains


def find_owner_pid() -> int | None:
    """PID of the nearest `claude.exe` ancestor, or None if not found."""
    if sys.platform != "win32":
        return None
    try:
        procs = _snapshot()  # {pid: (ppid, name_lower)}
    except Exception:
        return None

    pid = os.getpid()
    seen: set[int] = set()
    for _ in range(_MAX_DEPTH):
        entry = procs.get(pid)
        if entry is None or pid in seen:
            break
        seen.add(pid)
        ppid, name = entry
        if name == OWNER_PROCESS_NAME:
            return pid
        pid = ppid
    return None


def _snapshot() -> dict[int, tuple[int, str]]:
    """Map every running pid -> (parent pid, lowercased exe name)."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap == 0:
        raise OSError("CreateToolhelp32Snapshot failed")

    procs: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32First(snap, ctypes.byref(entry)):
            while True:
                name = entry.szExeFile.decode(errors="replace").lower()
                procs[entry.th32ProcessID] = (entry.th32ParentProcessID, name)
                if not kernel32.Process32Next(snap, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snap)
    return procs
