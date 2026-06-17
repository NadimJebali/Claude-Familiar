"""Tiny OS-detection helper shared across the mascot's platform-specific code.

Named ``osplatform`` (not ``platform``) so it never shadows the stdlib module.
"""
from __future__ import annotations

import sys

IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform.startswith("linux")
IS_MACOS = sys.platform == "darwin"


def primary_work_area() -> tuple[int, int, int, int] | None:
    """The primary monitor's usable work area as (x, y, width, height).

    On Windows this asks Win32 for SPI_GETWORKAREA, which targets the *primary*
    monitor (not the whole multi-monitor virtual desktop) and already excludes
    the taskbar — so a card anchored to its bottom-right can't be clipped off the
    main screen or hidden behind the taskbar. Returns None on other platforms or
    on any failure, so callers fall back to Tk's own screen metrics.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        SPI_GETWORKAREA = 0x0030
        rect = wintypes.RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        )
        if not ok:
            return None
        return (rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        return None


def monitor_work_area_at(x: int, y: int) -> tuple[int, int, int, int] | None:
    """Work area (x, y, width, height) of the monitor that contains point (x, y).

    Lets a multi-monitor caller clamp a popup to the *same* screen the card is on,
    instead of the primary monitor that Tk's ``winfo_screenwidth()`` always
    reports. Windows only; returns None elsewhere or on any failure so callers
    fall back to Tk's screen metrics.
    """
    if not IS_WINDOWS:
        return None
    try:
        import ctypes
        from ctypes import wintypes

        MONITOR_DEFAULTTONEAREST = 2

        class _MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        user32 = ctypes.windll.user32
        # Pin the signatures so POINT is passed by value and the HMONITOR handle
        # survives on 64-bit (default int return would truncate the pointer).
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]

        hmon = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)),
                                       MONITOR_DEFAULTTONEAREST)
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
            return None
        r = info.rcWork
        return (r.left, r.top, r.right - r.left, r.bottom - r.top)
    except Exception:
        return None
