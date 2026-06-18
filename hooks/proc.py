"""Find the owning Claude process for a hook invocation (Windows + Linux).

A hook runs as a short-lived python process spawned (through one or more shells)
by the long-lived Claude Code CLI process for that session. We walk the process
ancestor chain and return the PID of the nearest Claude ancestor so the widget
can prune a session's mascot the instant that process dies — e.g. when the user
closes the terminal and `SessionEnd` never fires.

Stdlib only (ctypes on Windows, ``/proc`` on Linux). Returns None on any other
platform or any failure — callers must treat None as "unknown owner" and fall
back to the staleness timeout.
"""
from __future__ import annotations

import os
import sys

OWNER_PROCESS_NAME = "claude.exe"   # Windows exe name
OWNER_PROCESS_COMM = "claude"       # Linux /proc comm (truncated to 15 chars)
_MAX_DEPTH = 32  # guard against cycles / runaway chains


def find_owner_pid() -> int | None:
    """PID of the nearest Claude ancestor, or None if not found."""
    if sys.platform == "win32":
        snapshot, matches = _snapshot, _is_owner_windows
    elif sys.platform.startswith("linux"):
        snapshot, matches = _snapshot_linux, _is_owner_linux
    else:
        return None
    try:
        procs = snapshot()  # {pid: (ppid, name)}
    except Exception:  # noqa: BLE001 — a snapshot failure just means "owner unknown"
        return None

    pid = os.getpid()
    seen: set[int] = set()
    for _ in range(_MAX_DEPTH):
        entry = procs.get(pid)
        if entry is None or pid in seen:
            break
        seen.add(pid)
        ppid, name = entry
        if matches(name):
            return pid
        pid = ppid
    return None


def _is_owner_windows(name: str) -> bool:
    return name == OWNER_PROCESS_NAME


def _is_owner_linux(name: str) -> bool:
    # /proc comm is truncated to 15 chars; match the Claude CLI process name.
    return name == OWNER_PROCESS_COMM or name.startswith("claude")


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


def _parse_stat(text: str) -> tuple[int, str] | None:
    """Parse a /proc/<pid>/stat line -> (parent pid, comm).

    comm is wrapped in parentheses and may itself contain spaces or ')', so we
    split on the LAST ')': the two fields after it are state and ppid.
    """
    open_paren = text.find("(")
    close_paren = text.rfind(")")
    if open_paren == -1 or close_paren == -1 or close_paren < open_paren:
        return None
    comm = text[open_paren + 1:close_paren]
    rest = text[close_paren + 1:].split()
    if len(rest) < 2:
        return None
    try:
        return int(rest[1]), comm  # rest[0] is state, rest[1] is ppid
    except ValueError:
        return None


def _snapshot_linux() -> dict[int, tuple[int, str]]:
    """Map every running pid -> (parent pid, comm) by reading /proc."""
    procs: dict[int, tuple[int, str]] = {}
    for entry in os.scandir("/proc"):
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/stat", encoding="utf-8") as fh:
                parsed = _parse_stat(fh.read())
        except OSError:
            continue  # process vanished between scandir and open
        if parsed is not None:
            procs[int(entry.name)] = parsed
    return procs
