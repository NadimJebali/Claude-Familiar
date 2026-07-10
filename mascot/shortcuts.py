"""App-launcher shortcut primitives + destinations for Claude Familiar.

The low-level building blocks the platform launcher adapters
(:mod:`mascot.launchers`) call — not a platform fork itself. The fork lives once,
in :mod:`mascot.launcher`; this module just provides the primitives and the
destination paths:

  * Windows: ``.lnk`` files via pywin32's WScript.Shell COM, pointing
    ``pythonw.exe`` at the target with the mascot ``.ico``, no console.
  * Linux: freedesktop ``.desktop`` entries (via :mod:`mascot.desktop_entry`) with
    the mascot ``.png``.

The user-facing app icon opens the Settings / control panel; the run-at-login
entry launches the widget instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import desktop_entry, icon, osplatform

APP_NAME = "Claude Familiar"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

# The app icon opens the Settings / control panel (run as a module from the
# project root, which is the shortcut's WorkingDirectory).
SETTINGS_MODULE = "mascot.qt_control_panel"
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
_WINDOW_STYLE_MINIMIZED = 7  # WScript.Shell shortcut WindowStyle: no console flash


def create_shortcut(path: Path, *, target: Path | None = None,
                    arguments: str | None = None,
                    description: str = APP_NAME) -> bool:
    """Create/overwrite a .lnk at ``path`` launching the mascot. Returns success.

    Uses pywin32's WScript.Shell COM object directly — no PowerShell subprocess and
    no string-interpolated paths (which broke on quotes / special characters).
    Best-effort: any COM failure is reported and reflected in the return value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    ico = icon.ensure_ico()  # always keep the icon fresh / present
    target = target or Path(_python())
    arguments = arguments if arguments is not None else f'"{RUN_SCRIPT}"'
    try:
        from win32com.client import Dispatch
        link = Dispatch("WScript.Shell").CreateShortcut(str(path))
        link.TargetPath = str(target)
        link.Arguments = arguments
        link.WorkingDirectory = str(PROJECT_ROOT)
        link.IconLocation = str(ico)
        link.Description = description
        link.WindowStyle = _WINDOW_STYLE_MINIMIZED
        link.Save()
    except Exception as exc:  # noqa: BLE001 — shortcut creation must never crash a caller
        print("[mascot] could not create shortcut:", exc)
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
