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
