#!/usr/bin/env python3
"""Demo the mascot widget with fake sessions — including the Tamagotchi pet.

Creates a couple of test state files AND seeds a demo pet (a hatched, slightly
hungry teen with coins + items) so you can see the evolved creature, the idle-face
mood, the hover tooltip, the food/zzz popups, and the Pet window (tray "Pet…", the
on-card paw button, or Settings). Your real pet.json is backed up and restored on
exit, so the demo never touches your actual progress.

Run with:  python demo.py   (stop with Ctrl+C)
"""
import json
import subprocess
import sys
import time
from pathlib import Path

BASE = Path.home() / ".claude" / "mascot"
STATE_DIR = BASE / "state"
PET_PATH = BASE / "pet.json"
STATE_DIR.mkdir(parents=True, exist_ok=True)

now = time.time()
DAY = 86400.0

# One busy card and one idle card — the idle one shows the pet's mood face, the
# hover tooltip, and the food/zzz popups (busy states always win on the face).
states = [
    {
        "session_id": "demo-frontend",
        "cwd": "C:/project/frontend",
        "state": "working",
        "tool": "Edit",
        "subagents": [{"id": "a", "type": "code-reviewer"}],
        "effort": "max",        # rainbow-animated panel (steady working card)
        "ts": now,
    },
    {
        "session_id": "demo-backend",
        "cwd": "C:/project/backend",
        "state": "idle",
        "tool": None,
        "subagents": [],
        "effort": "xhigh",      # purple wave panel (steady idle card)
        "ts": now,
    },
]

# A third "tour" card cycles through the newer looks while the demo runs: the
# per-tool working faces, plan-mode planning, compacting, and the post-error
# stumble. Each entry overlays the tour card's base state for TOUR_STEP_S.
TOUR_STEP_S = 4.0
TOUR_BASE = {
    "session_id": "demo-tour",
    "cwd": "C:/project/tour",
    "subagents": [],
    "tool": None,
    "permission_mode": "",
    "stumbled": False,
    "effort": "high",       # the tour card wears a steady periwinkle (static) tint
}
TOUR_PHASES = [
    {"state": "working", "tool": "Read"},        # reading eyes
    {"state": "working", "tool": "Edit"},        # editing concentration
    {"state": "working", "tool": "Bash"},        # gritted-teeth run face
    {"state": "working", "tool": "WebSearch"},   # scanning-the-web eyes
    {"state": "thinking", "permission_mode": "plan"},   # planning…
    {"state": "compacting"},                     # tidying memories…
    {"state": "idle", "stumbled": True},         # brief embarrassed "oops"
]


def _write_tour_phase(index: int) -> None:
    phase = TOUR_PHASES[index % len(TOUR_PHASES)]
    state = {**TOUR_BASE, **phase, "ts": time.time()}
    (STATE_DIR / "demo-tour.json").write_text(json.dumps(state, indent=2))

# A demo pet: a teen (level 5, 2 days old), a little hungry so you can see the
# "hungry" idle face + the food popup, with coins + items to try the shop.
demo_pet = {
    "name": "Pixel",
    "born": now - 2 * DAY,
    "last_seen": now,
    "hunger": 18, "happiness": 72, "energy": 84,
    "coins": 120, "xp": 480,            # level 5 + 2d age -> teen stage
    "coins_today": 0, "last_award_date": "", "last_prompt_date": "",
    "days_active": 9, "streak": 4, "best_streak": 6,   # history: flower earned
    "inventory": {"snack": 3, "ball": 1}, "cooldowns": {},
    "wardrobe": ["party_hat", "flower"],
    "equipped": {"head": "party_hat"},  # worn on the card + in the Pet window
}

print("Creating demo state files + a demo pet...")
for state in states:
    (STATE_DIR / f"{state['session_id']}.json").write_text(json.dumps(state, indent=2))

# Back up any real pet so the demo never clobbers your progress.
pet_backup = PET_PATH.read_bytes() if PET_PATH.exists() else None
PET_PATH.write_text(json.dumps(demo_pet, indent=2), encoding="utf-8")

print()
print("Launching mascot widget (tkinter)...")
print("✓ Three cards appear bottom-right: one working, one idle, one on a face tour")
print("✓ The tour card cycles: reading / editing / running / browsing eyes,")
print("  planning (plan mode), tidying memories (compacting), and a brief 'oops…'")
print("✓ The idle card shows the pet's mood face + a food popup (it's hungry)")
print("✓ Hover a card for the status tooltip (needs / coins / level / name)")
print("✓ Click the paw button (or tray 'Pet...') to open the Pet window — shop, feed, play")
print("✓ Tap a card to pet it (+1 coin, rising hearts)")
print("✓ Press Ctrl+C here to stop")
print()

proc = subprocess.Popen([sys.executable, "-m", "mascot"], cwd=Path(__file__).parent)

try:
    step = 0
    while proc.poll() is None:
        _write_tour_phase(step)
        step += 1
        time.sleep(TOUR_STEP_S)
except KeyboardInterrupt:
    print("\nStopping...")
    proc.terminate()
    proc.wait(timeout=2)
finally:
    print("Cleaning up demo state files...")
    for state in states:
        (STATE_DIR / f"{state['session_id']}.json").unlink(missing_ok=True)
    (STATE_DIR / "demo-tour.json").unlink(missing_ok=True)
    # Restore your real pet (or remove the demo pet if you had none).
    if pet_backup is not None:
        PET_PATH.write_bytes(pet_backup)
        print("Restored your real pet.json.")
    else:
        PET_PATH.unlink(missing_ok=True)
        print("Removed the demo pet.json.")
    print("Done.")
