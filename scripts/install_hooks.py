#!/usr/bin/env python3
"""Install / uninstall the mascot hooks in Claude Code's settings.json.

These hooks make Claude Code call ``hooks/emit.py`` on every lifecycle event so
the mascot widget can reflect what Claude is doing in real time.

The entries are written in Claude Code's real hook format::

    "hooks": {
      "<EventName>": [
        { "matcher": "*",            # PreToolUse / PostToolUse only
          "hooks": [
            { "type": "command",
              "command": "\"<python>\" \"<emit.py>\" <EventName>" }
          ]
        }
      ]
    }

The command uses the **absolute interpreter path** (``sys.executable``) and the
**absolute path to emit.py**, so the hooks work regardless of the cwd Claude is
launched from or whether a venv is active.

Usage::

    python scripts/install_hooks.py            # install (idempotent)
    python scripts/install_hooks.py --uninstall # remove our hooks
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
BACKUP_PATH = Path.home() / ".claude" / "settings.json.mascot-backup"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EMIT_PY = PROJECT_ROOT / "hooks" / "emit.py"
PYTHON_EXE = sys.executable

# Events the mascot listens to. PreToolUse/PostToolUse need a "*" matcher so the
# hook fires for every tool; the rest are not tool-scoped.
TOOL_EVENTS = ("PreToolUse", "PostToolUse")
EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "Notification",
    "Stop",
    "StopFailure",  # turn ended on an API error (usage/rate limit, auth, billing, ...)
    "SubagentStop",
    "SessionEnd",
)


def _command_for(event: str) -> str:
    """The shell command Claude runs for one hook event."""
    return f'"{PYTHON_EXE}" "{EMIT_PY}" {event}'


def _is_mascot_hook(entry: dict[str, Any]) -> bool:
    """True if a matcher block was installed by us (calls our emit.py)."""
    emit_str = str(EMIT_PY)
    for hook in entry.get("hooks", []):
        if emit_str in hook.get("command", ""):
            return True
    return False


def _matcher_block(event: str) -> dict[str, Any]:
    """Build one matcher block in Claude Code's hook format for an event."""
    block: dict[str, Any] = {
        "hooks": [{"type": "command", "command": _command_for(event)}]
    }
    if event in TOOL_EVENTS:
        # Tool events match on the tool name; "*" = every tool.
        return {"matcher": "*", **block}
    return block


def _load_settings() -> dict[str, Any]:
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    print(f"{SETTINGS_PATH} does not exist yet — creating a new settings file.")
    return {}


def _save_settings(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _backup_once() -> None:
    """Back up the original settings.json the first time we touch it."""
    if SETTINGS_PATH.exists() and not BACKUP_PATH.exists():
        BACKUP_PATH.write_text(
            SETTINGS_PATH.read_text(encoding="utf-8"), encoding="utf-8"
        )
        print(f"Backed up original settings to {BACKUP_PATH}")


def install() -> None:
    if not EMIT_PY.exists():
        print(f"emit.py not found at {EMIT_PY}")
        sys.exit(1)

    settings = _load_settings()
    _backup_once()

    hooks: dict[str, Any] = settings.setdefault("hooks", {})

    for event in EVENTS:
        existing = hooks.get(event)
        if not isinstance(existing, list):
            # No (or malformed) entry for this event — create the list.
            hooks[event] = [_matcher_block(event)]
            print(f"Added hook: {event}")
            continue

        # Drop any prior mascot blocks (keeps the script idempotent and refreshes
        # a stale interpreter/emit path), preserve the user's other hooks.
        kept = [e for e in existing if not _is_mascot_hook(e)]
        was_present = len(kept) != len(existing)
        kept.append(_matcher_block(event))
        hooks[event] = kept
        print(f"{'Updated' if was_present else 'Added'} hook: {event}")

    _save_settings(settings)
    print()
    print(f"Hooks installed in {SETTINGS_PATH}")
    print("Interpreter:", PYTHON_EXE)
    print()
    print("Next: run the widget, then start a Claude Code session:")
    print("  python -m mascot")


def uninstall() -> None:
    if not SETTINGS_PATH.exists():
        print(f"No settings file at {SETTINGS_PATH} — nothing to remove.")
        return

    settings = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})

    removed = 0
    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not _is_mascot_hook(e)]
        removed += len(entries) - len(kept)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)

    _save_settings(settings)
    print(f"Removed {removed} mascot hook block(s) from {SETTINGS_PATH}")
    if BACKUP_PATH.exists():
        print(f"(Original backup still available at {BACKUP_PATH})")


def main() -> None:
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()


if __name__ == "__main__":
    main()
