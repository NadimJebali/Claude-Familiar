#!/usr/bin/env python3
"""One-step installer for Claude Familiar.

Installs Claude Familiar as a real Windows app: generates the mascot icon,
installs the Claude Code hooks, creates Start-menu + desktop shortcuts (so you
can launch it from the Start menu / search like any other application), then
opens the settings/control panel.

    python install.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    print("Generating the mascot app icon...")
    subprocess.run([sys.executable, "-c",
                    "from mascot import icon; print(icon.ensure_ico())"],
                   cwd=str(ROOT), check=False)

    print("Installing Claude Familiar hooks...")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "install_hooks.py")], check=False)

    print("Adding Claude Familiar to the Start menu and desktop...")
    result = subprocess.run(
        [sys.executable, "-c",
         "from mascot import shortcuts; "
         "print('\\n'.join(str(p) for p in shortcuts.install_app_shortcuts()))"],
        cwd=str(ROOT), check=False, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        if line.strip():
            print(f"  created: {line.strip()}")
    if result.returncode != 0 and result.stderr.strip():
        print(f"  (could not create shortcuts: {result.stderr.strip()})")

    print("\nClaude Familiar is installed. Look for it in the Start menu / on your desktop.")
    print("Opening the settings panel...")
    subprocess.run([sys.executable, "-m", "mascot.control_panel"], cwd=str(ROOT), check=False)


if __name__ == "__main__":
    main()
