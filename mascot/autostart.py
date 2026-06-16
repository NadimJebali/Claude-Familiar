"""Run-at-login support (Windows).

Creates/removes a shortcut in the user's Startup folder pointing at
``run_mascot.py`` via ``pythonw.exe`` (no console window). The shortcut is made
with WScript.Shell through PowerShell, so there are no extra dependencies.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import icon

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_SCRIPT = PROJECT_ROOT / "run_mascot.py"

_STARTUP = Path(os.environ.get("APPDATA", Path.home())) / \
    "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT = _STARTUP / "Claude Familiar.lnk"


def _pythonw() -> Path:
    """pythonw.exe (no console) if available, else the current interpreter."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def is_enabled() -> bool:
    return SHORTCUT.exists()


def enable() -> bool:
    """Create the Startup shortcut. Returns True if it now exists."""
    _STARTUP.mkdir(parents=True, exist_ok=True)
    ico = icon.ensure_ico()  # mascot icon for the shortcut
    ps = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{SHORTCUT}'); "
        f"$s.TargetPath = '{_pythonw()}'; "
        f"$s.Arguments = '\"{RUN_SCRIPT}\"'; "
        f"$s.WorkingDirectory = '{PROJECT_ROOT}'; "
        f"$s.IconLocation = '{ico}'; "
        "$s.WindowStyle = 7; $s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        check=False, capture_output=True,
    )
    return is_enabled()


def disable() -> bool:
    """Remove the Startup shortcut. Returns True if it is gone."""
    try:
        SHORTCUT.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        return False
    return not is_enabled()


def set_enabled(flag: bool) -> bool:
    return enable() if flag else disable()
