#!/usr/bin/env python3
"""Demo the mascot widget with fake sessions.

Creates two test state files and launches the tkinter widget so you can see
the cards without needing live Claude sessions. Cleans up on exit.

Run with:  python demo.py
"""
import json
import subprocess
import sys
import time
from pathlib import Path

state_dir = Path.home() / ".claude" / "mascot" / "state"
state_dir.mkdir(parents=True, exist_ok=True)

states = [
    {
        "session_id": "demo-frontend",
        "cwd": "C:/project/frontend",
        "state": "working",
        "tool": "Edit",
        "subagents": [{"id": "a", "type": "code-reviewer"}],
        "ts": time.time(),
    },
    {
        "session_id": "demo-backend",
        "cwd": "C:/project/backend",
        "state": "thinking",
        "tool": None,
        "subagents": [],
        "ts": time.time(),
    },
]

print("Creating demo state files...")
for state in states:
    (state_dir / f"{state['session_id']}.json").write_text(json.dumps(state, indent=2))

print()
print("Launching mascot widget (tkinter)...")
print("✓ Two windows appear in the bottom-right (⚙️ working, 🤔 thinking)")
print("✓ Drag any card anywhere — it stays where you drop it")
print("✓ Press Ctrl+C here to stop")
print()

proc = subprocess.Popen([sys.executable, "-m", "mascot"], cwd=Path(__file__).parent)

try:
    proc.wait()
except KeyboardInterrupt:
    print("\nStopping...")
    proc.terminate()
    proc.wait(timeout=2)
finally:
    print("Cleaning up demo state files...")
    for state in states:
        (state_dir / f"{state['session_id']}.json").unlink(missing_ok=True)
    print("Done.")
