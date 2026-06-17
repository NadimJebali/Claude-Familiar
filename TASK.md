# TASK.md — Mascot feature roadmap

Six features for the claude-mascot widget, ordered **easiest → hardest**.
Pure-stdlib Tkinter, no new dependencies. Keep the pure state machine
(`state_logic.py`) unit-tested; GUI is verified visually via `demo.py`.

Status legend: ⬜ todo · 🔄 in progress · ✅ done

---

## Grill-session decisions & plan — 2026-06-17

Outcome of a `/grill-me` design review of the in-flight work. **Supersedes** the
"NEXT (needs user)" step in the session-limit bug fix below, and **reverses** feature
#4 (stats tooltip → cut). Filed as GitHub issues #1 (PRD) and #2–#4 (slices).

### Status (2026-06-17)
- ✅ **#2 StopFailure detection** — implemented (TDD): `compute_next_state` branches on
  `error_type` (`_DEATH_ERROR_TYPES`), installer wires `StopFailure`, emit round-trips it.
- ✅ **#3 watchdog backstop** — implemented (TDD): `effective_state.compute` early-returns
  idle on a stall (never sleeping); `WORKING_STALL_S` raised to 270.
- ⏳ **#4 confirm error_type map (HITL)** — needs a real limit hit + `CLAUDE_MASCOT_DEBUG`.
- ⏳ **Stats-tooltip cut** & **home-monitor picker** — deferred: both touch GUI/Win32 that
  can't be verified headlessly; do them in a session where the app can be launched.

### Commit order (Q1)
Split the in-flight working tree: behavior-preserving **refactor first**, then one
commit per feature. Strip the cut stats tooltip *before* the refactor commit so dead
code never enters history.
1. `chore:` remove stats tooltip + counters (the cut from #4 below)
2. `refactor:` split `tkinter_app` → `manager` / `effective_state` / `popups` / `popup_place` / `scale`
   (multi-monitor popups + `waiting_angry` ride along — already built & tested)
3. `feat:` StopFailure limit detection (+ watchdog demotion)
4. `feat:` Windows "home monitor" picker

### Limit detection — StopFailure (Q2–Q4, Q6)
Replace the time-guess with the real terminating hook. Claude Code exposes
**`StopFailure`** (*"fires when a turn ends due to an API error"*) with a structured
`error_type` enum — verified **absent** from our installed hooks, which is *why* a
limit hit looked like "no terminating hook fired."

- **Prereq:** add `StopFailure` to `EVENTS` in `install_hooks.py` and re-run the
  installer — `CLAUDE_MASCOT_DEBUG=1` can't capture it until `emit.py` is invoked for it.
- **Wire-and-log together:** add a `StopFailure` branch to `compute_next_state`; keep
  `CLAUDE_MASCOT_DEBUG=1` on to capture the real payload + triangulate against
  `Stop`/`Notification`; finalize the map from the captured `debug.log`.
- **`error_type` map (provisional — confirm from `debug.log`):**
  - → `dead` (gravestone): `rate_limit` (all of them — revive-on-next-prompt undoes a
    false tombstone), `billing_error`, `authentication_failed`, `oauth_org_not_allowed`
  - → `idle` (turn just ended, *not* death): `overloaded`, `server_error`,
    `model_not_found`, `invalid_request`, `max_output_tokens`, `unknown`
- **Keep** the `Notification`/`Stop` `_payload_text` match as the **secondary** path — it
  supplies the "resets at 3pm" bubble that `StopFailure` (error_type only) lacks.
- **Watchdog → thin backstop:** raise `WORKING_STALL_S` → 270 (just under the 300s
  prune); keep the thinking stall. Make the watchdog **early-`return "idle"`** instead of
  mutate-`raw`-and-fall-through (a stalled busy state can otherwise reach `sleeping` via
  the idle overlay) + a pinning test. Note: any `StopFailure` now sets idle-or-dead
  immediately, so the watchdog is near-vestigial — kept only for a truly-no-hook wedge.

### Home monitor picker (Q7 = B) — NEW, Windows-only
Cards anchor to the *primary* monitor today; if your main display isn't primary they
spawn out of sight. Add a **deterministic** picker (no foreground-window heuristic):
- `EnumDisplayMonitors` (Win32) to enumerate displays + work areas
- `home_monitor` setting in `settings.py`; picker in `control_panel.py`
- `_place_initial` resolves the chosen monitor's work area instead of `primary_work_area()`
- Linux: degrades to current primary/screen behavior (matches tray/chroma being Win-only)

### Refactor (Q5)
Decomposition is **done as-is**; `MascotWindow` stays whole (under the 800-line ceiling;
the testability-driven extractions are already out).

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

### 4. Session stats on hover — ❌ CUT (2026-06-17, see Grill-session decisions)
**Reversed.** Hover-only on a 158px card is near-undiscoverable, and the per-session
counters don't fit Tamagotchi's *lifetime* need (YAGNI). Remove `StatsTooltip`, the
`TOOLTIP_*` constants, the `<Enter>`/`<Leave>` bindings + `_stats_text` plumbing, the
`prompts`/`tools_run`/`subagents_spawned` counters in `state_logic`, and their 7 tests.
The life-stats display returns with Tamagotchi (#6), driven by lifetime `pet.json`.
~~Counters live in the **pure, tested** state machine; tooltip mirrors `BubbleWindow`.~~
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
- **SUPERSEDED (2026-06-17):** the real fix is the `StopFailure` hook — see
  "Limit detection — StopFailure" under Grill-session decisions above. The reason this
  looked like "no terminating hook fired" is that `StopFailure` was never installed.

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
- [ ] **Life-stats display** — revives the cut hover-tooltip pattern (#4), but driven by
      **lifetime** `pet.json` counters (age, XP, prompts/tools/agents over the pet's life)
      rather than the per-session counters we removed
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
