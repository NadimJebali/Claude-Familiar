"""Tk-free setup actions behind the control panel.

The control panel is the UI; the install / uninstall / hooks / reset logic lives
here, returning plain data (booleans, ``(ok, message)`` tuples, lists) so it can
be tested without a Tk root. Shortcut + run-at-login work goes through the
launcher seam (:mod:`mascot.launcher`); hook (un)installation shells out to the
installer script, the single source of how the hooks are written.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from . import launcher, pet_store

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMIT_PY = PROJECT_ROOT / "hooks" / "emit.py"
INSTALL_HOOKS = PROJECT_ROOT / "scripts" / "install_hooks.py"
SETTINGS_PATH = Path.home() / ".claude" / "settings.json"


# --- Claude Code hooks -----------------------------------------------------
def hooks_installed(settings_path: Path = SETTINGS_PATH) -> bool:
    """True if our emit.py is referenced by a hook command in settings.json.

    The single app-side definition of 'are the hooks installed?' — the same notion
    the installer writes (emit.py invoked as a hook command).
    """
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    needle = str(EMIT_PY)
    for entries in (data.get("hooks") or {}).values():
        for entry in entries if isinstance(entries, list) else []:
            for hook in entry.get("hooks", []):
                if needle in hook.get("command", ""):
                    return True
    return False


def install_hooks() -> tuple[bool, str]:
    """Run the hook installer (writes Claude Code's settings.json). Returns (ok, message)."""
    try:
        proc = subprocess.run([sys.executable, str(INSTALL_HOOKS)],
                              capture_output=True, text=True)
    except OSError as exc:
        return False, f"Hook install failed: {exc}"
    if proc.returncode == 0:
        return True, "Hooks installed."
    return False, f"Hook install failed: {proc.stderr[:200]}"


# --- app shortcuts + run-at-login (through the launcher seam) ---------------
def shortcuts_installed() -> bool:
    return launcher.is_installed()


def toggle_shortcuts(desktop: bool = True) -> tuple[bool, str]:
    """Add or remove the app shortcuts. Returns (installed_now, message)."""
    if launcher.is_installed():
        launcher.uninstall()
        return False, "Removed Claude Familiar shortcuts."
    created = launcher.install(desktop=desktop)
    return True, (f"Added {len(created)} shortcut(s). "
                  "Find it in the Start menu / on your desktop.")


def autostart_enabled() -> bool:
    return launcher.autostart_enabled()


def set_autostart(enabled: bool) -> bool:
    """Enable/disable run-at-login. Returns the resulting state."""
    launcher.set_autostart(enabled)
    return launcher.autostart_enabled()


# --- pet + full uninstall --------------------------------------------------
def reset_pet() -> tuple[bool, str]:
    """Overwrite pet.json with a fresh egg. Returns (ok, message).

    A running widget picks this up via its external-change reload (it is the single
    writer; this is a deliberate out-of-band reset from Settings).
    """
    try:
        now = time.time()
        pet_store.save(pet_store.PET_PATH, pet_store.default_pet(now), now)
    except OSError as exc:
        return False, f"Could not reset pet: {exc}"
    return True, "Pet progress reset — a fresh egg is on the way."


def uninstall() -> list[str]:
    """Undo everything the installer created. Returns the actions taken."""
    from . import uninstall as uninstall_mod
    return uninstall_mod.full_uninstall()
