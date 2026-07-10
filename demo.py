#!/usr/bin/env python3
"""Demo the mascot widget with fake sessions — including the Tamagotchi pet.

Creates a few test state files AND seeds a demo pet (a hatched, slightly
hungry teen with coins + items) so you can see the evolved creature, the idle-face
mood, the hover tooltip, the food/zzz popups, and the Pet window (tray "Pet…", the
on-card paw button, or Settings). The states carry an ``effort`` level, a demo
``usage.json`` is seeded, and each session gets a tiny demo *transcript* so the
context rings fill (76% amber / 96% red / 30% calm). Your real pet.json +
usage.json + settings.json are backed up and restored on exit, so the demo never
touches your actual progress.

Run with:  python demo.py             (stop with Ctrl+C)
           python demo.py --compact   the Compact theme: one panel, session rows
           python demo.py --stale     age the usage snapshot -> the "stale" label
"""
import json
import subprocess
import sys
import time
from pathlib import Path

COMPACT = "--compact" in sys.argv
STALE = "--stale" in sys.argv

# The status output below uses check-marks; force UTF-8 so a non-UTF-8 Windows
# console (cp1252) renders them instead of crashing with UnicodeEncodeError.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

BASE = Path.home() / ".claude" / "mascot"
STATE_DIR = BASE / "state"
PET_PATH = BASE / "pet.json"
USAGE_PATH = BASE / "usage.json"
TRANSCRIPT_DIR = BASE / "demo-transcripts"
STATE_DIR.mkdir(parents=True, exist_ok=True)

now = time.time()
DAY = 86400.0


def _write_transcript(sid: str, fill_pct: float) -> str:
    """A tiny demo transcript whose last assistant turn holds fill_pct of the
    200k context window — the real tailer reads it and the ring fills."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    path = TRANSCRIPT_DIR / f"{sid}.jsonl"
    tokens = int(200_000 * fill_pct / 100)
    line = {"type": "assistant", "isSidechain": False, "sessionId": sid,
            "message": {"usage": {"input_tokens": 2,
                                  "cache_read_input_tokens": tokens - 2,
                                  "cache_creation_input_tokens": 0,
                                  "output_tokens": 10}}}
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    return str(path)

# One busy card and one idle card — the idle one shows the pet's mood face, the
# hover tooltip, and the food/zzz popups (busy states always win on the face).
states = [
    {
        "session_id": "demo-frontend",
        "cwd": "C:/project/frontend",
        "state": "working",
        "tool": "Edit",
        "subagents": [{"id": "a", "type": "code-reviewer"}],
        "effort": "max",        # rainbow-animated panel (a steady working card)
        "model": "claude-opus-4-8",
        "transcript_path": _write_transcript("demo-frontend", 76.0),  # amber ring
        "ts": now,
    },
    {
        "session_id": "demo-backend",
        "cwd": "C:/project/backend",
        "state": "idle",
        "tool": None,
        "subagents": [],
        "effort": "xhigh",      # purple-wave panel (a steady idle card)
        "model": "claude-sonnet-5",
        "transcript_path": _write_transcript("demo-backend", 96.0),   # red ring
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
    "model": "claude-haiku-4-5-20251001",
    "transcript_path": _write_transcript("demo-tour", 30.0),          # calm ring
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

# A demo usage snapshot so the bottom bars show without a live statusline: the 5h
# window warning-amber, the weekly window alarm-red. resets_at is far in the future
# so neither decays to zero during the demo. --stale ages the write stamp so the
# bars draw dimmed under the "stale" label (#69).
demo_usage = {
    "five_hour": {"used_percentage": 76, "resets_at": now + 3 * 3600},
    "seven_day": {"used_percentage": 93, "resets_at": now + 5 * DAY},
    "effort": "max",
    "ts": now - 3600 if STALE else now,
}

print("Creating demo state files + a demo pet...")
for state in states:
    (STATE_DIR / f"{state['session_id']}.json").write_text(json.dumps(state, indent=2))

# Back up any real pet + usage to FILES before overwriting, so the demo never clobbers
# your progress even if it dies before cleanup — the finally restores from these
# backups no matter how the run ends (a plain in-memory copy is lost on a crash).
PET_BACKUP = BASE / "pet.json.demo-backup"
USAGE_BACKUP = BASE / "usage.json.demo-backup"
SETTINGS_PATH = BASE / "settings.json"
SETTINGS_BACKUP = BASE / "settings.json.demo-backup"
had_real_pet = PET_PATH.exists()
had_real_usage = USAGE_PATH.exists()
had_real_settings = SETTINGS_PATH.exists()
if had_real_pet:
    PET_BACKUP.write_bytes(PET_PATH.read_bytes())
if had_real_usage:
    USAGE_BACKUP.write_bytes(USAGE_PATH.read_bytes())
if had_real_settings:
    SETTINGS_BACKUP.write_bytes(SETTINGS_PATH.read_bytes())

proc = None
try:
    PET_PATH.write_text(json.dumps(demo_pet, indent=2), encoding="utf-8")
    USAGE_PATH.write_text(json.dumps(demo_usage, indent=2), encoding="utf-8")
    # The demo showcases the pet layer, which ships OFF by default (quiet defaults,
    # #68) — seed a settings.json with the pet on for the run. Your other settings
    # ride along untouched, and your real file is restored on exit like the pet.
    demo_settings = {}
    if had_real_settings:
        try:
            demo_settings = json.loads(SETTINGS_BACKUP.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            demo_settings = {}
    demo_settings["tamagotchi_enabled"] = True
    demo_settings["theme"] = "compact" if COMPACT else "classic"
    SETTINGS_PATH.write_text(json.dumps(demo_settings, indent=2), encoding="utf-8")

    print()
    print("Launching the Claude Familiar widget (PySide6/Qt)...")
    if COMPACT:
        print("✓ COMPACT theme: one panel bottom-right, a slim row per session")
        print("✓ Rows: effort dot · state · model · ×subagents · context ring")
        print("  (frontend rainbow/max 76% ring, backend shimmer/xhigh 96% ring,")
        print("   tour steady/high 30% ring; idle rows draw dimmed)")
        print("✓ Usage bars once at the panel bottom" + (" — dimmed 'stale'" if STALE else ""))
        print("✓ Tray → Theme → Classic switches back LIVE (no restart)")
    else:
        print("✓ Three cards appear bottom-right: one working, one idle, one on a face tour")
        print("✓ The tour card cycles: reading / editing / running / browsing eyes,")
        print("  planning (plan mode), tidying memories (compacting), and a brief 'oops…'")
        print("✓ Each card wears its effort color: the working card rainbow-animates (max),")
        print("  the idle card waves purple (xhigh), the tour card is a steady tint (high)")
        print("✓ A context ring sits top-right: 76% amber, 96% red, 30% calm")
        print("✓ Usage bars sit at each card's bottom: 5h (amber) + weekly (red)"
              + (" — dimmed 'stale'" if STALE else ""))
        print("✓ The idle card shows the pet's mood face + a food popup (it's hungry)")
        print("✓ Hover a card for the status tooltip (needs / coins / level / name)")
        print("✓ Click the paw button (or tray 'Pet…') to open the Pet window — shop, feed, play")
        print("✓ Tap a card to pet it (+1 coin, rising hearts); faces crossfade, motion is smooth")
        print("✓ Tray → Theme → Compact switches to the session-list panel LIVE")
    print("✓ Press Ctrl+C here to stop")
    print()

    proc = subprocess.Popen([sys.executable, "-m", "mascot.qt_app"], cwd=Path(__file__).parent)
    step = 0
    while proc.poll() is None:
        _write_tour_phase(step)
        step += 1
        time.sleep(TOUR_STEP_S)
except KeyboardInterrupt:
    print("\nStopping...")
    if proc is not None:
        proc.terminate()
        proc.wait(timeout=2)
finally:
    print("Cleaning up demo state files...")
    for state in states:
        (STATE_DIR / f"{state['session_id']}.json").unlink(missing_ok=True)
    (STATE_DIR / "demo-tour.json").unlink(missing_ok=True)
    for sid in ("demo-frontend", "demo-backend", "demo-tour"):
        (TRANSCRIPT_DIR / f"{sid}.jsonl").unlink(missing_ok=True)
    try:
        TRANSCRIPT_DIR.rmdir()
    except OSError:
        pass
    # Restore your real pet + usage (or remove the demo files if you had none).
    if had_real_pet:
        PET_PATH.write_bytes(PET_BACKUP.read_bytes())
        PET_BACKUP.unlink(missing_ok=True)
        print("Restored your real pet.json.")
    else:
        PET_PATH.unlink(missing_ok=True)
        print("Removed the demo pet.json.")
    if had_real_usage:
        USAGE_PATH.write_bytes(USAGE_BACKUP.read_bytes())
        USAGE_BACKUP.unlink(missing_ok=True)
    else:
        USAGE_PATH.unlink(missing_ok=True)
    if had_real_settings:
        SETTINGS_PATH.write_bytes(SETTINGS_BACKUP.read_bytes())
        SETTINGS_BACKUP.unlink(missing_ok=True)
        print("Restored your real settings.json.")
    else:
        SETTINGS_PATH.unlink(missing_ok=True)
    print("Done.")
