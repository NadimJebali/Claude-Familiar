#!/usr/bin/env python3
"""One-step installer for Claude Familiar.

Installs the Claude Code hooks, then opens the settings/control panel where you
can pick the mascot, enable run-at-login, and launch the widget.

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
    print("\nOpening the settings panel...")
    subprocess.run([sys.executable, "-m", "mascot.control_panel"], cwd=str(ROOT), check=False)


if __name__ == "__main__":
    main()
