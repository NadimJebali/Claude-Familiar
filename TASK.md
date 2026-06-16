# TASK.md — Mascot feature roadmap

Six features for the claude-mascot widget, ordered **easiest → hardest**.
Pure-stdlib Tkinter, no new dependencies. Keep the pure state machine
(`state_logic.py`) unit-tested; GUI is verified visually via `demo.py`.

Status legend: ⬜ todo · 🔄 in progress · ✅ done

---

## Batch A — sprite/animation layer (ship together)

### 1. Happy / celebrate state — ✅
Brief joyful reaction when Claude finishes, before settling to idle.
Widget-side effective state (like `dizzy`/`sleeping`): time-bounded, computed
from a timestamp, **never written to the state file**.
- [x] `sprite_pixel.py`: add `_FACES["happy"]` (smiling/closed-eyes face)
- [x] `config.py`: `STATE_COLORS["happy"]` (gold/green accent)
- [x] `tkinter_app.py`: `STATE_CAPTIONS["happy"]`, `_celebrate_until` timer,
      effective-state priority `dizzy > happy > sleeping/raw`
- [x] Trigger: `update_state` detects active(`working`/`thinking`)→`idle`;
      NOT on `waiting→idle` or `dead`
- [x] Optional hop in `_animate` during `happy`

### 2. Idle "life" animations + longer idle-before-sleep — ✅
- [x] `settings.py`: bump `sleep_after_idle_s` default 30 → 90
- [x] `sprite_pixel.py`: add `idle_blink` face (eyes closed)
- [x] `tkinter_app.py`: periodic blink (~every 4–7s, ~120ms) while effective
      state is `idle`, scheduled off the existing 25fps `_animate` clock

### 3. Click-to-pet + pixel-art hearts — ✅  (reuses happy face from #1)
- [x] `sprite_pixel.py`: `draw_heart(...)` from a small hand-drawn grid (no emoji)
- [x] `tkinter_app.py`: tap-vs-drag detection in drag start/end
- [x] On pet: reuse `happy` face + spawn 2–3 rising/fading heart particles
- [x] Heart particle list animated in `_animate`; cap count, ~0.8s lifetime

---

## Batch B

### 4. Session stats on hover — ✅
Counters live in the **pure, tested** state machine; tooltip mirrors `BubbleWindow`.
- [x] `state_logic.py`: add `tools_run`, `subagents_spawned`, `prompts` to
      `default_state`; increment in `compute_next_state` (uses `current.get(k,0)+1`
      so old state files upgrade cleanly)
- [x] `tests/`: unit tests for each counter (7 tests)
- [x] `tkinter_app.py`: `StatsTooltip` Toplevel + `<Enter>`/`<Leave>` bindings,
      shows `prompts · tools · agents` + uptime; hides during drag; live-updates

### 5. System tray icon + menu — ✅  (Windows; Linux documented unsupported)
Tkinter has no native tray → Win32 `ctypes`, gated to `osplatform.IS_WINDOWS`
(mirrors the Windows-only chroma transparency).
- [x] `mascot/tray.py` (NEW): `Shell_NotifyIconW` + hidden window with our own
      `WndProc` + popup menu (`TPM_RETURNCMD`); reuses the generated `.ico`
- [x] `tkinter_app.py`: `MascotManager` owns the tray. Tk's own Windows message
      loop dispatches the icon's messages to our `WndProc` (no manual pump), so
      menu callbacks run on the Tk thread and touch Tk safely
- [x] Menu: Show / hide cards (`withdraw`/`deiconify`, re-asserting `-topmost`),
      Settings… (`python -m mascot.control_panel`), Quit; left-click also toggles
- [x] Linux: no-op — `tray.py` is imported only on Windows; README note added

---

## Bug fixes

### Session-limit "stuck at thinking" — ✅
Hitting a usage/session limit ("You've hit your session limit · resets …") left
the mascot frozen on `thinking`. Root cause: stuck at `thinking` means
`UserPromptSubmit` was the **last** hook to fire — a real limit hit delivers **no
terminating hook** (no `Stop`, no `Notification`) to the widget, so the speculative
gravestone-on-`Notification` code (never verified live — see `docs/PLAN.md` line 209)
could not trigger.
- [x] `emit.py`: opt-in `_debug_log` (set `CLAUDE_MASCOT_DEBUG=1`) appends every
      hook event + key fields to `~/.claude/mascot/debug.log` — captures the **real**
      limit payload next time so the precise fix can be confirmed
- [x] `state_logic.py`: `_payload_text()` scans all string fields (not just
      `message`); usage-limit detection now also runs on `Stop` → tombstones if the
      limit text rides on it
- [x] `tkinter_app.py`: `THINKING_STALL_S` watchdog — after ~3 min stale on
      `thinking` with no new event, the display falls back to idle instead of
      appearing frozen (only `thinking`, never `working`, to avoid cutting long tools)
- [x] tests: Stop-with-limit-text tombstones; limit detected in non-`message` field
- **NEXT (needs user):** enable `CLAUDE_MASCOT_DEBUG=1`, reproduce a limit hit, and
  share `debug.log` so we can confirm exactly what (if anything) fires and finalize.

### Duplicate, overlapping cards — ✅
No single-instance guard, so a second `run_mascot.py` (e.g. autostart + a manual
launch, or the panel's "Launch widget" while one already ran) polled the same
state dir and drew a second, exactly-overlapping card for every session.
- [x] `mascot/single_instance.py` (NEW): named mutex (Windows) / `flock` (POSIX)
- [x] `tkinter_app.py`: `main()` acquires the guard; a second instance exits cleanly

### Shaking card drifts off-screen — ✅
The attention shake repositioned by deltas off `winfo_x()`, which lags a frame
behind a just-applied `geometry()` on Windows; the error compounded on every
shake reversal and slowly walked a frantic card clean off the screen.
- [x] `tkinter_app.py`: capture the rest position once when a shake begins, then
      set an absolute geometry of rest+offset every frame (no accumulated drift)

## Future / stretch

### 6. Tamagotchi mode — ⬜ FUTURE
Persistent leveling/evolving pet. Outline only for now.
- [ ] `~/.claude/mascot/pet.json` lifetime XP/level/stage (separate from session state)
- [ ] XP from lifetime activity; level curve; mood/energy decay over real time
- [ ] Evolution-stage sprite sets (baby/teen/adult) in the ASCII-grid format
- [ ] Level badge + XP bar on the card; evolution transition; optional needs
- Phasing: (a) persistence+XP, (b) level/badge UI, (c) evolution art, (d) mood/needs

---

## Validation
```bash
python -m pytest -q        # state_logic counters (#4) + existing suite
python demo.py             # visual: celebrate, blink, pet hearts, hover tooltip
python -m mascot           # live with a real Claude session; tray on Windows
```

## Notes
- `smooth` art lacks the new faces → falls back to `idle` (acceptable; can add later).
- Effective-state priority is the contract: `dizzy > happy > sleeping > raw`.
- Keep particle/blink work on the existing `_animate` loop — never thrash `_render`.
