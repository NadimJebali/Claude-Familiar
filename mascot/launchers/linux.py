"""Linux launcher adapter: freedesktop ``.desktop`` entries + XDG autostart.

Wraps :mod:`mascot.desktop_entry` and the destination paths in
:mod:`mascot.shortcuts` (the adapter's internals). The application-menu and
desktop entries open Settings; the run-at-login entry (``~/.config/autostart``)
launches the widget.
"""
from __future__ import annotations

import os
from pathlib import Path

from .. import desktop_entry, icon, shortcuts

APP_NAME = shortcuts.APP_NAME

# App-shortcut destinations live in :mod:`mascot.shortcuts` (single source of truth).
MENU_ENTRY = shortcuts.MENU_ENTRY
DESKTOP_ENTRY = shortcuts.DESKTOP_ENTRY

# Run-at-login destination: an XDG autostart entry.
_CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
AUTOSTART_ENTRY = _CONFIG_HOME / "autostart" / shortcuts.DESKTOP_FILE_NAME


class LinuxLauncher:
    """``.desktop`` launchers (application menu + desktop) and an XDG autostart entry."""

    def install(self, *, desktop: bool = True) -> list[Path]:
        created: list[Path] = []
        targets = [MENU_ENTRY] + ([DESKTOP_ENTRY] if desktop else [])
        for entry in targets:
            if shortcuts.create_desktop_entry(entry):
                created.append(entry)
        return created

    def uninstall(self) -> None:
        shortcuts.remove_shortcut(MENU_ENTRY)
        shortcuts.remove_shortcut(DESKTOP_ENTRY)

    def is_installed(self) -> bool:
        return MENU_ENTRY.exists()

    def enable_autostart(self) -> bool:
        # The autostart entry launches the widget (run_mascot.py), not Settings.
        png = icon.ensure_png()
        exec_cmd = f'"{shortcuts._python()}" "{shortcuts.RUN_SCRIPT}"'
        return desktop_entry.write(
            AUTOSTART_ENTRY, name=APP_NAME, exec_cmd=exec_cmd,
            comment=f"{APP_NAME} (run at login)", icon=str(png),
            path=str(shortcuts.PROJECT_ROOT),
        )

    def disable_autostart(self) -> bool:
        return shortcuts.remove_shortcut(AUTOSTART_ENTRY)

    def autostart_enabled(self) -> bool:
        return AUTOSTART_ENTRY.exists()
