"""Phase 0 installer: register the logging emitter into ~/.claude/settings.json.

This wires emit_logging.py into every relevant Claude Code hook event so we can
capture the real payload schema. It is SAFE and REVERSIBLE:

  - Backs up settings.json before any change (timestamped copy).
  - Idempotent: re-running won't add duplicates.
  - `--uninstall` removes every hook entry that points at emit_logging.py.

Usage:
    python scripts/install_logging_hooks.py            # install
    python scripts/install_logging_hooks.py --uninstall # remove

After installing, RESTART any open Claude Code sessions (hooks load at startup),
run a session, trigger events, then inspect ~/.claude/mascot/hook-log.jsonl.
"""
import sys
import json
import time
import shutil
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude" / "settings.json"
EMIT_LOGGING = (Path(__file__).resolve().parent.parent / "hooks" / "emit_logging.py").resolve()
MARKER = "emit_logging.py"  # identifies entries we own, for idempotency + uninstall

# Events with a tool matcher vs. events without one.
TOOL_EVENTS = ["PreToolUse", "PostToolUse"]
PLAIN_EVENTS = [
    "SessionStart",
    "UserPromptSubmit",
    "Notification",
    "Stop",
    "SubagentStop",
    "SessionEnd",
]


def command_for(event: str) -> str:
    return f'"{sys.executable}" "{EMIT_LOGGING}" {event}'


def load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"ERROR: {SETTINGS_PATH} is not valid JSON. Fix it first.")
            sys.exit(1)
    return {}


def backup_settings() -> None:
    if SETTINGS_PATH.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = SETTINGS_PATH.with_suffix(f".json.mascot-bak-{stamp}")
        shutil.copy2(SETTINGS_PATH, dest)
        print(f"Backed up settings.json -> {dest.name}")


def save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def is_ours(entry: dict) -> bool:
    return any(MARKER in h.get("command", "") for h in entry.get("hooks", []))


def install() -> None:
    settings = load_settings()
    backup_settings()
    hooks = settings.setdefault("hooks", {})

    def add(event: str, matcher: str | None) -> None:
        entries = hooks.setdefault(event, [])
        if any(is_ours(e) for e in entries):
            print(f"  {event}: already installed, skipping")
            return
        entry: dict = {"hooks": [{"type": "command", "command": command_for(event)}]}
        if matcher is not None:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
        print(f"  {event}: installed")

    for event in TOOL_EVENTS:
        add(event, matcher="*")
    for event in PLAIN_EVENTS:
        add(event, matcher=None)

    save_settings(settings)
    print("\nDone. Restart Claude Code sessions, then trigger events.")
    print("Log: ~/.claude/mascot/hook-log.jsonl")


def uninstall() -> None:
    settings = load_settings()
    if "hooks" not in settings:
        print("No hooks present.")
        return
    backup_settings()
    removed = 0
    for event, entries in list(settings["hooks"].items()):
        kept = [e for e in entries if not is_ours(e)]
        removed += len(entries) - len(kept)
        if kept:
            settings["hooks"][event] = kept
        else:
            del settings["hooks"][event]
    if not settings["hooks"]:
        del settings["hooks"]
    save_settings(settings)
    print(f"Removed {removed} logging hook entr{'y' if removed == 1 else 'ies'}.")


if __name__ == "__main__":
    if "--uninstall" in sys.argv:
        uninstall()
    else:
        install()
