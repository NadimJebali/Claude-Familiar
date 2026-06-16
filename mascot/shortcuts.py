"""App-launcher shortcut creation for Claude Familiar (Windows + Linux).

A single home for the platform-specific logic that makes the app show up — and
launch — like any other installed application:

  * Windows: ``.lnk`` files (Start menu + desktop) via WScript.Shell, pointing
    ``pythonw.exe`` at the target with the mascot ``.ico``, no console window.
  * Linux: freedesktop ``.desktop`` entries (application menu + desktop) with the
    mascot ``.png``.

The user-facing app icon opens the Settings / control panel; the run-at-login
entry (see :mod:`mascot.autostart`) launches the widget instead.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import desktop_entry, icon, osplatform

APP_NAME = "Claude Familiar"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

# The app icon opens the Settings / control panel (run as a module from the
# project root, which is the shortcut's WorkingDirectory).
SETTINGS_MODULE = "mascot.control_panel"
SETTINGS_ARGS = f"-m {SETTINGS_MODULE}"

# --- Windows paths ---------------------------------------------------------
_APPDATA = Path(os.environ.get("APPDATA", Path.home()))
START_MENU_DIR = _APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
START_MENU_SHORTCUT = START_MENU_DIR / f"{APP_NAME}.lnk"
DESKTOP_SHORTCUT = DESKTOP_DIR / f"{APP_NAME}.lnk"

# --- Linux paths -----------------------------------------------------------
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
APPS_DIR = _DATA_HOME / "applications"
LINUX_DESKTOP_DIR = Path(os.environ.get("XDG_DESKTOP_DIR", Path.home() / "Desktop"))
DESKTOP_FILE_NAME = "claude-familiar.desktop"
MENU_ENTRY = APPS_DIR / DESKTOP_FILE_NAME
DESKTOP_ENTRY = LINUX_DESKTOP_DIR / DESKTOP_FILE_NAME


def _python() -> str:
    """Quoted interpreter path (pythonw.exe on Windows to avoid a console)."""
    exe = Path(sys.executable)
    if osplatform.IS_WINDOWS:
        pythonw = exe.with_name("pythonw.exe")
        exe = pythonw if pythonw.exists() else exe
    return str(exe)


# --- Windows (.lnk) --------------------------------------------------------
def create_shortcut(path: Path, *, target: Path | None = None,
                    arguments: str | None = None,
                    description: str = APP_NAME) -> bool:
    """Create/overwrite a .lnk at ``path`` launching the mascot. Returns success."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ico = icon.ensure_ico()  # always keep the icon fresh / present
    target = target or Path(_python())
    arguments = arguments if arguments is not None else f'"{RUN_SCRIPT}"'
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{path}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.Arguments = '{arguments}'; "
        f"$s.WorkingDirectory = '{PROJECT_ROOT}'; "
        f"$s.IconLocation = '{ico}'; "
        f"$s.Description = '{description}'; "
        "$s.WindowStyle = 7; $s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=False, capture_output=True,
    )
    return path.exists()


def remove_shortcut(path: Path) -> bool:
    """Delete a shortcut file if present. Returns True if it is gone afterwards."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return not path.exists()


# --- Linux (.desktop) ------------------------------------------------------
def create_desktop_entry(path: Path, *, exec_args: str = SETTINGS_ARGS,
                         comment: str = f"{APP_NAME} — Settings") -> bool:
    """Create/overwrite a .desktop launcher at ``path``. Returns success."""
    png = icon.ensure_png()  # always keep the icon fresh / present
    exec_cmd = f'"{_python()}" {exec_args}'
    return desktop_entry.write(
        path, name=APP_NAME, exec_cmd=exec_cmd, comment=comment,
        icon=str(png), path=str(PROJECT_ROOT),
    )


# --- platform-dispatching public API ---------------------------------------
def install_app_shortcuts(desktop: bool = True) -> list[Path]:
    """Register the app: menu entry (always) + optional desktop icon.

    These open the Settings / control panel (the run-at-login entry, created
    separately, is what launches the widget). Returns the shortcuts that exist.
    """
    created: list[Path] = []
    if osplatform.IS_WINDOWS:
        targets = [START_MENU_SHORTCUT] + ([DESKTOP_SHORTCUT] if desktop else [])
        for shortcut in targets:
            if create_shortcut(shortcut, arguments=SETTINGS_ARGS,
                               description=f"{APP_NAME} — Settings"):
                created.append(shortcut)
    else:
        targets = [MENU_ENTRY] + ([DESKTOP_ENTRY] if desktop else [])
        for entry in targets:
            if create_desktop_entry(entry):
                created.append(entry)
    return created


def uninstall_app_shortcuts() -> None:
    """Remove the menu and desktop shortcuts for the current platform."""
    if osplatform.IS_WINDOWS:
        remove_shortcut(START_MENU_SHORTCUT)
        remove_shortcut(DESKTOP_SHORTCUT)
    else:
        remove_shortcut(MENU_ENTRY)
        remove_shortcut(DESKTOP_ENTRY)


def is_installed() -> bool:
    """True if the menu shortcut exists (the app is 'installed')."""
    return (START_MENU_SHORTCUT if osplatform.IS_WINDOWS else MENU_ENTRY).exists()
