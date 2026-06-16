"""Run-at-login support (Windows + Linux).

Creates/removes an entry that launches the *widget* (not the settings panel) when
the user logs in:

  * Windows: a ``.lnk`` in the user's Startup folder (via :mod:`mascot.shortcuts`).
  * Linux: a ``.desktop`` file in ``~/.config/autostart`` (XDG autostart).

Shares its building blocks with :mod:`mascot.shortcuts`, so there are no extra
dependencies.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import desktop_entry, icon, osplatform, shortcuts

APP_NAME = shortcuts.APP_NAME

# Windows Startup folder shortcut.
_STARTUP = Path(os.environ.get("APPDATA", Path.home())) / \
    "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
WIN_SHORTCUT = _STARTUP / f"{APP_NAME}.lnk"

# Linux XDG autostart entry.
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
LINUX_AUTOSTART = _CONFIG_HOME / "autostart" / shortcuts.DESKTOP_FILE_NAME


def is_enabled() -> bool:
    return (WIN_SHORTCUT if osplatform.IS_WINDOWS else LINUX_AUTOSTART).exists()


def enable() -> bool:
    """Create the run-at-login entry (launches the widget). Returns success."""
    if osplatform.IS_WINDOWS:
        return shortcuts.create_shortcut(
            WIN_SHORTCUT, description=f"{APP_NAME} (run at login)")
    png = icon.ensure_png()
    exec_cmd = f'"{shortcuts._python()}" "{shortcuts.RUN_SCRIPT}"'
    return desktop_entry.write(
        LINUX_AUTOSTART, name=APP_NAME, exec_cmd=exec_cmd,
        comment=f"{APP_NAME} (run at login)", icon=str(png),
        path=str(shortcuts.PROJECT_ROOT),
    )


def disable() -> bool:
    """Remove the run-at-login entry. Returns True if it is gone."""
    target = WIN_SHORTCUT if osplatform.IS_WINDOWS else LINUX_AUTOSTART
    return shortcuts.remove_shortcut(target)


def set_enabled(flag: bool) -> bool:
    return enable() if flag else disable()
