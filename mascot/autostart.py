"""Run-at-login support — a thin shim over the launcher seam.

Enabling/disabling run-at-login is platform-specific (a Startup ``.lnk`` on
Windows, an XDG autostart ``.desktop`` on Linux), but that fork now lives once in
:mod:`mascot.launcher`'s adapters. This module keeps a stable
``is_enabled``/``enable``/``disable``/``set_enabled`` surface for callers and
delegates straight through — no platform branching, no reaching into shortcut
internals.
"""
from __future__ import annotations

from . import launcher


def is_enabled() -> bool:
    return launcher.autostart_enabled()


def enable() -> bool:
    """Create the run-at-login entry (launches the widget). Returns success."""
    return launcher.set_autostart(True)


def disable() -> bool:
    """Remove the run-at-login entry. Returns True if it is gone."""
    return launcher.set_autostart(False)


def set_enabled(flag: bool) -> bool:
    return launcher.set_autostart(flag)
