"""Windows shortcut (.lnk) creation for Claude Familiar.

Single home for the WScript.Shell shortcut logic shared by the installer and the
run-at-login feature. A shortcut points ``pythonw.exe`` at ``run_mascot.py`` and
carries the mascot ``.ico``, so the app shows up — and launches — like any other
installed Windows application (Start menu, search, desktop), with no console
window and no extra dependencies.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import icon

APP_NAME = "Claude Familiar"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

_APPDATA = Path(os.environ.get("APPDATA", Path.home()))
START_MENU_DIR = _APPDATA / "Microsoft" / "Windows" / "Start Menu" / "Programs"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"

START_MENU_SHORTCUT = START_MENU_DIR / f"{APP_NAME}.lnk"
DESKTOP_SHORTCUT = DESKTOP_DIR / f"{APP_NAME}.lnk"


def _pythonw() -> Path:
    """pythonw.exe (no console window) if available, else this interpreter."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def create_shortcut(path: Path, *, target: Path | None = None,
                    arguments: str | None = None,
                    description: str = APP_NAME) -> bool:
    """Create/overwrite a .lnk at ``path`` launching the mascot. Returns success.

    Defaults launch ``run_mascot.py`` through ``pythonw.exe`` with the mascot
    icon. ``target``/``arguments`` override that (used by run-at-login).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ico = icon.ensure_ico()  # always keep the icon fresh / present
    target = target or _pythonw()
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
    """Delete a .lnk if present. Returns True if it is gone afterwards."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return not path.exists()


def install_app_shortcuts(desktop: bool = True) -> list[Path]:
    """Register the app: Start-menu entry (always) + optional desktop icon.

    Returns the list of shortcuts that now exist.
    """
    created: list[Path] = []
    if create_shortcut(START_MENU_SHORTCUT):
        created.append(START_MENU_SHORTCUT)
    if desktop and create_shortcut(DESKTOP_SHORTCUT):
        created.append(DESKTOP_SHORTCUT)
    return created


def uninstall_app_shortcuts() -> None:
    """Remove the Start-menu and desktop shortcuts."""
    remove_shortcut(START_MENU_SHORTCUT)
    remove_shortcut(DESKTOP_SHORTCUT)


def is_installed() -> bool:
    """True if the Start-menu shortcut exists (the app is 'installed')."""
    return START_MENU_SHORTCUT.exists()
