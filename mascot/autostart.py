"""Run-at-login support (Windows).

Creates/removes a shortcut in the user's Startup folder pointing at
``run_mascot.py`` via ``pythonw.exe`` (no console window). Shares the shortcut
logic with :mod:`mascot.shortcuts`, so there are no extra dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import shortcuts

_STARTUP = Path(os.environ.get("APPDATA", Path.home())) / \
    "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT = _STARTUP / "Claude Familiar.lnk"


def is_enabled() -> bool:
    return SHORTCUT.exists()


def enable() -> bool:
    """Create the Startup shortcut. Returns True if it now exists."""
    return shortcuts.create_shortcut(SHORTCUT, description="Claude Familiar (run at login)")


def disable() -> bool:
    """Remove the Startup shortcut. Returns True if it is gone."""
    return shortcuts.remove_shortcut(SHORTCUT)


def set_enabled(flag: bool) -> bool:
    return enable() if flag else disable()
