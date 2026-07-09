#!/usr/bin/env python3
"""Statusline emitter for the mascot.

Installed as Claude Code's ``statusLine`` command. Claude runs it on each update
with the statusline JSON on stdin; this script:

  1. distills the account-global usage snapshot (5h + weekly limits, effort) and
     writes it atomically to ``~/.claude/mascot/usage.json`` for the widget's card,
  2. prints a compact ``model · effort · 5h% · wk% · dir`` line for the terminal
     footer,

and ALWAYS exits 0 — a statusline command that errors must never disrupt Claude.

Pure logic lives in ``mascot.statusline`` (tested); this module only does the
stdin read and the atomic write. It never overwrites the snapshot from malformed
or empty input, so a stray invocation can't wipe good numbers.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# emit.py (sibling) for the hardened atomic write; the project root for the pure
# mascot.statusline logic. Both absolute, so this works from any cwd Claude uses.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))

from emit import write_state_atomic  # noqa: E402 — after the sys.path setup

from mascot import statusline  # noqa: E402


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:  # noqa: BLE001 — malformed stdin falls back to an empty payload
        payload = {}

    # Only persist real input; malformed/empty stdin must not clobber a good file.
    if isinstance(payload, dict) and payload:
        snapshot = statusline.snapshot_from_status(payload, time.time())
        write_state_atomic(statusline.USAGE_PATH, snapshot)

    # The footer prints for any payload ("" when there's nothing to show).
    try:
        sys.stdout.write(statusline.footer_line(payload if isinstance(payload, dict) else {}))
    except Exception:  # noqa: BLE001 — never let footer formatting break the hook
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 — the statusline command must never crash Claude
        pass
    sys.exit(0)
