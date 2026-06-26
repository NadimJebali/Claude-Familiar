"""Windows launcher adapter: ``.lnk`` shortcuts + Startup entry.

Wraps the pywin32 COM ``.lnk`` writer in :mod:`mascot.shortcuts` (the adapter's
internals — destination paths and the low-level create/remove primitives). The
app-icon shortcuts open Settings; the run-at-login Startup shortcut launches the
widget. COM is imported lazily inside the writer, so this module imports fine on
every platform.
"""
from __future__ import annotations

from pathlib import Path

from .. import shortcuts

APP_NAME = shortcuts.APP_NAME

# App-shortcut destinations live in :mod:`mascot.shortcuts` (single source of
# truth). The run-at-login destination is the Startup folder, under the same
# Start-menu/Programs root.
START_MENU_SHORTCUT = shortcuts.START_MENU_SHORTCUT
DESKTOP_SHORTCUT = shortcuts.DESKTOP_SHORTCUT
STARTUP_SHORTCUT = shortcuts.START_MENU_DIR / "Startup" / f"{APP_NAME}.lnk"


class WindowsLauncher:
    """``.lnk`` shortcuts (Start menu + desktop) and a Startup run-at-login entry."""

    def install(self, *, desktop: bool = True) -> list[Path]:
        created: list[Path] = []
        targets = [START_MENU_SHORTCUT] + ([DESKTOP_SHORTCUT] if desktop else [])
        for shortcut in targets:
            if shortcuts.create_shortcut(shortcut, arguments=shortcuts.SETTINGS_ARGS,
                                         description=f"{APP_NAME} — Settings"):
                created.append(shortcut)
        return created

    def uninstall(self) -> None:
        shortcuts.remove_shortcut(START_MENU_SHORTCUT)
        shortcuts.remove_shortcut(DESKTOP_SHORTCUT)

    def is_installed(self) -> bool:
        return START_MENU_SHORTCUT.exists()

    def enable_autostart(self) -> bool:
        # Default args launch the widget (run_mascot.py), not Settings.
        return shortcuts.create_shortcut(
            STARTUP_SHORTCUT, description=f"{APP_NAME} (run at login)")

    def disable_autostart(self) -> bool:
        return shortcuts.remove_shortcut(STARTUP_SHORTCUT)

    def autostart_enabled(self) -> bool:
        return STARTUP_SHORTCUT.exists()
