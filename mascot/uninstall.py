"""Full uninstall / reset for Claude Familiar.

Undoes everything the installer created: Claude Code hooks, Start-menu/desktop
and run-at-login shortcuts, the user settings + per-session state directory, and
the generated app icon — returning the machine to its pre-install state.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import autostart, icon, shortcuts

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_HOOKS = PROJECT_ROOT / "scripts" / "install_hooks.py"
MASCOT_DIR = Path.home() / ".claude" / "mascot"
HOOKS_BACKUP = Path.home() / ".claude" / "settings.json.mascot-backup"


def full_uninstall() -> list[str]:
    done: list[str] = []

    # 1) Remove the Claude Code hooks (strips only our blocks; keeps the rest).
    try:
        subprocess.run([sys.executable, str(INSTALL_HOOKS), "--uninstall"],
                       cwd=str(PROJECT_ROOT), check=False, capture_output=True)
        done.append("Removed Claude Code hooks from settings.json")
    except OSError as exc:
        done.append(f"Could not remove hooks: {exc}")

    # 2) Delete the hooks backup file.
    try:
        if HOOKS_BACKUP.exists():
            HOOKS_BACKUP.unlink()
            done.append("Deleted settings.json backup")
    except OSError as exc:
        done.append(f"Could not delete hooks backup: {exc}")

    # 3) Remove Start-menu + desktop shortcuts.
    try:
        shortcuts.uninstall_app_shortcuts()
        done.append("Removed Start-menu and desktop shortcuts")
    except OSError as exc:
        done.append(f"Could not remove shortcuts: {exc}")

    # 4) Disable run-at-login.
    try:
        autostart.disable()
        done.append("Disabled run-at-login")
    except OSError as exc:
        done.append(f"Could not disable run-at-login: {exc}")

    # 5) Delete user settings + per-session state.
    try:
        if MASCOT_DIR.exists():
            shutil.rmtree(MASCOT_DIR, ignore_errors=True)
            done.append("Deleted settings and session state (~/.claude/mascot)")
    except OSError as exc:
        done.append(f"Could not delete settings dir: {exc}")

    # 6) Delete the generated app icons (.ico on Windows, .png on Linux).
    for icon_path in (icon.ICON_PATH, icon.PNG_PATH):
        try:
            if icon_path.exists():
                icon_path.unlink()
                done.append(f"Deleted the generated app icon ({icon_path.name})")
        except OSError as exc:
            done.append(f"Could not delete icon {icon_path.name}: {exc}")

    return done


def main() -> None:
    for line in full_uninstall():
        print(" -", line)


if __name__ == "__main__":
    main()
