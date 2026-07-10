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
- ✅ **Home-monitor picker** (#7, 348b59e) — pure `osplatform.choose_work_area` (TDD, 5 cases)
  + Win32 `enumerate_work_areas`, `home_monitor` setting wired through config + `_place_initial`,
  and a Display picker on the panel. Verified live against the real dual-monitor layout.
- ✅ **Stats-tooltip cut** (#6, 1ff5368) — `StatsTooltip` + counters + their tests removed;
  no dangling refs; suite green; `MascotWindow` constructs/animates/drags/closes cleanly.

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

### 6. Tamagotchi mode — 🔄 IN PROGRESS (PRD #8)
Persistent virtual-pet layer on the mascot: **coins** earned from Claude activity
(daily-capped), a **shop** for food/toys, three gentle **needs** (hunger/happiness/
energy), a **mood** shown on the idle face, **XP/levels**, and **egg→baby→teen→
adult** evolution. **One global pet** shared across every session card; a delight,
never an obligation (no sickness/death — the gravestone stays for usage limits).
Filed as PRD #8 with four phased issues:
- ✅ **#9 pet engine + persistence (pure core)** — see decision log below
- ✅ **#10 Pet window + shop + feed/play** — see decision log below
- ✅ **#11 status tooltip + idle-face mood** — see decision log below
- 🔄 **#12 evolution stages + per-stage art** — mechanism + scaling + flourish done
  & tested; the per-stage **art is in HITL review** (drafts authored)

#### #9 — pet engine + persistence (done, TDD)
- **`mascot/pet_logic.py`** — the pure core (clock-free, I/O-free, immutable;
  mirrors `state_logic`/`effective_state`/`osplatform`): `decay` (hunger/happiness
  drift down; energy **drains while working, refills while idle**; clamped 0..100;
  negative-elapsed-safe), `apply_effects` (stat→delta map, clamped, negative-safe,
  **needs-only** so an item can never grant power), `award` (coins daily-capped +
  date reset; **XP uncapped**), `events_for_transition` + `apply_events` +
  `EVENT_REWARDS` (`working`/`thinking`→`idle` = a completed turn; a vanished
  sub-agent badge = a finished sub-agent), `mood`, `level_for_xp`, `(level,age)→
  stage`.
- **`mascot/pet_store.py`** — the thin I/O wrapper (mirrors `hooks/emit.py`) owning
  `~/.claude/mascot/pet.json`: `default_pet`, atomic `save`, and `load` with
  **decay-on-load** via a `last_seen` stamp (missing/corrupt → fresh default;
  unknown keys back-filled for forward-compat; `born` preserved across restarts).
- **`mascot/manager.py`** is the **sole writer**: each 500ms poll it decays the pet
  (working = any session busy) and awards coins/XP from polled session-state
  transitions, persisting throttled (an award forces a flush; a flush also runs on
  exit). **No change to `hooks/emit.py`** — earning is derived widget-side, so the
  hook emitter stays fast and there are no cross-process races on the file.
- **Decisions:** coins are daily-capped (200/day, global) but **XP is not** — the
  evolution **age-gate** (`(level,age)→stage`), not an XP cap, is what stops
  grinding stages, so the cap matches the PRD's "never pays to over-use" without
  freezing progression. Stats bottom out at 0 (droopy/sleepy), never sickness or
  death. Decay rates / coin amounts / level & stage curves are a **tuning pass**,
  so the tests assert **direction / clamping / monotonicity**, not magnitudes.
- **Tests:** 57 new cases in `tests/test_phase1.py` (synthetic inputs, same style
  as the existing pure cores + the emit round-trip). The GUI (Pet window, tooltip,
  idle-face mood, evolution art) arrives in #10–#12 and is verified visually per
  convention.

#### Card-lifetime fix (fb85fbf) — sleep = energy recovery, not a timeout
Card pruning was `is_stale OR is_owner_dead`; the heartbeat only ticks on hook
events, so an idle→sleeping-but-live session was timed out at `STALE_TIMEOUT_S`
(300s). That fought the energy-recovery model (sleep refills energy, US10/US28), so
`state_store.is_session_live()` now keeps a card while its owning `claude` process
is alive (pruning only on confirmed owner death or `SessionEnd`); the staleness
timeout survives only as a backstop for sessions with no trackable owner PID. The
`effective_state` stall watchdog (`WORKING_STALL_S`/`THINKING_STALL_S`) is
unaffected — it governs the *face*, not card removal. +2 tests.

#### #10 — Pet window + shop + feed/play (done, TDD core + GUI)
- **`mascot/shop.py`** (pure, tested): a **data-driven `CATALOG`** (food + toys,
  trade-off items, level gates) and pure ops reusing `pet_logic.apply_effects`:
  `can_buy`/`buy` (spend coins, +inventory), `can_feed`/`feed` (consume one, apply
  effects, +care XP), `cooldown_remaining`/`can_play`/`play` (reusable toy on a
  cooldown, +care XP). Validation is split into `can_*` (-> `(ok, reason)`) from the
  transforms, which assume the precondition and stay immutable.
- **`mascot/pet_window.py`** (GUI): the dashboard — pet sprite, three need bars,
  coins, name, level, inventory, and a Shop/Items tabbed view with Buy/Feed/Play
  and a rename box. Feeding/playing/tapping reuse the **happy face + pixel hearts**.
  Persistence is abstracted behind `load_pet`/`save_pet` callbacks so the same
  window runs **in-process** (tray, sharing the manager's live pet) or
  **standalone** (`python -m mascot.pet_window`, from Settings, read-modify-write
  via `pet_store`).
- **Single-writer across two entry points:** the **tray** opens the window in the
  manager process (no race). The **Settings** button launches it as its own process
  (Linux/no-tray); it read-modify-writes per action, and the **manager reloads
  `pet.json` when its mtime changes externally**, so the two stay in sync without
  IPC. The hooks still never touch `pet.json`. Wired: `tray.py` (+"Pet…" item),
  `manager.py` (open/focus + external reload + `_celebrate_cards`),
  `control_panel.py` (+"🐾 Pet" button), `MascotWindow.celebrate()`.
- **`cooldowns: {}`** added to `default_pet` (forward-compatible via decay-on-load's
  key back-fill). **Tests:** +18 shop cases. GUI verified by construct->act->destroy
  smoke tests (Pet window actions; manager external-reload + in-process buy) — a
  full visual review still wants a live launch.

#### #11 — status tooltip + idle-face mood (done, TDD seam + GUI)
- **Idle-face mood (pure, tested):** `effective_state.compute` gained a `mood` arg
  and a `_MOOD_IDLE_FACE` map. The mood face is returned **only** in the `raw ==
  "idle"` branch, *below* the sleep/blink checks — so dozing/blinking outrank it and
  **Claude-activity states (working/thinking/waiting/dead) structurally always win**
  (they never reach the idle branch). Default `mood="content"` keeps old callers on
  plain idle. +4 tests at the seam.
- **Faces + wiring (GUI):** four idle-mood faces in `sprite_pixel`
  (`idle_happy`/`idle_hungry`/`idle_sad`/`idle_tired`; smooth art falls back to
  idle), `STATE_CAPTIONS` maps them all to "idle", and `config.STATE_COLORS` tints
  them (happy = pink sparkle, the rest stay calm idle grey). The card derives mood
  from the pet via `pet_logic.mood` in `_compute_effective_state`; the **manager
  pushes the one global pet to every card** each poll (`MascotWindow.set_pet`).
- **Hover tooltip revived (`popups.StatsTooltip`):** a frameless Toplevel showing
  name, level, coins, and three need bars, driven by the pet, placed with the tested
  `popup_place.beside` (multi-monitor safe). Shown on `<Enter>`, hidden on `<Leave>`
  / drag / card-hide, follows the card (incl. shake) in `_animate`. Need-bar colors
  are shared via `config.NEED_COLORS` (also used by the Pet window). GUI verified via
  a construct→hover→leave→close smoke test.

#### #12 — evolution stages + per-stage body art (mechanism done; art HITL)
- **Composition (tested):** `sprite_pixel` now keys the body by stage — `_BODIES`
  (baby/teen/adult, each 6 top + 5 bottom rows) plus a faceless 16-row `_EGG` —
  and `grid_for(stage, state)` composes `body[stage] + face[state]` (the egg
  ignores the face). Every existing face is reused at every stage; unknown
  stage→baby, unknown face→idle, all validated at import. +4 composition tests.
- **Growth + flourish:** `STAGE_SCALE` grows the creature per stage; `draw_creature`
  gained `stage`/`flourish` args (a milestone sparkle drawn at `MILESTONE_LEVEL`,
  10). The card derives stage from the pet (`level_for_xp` + age via
  `stage_for`), threads it through `_draw_creature` and the render signature (so a
  stage change repaints even when the face doesn't), and the Pet window renders the
  pet at its stage too. `icon.py` updated to the new `grid_for` API.
- **Egg → baby on first level-up** falls out of `stage_for` (#9): level 1 = egg,
  level 2 = baby, no extra logic. Smooth art has no stages (single blob), matching
  how it already lacks the per-state faces.
- **HITL:** the per-stage grids are **first-draft art**; they render correctly
  (verified across egg/baby/teen/adult via a smoke test) but want a visual pass —
  iterate the ASCII grids in `sprite_pixel._BODIES` / `_EGG`. Issue #12 stays open
  for that review.

#### Mood polish (follow-up): emote popups + hungry eyes
- `idle_hungry` eyes gained white-flanked pupils (they read as eyes, not black dots).
- **Mood emotes:** a little food apple pops up above the creature every few seconds
  while hungry (`idle_hungry`), and a drifting "Z" while sleepy/tired
  (`idle_tired`/`sleeping`) — `sprite_pixel.draw_food`/`draw_zzz`, spawned + risen +
  faded on the card's existing particle clock (like the hearts), keyed off the
  effective state so they only show in the matching mood.
- Confirmed: moods **and** reactions (mood faces, happy/celebrate, hearts, emotes)
  compose over **every** stage (baby/teen/adult); only the **egg** is faceless.

#### Polish round 2: dino egg, on-card Pet button, shop item art
- **Dino egg:** bigger 2×2 speckles in `_EGG`, painted a steady grey
  (`EGG_SPECKLE`) instead of the state accent — a fresh pet's mood is *happy*, which
  would otherwise tint the spots pink. `draw_creature` special-cases the egg's `a`.
- **On-card Pet button:** a small "🐾" `tk.Button` (top-left of each card, a child of
  the toplevel so it survives canvas redraws) opens the Pet window via a new
  `MascotWindow(on_open_pet=…)` callback → `manager._open_pet_window`.
- **Shop item art:** new `mascot/item_art.py` — a 12×12 pixel grid per catalog item
  (cookie / bowl / energy can / roast / ball / puzzle cube) with a shared `PALETTE`,
  validated at import. The Pet window shop + inventory rows now show the rendered
  icon instead of an emoji. +1 test (every catalog item has valid art). Art is
  draft-quality, easy to iterate in `item_art._ITEMS`. (Feast redrawn as a roast
  turkey with two drumstick legs for clarity.)

#### Polish round 3: reset progress + petting trickle wired
- **Reset progress** (Settings → Setup tab): `control_panel._reset_pet` overwrites
  `pet.json` with a fresh `default_pet` (egg, 0 coins/XP, full needs, no items/name)
  after a confirm dialog. A running widget picks it up via its external-change
  reload — Settings is a deliberate out-of-band reset, the widget stays the writer.
- **Petting trickle wired** (the `pet` coin source from the engine, previously
  defined but unwired): tapping a **card** (`MascotWindow(on_pet=…)` →
  `manager._on_pet_petted`) and tapping the pet in the **Pet window** (`_pet_tap`)
  now award the daily-capped `EVENT_REWARDS["pet"]` (+1 coin/+1 XP) on top of the
  happy reaction. Earning sources now live: completed turn (+5), sub-agent finish
  (+3), petting (+1) — all under the 200/day cap.
- **First-prompt streak wired** (the last earning source): `pet_logic.started_prompt`
  (pure, tested) detects a session entering `thinking`; the widget claims a
  once-per-day bonus (`FIRST_PROMPT_OF_DAY`, +20), persisted via a new
  `last_prompt_date` field on the pet. **All four PRD coin sources (user story 4)
  are now live:** completed turn, sub-agent finish, daily first-prompt streak, and
  petting — under the 200/day cap.

#### Polish round 4: pixel-art UI icons + Pet-window glitch fix
- **Pet-window resize glitch fixed:** the window now pins its geometry after the
  initial build, so rebuilding the shop/inventory lists (which briefly empties their
  frames) on a click no longer makes the window shrink-and-grow.
- **On-card paw button** is bigger and now a **pixel-art paw** image (not a glyph).
- **Every GUI emoji replaced with pixel art** via a new `mascot/ui_icons.py`
  (paw / coin / check, rendered to `tk.PhotoImage`): the 🐾 in the card button, the
  Pet-window header, and the control-panel header + "Pet" button; the 🪙 coins in
  the Pet window; and the ✓ in the control-panel status labels.

#### Polish round 5: live toy cooldown, one-time toys, bar-label clip fix
- **Toy cooldown now counts down live.** It was static because the Items list only
  rebuilds on a coins/level/inventory change; the cooldown's "can play" boolean
  stays false the whole time, so the "Resting (Xs)" text never re-rendered. Now each
  toy keeps a persistent Play button + countdown label, updated every tick by
  `_update_cooldowns` (no list rebuild), so it ticks down and re-enables at 0.
- **Reusable toys are one-time purchases.** `shop.can_buy` now rejects a toy already
  owned ("Already owned"); food still stacks. The shop shows owned toys as a disabled
  "Owned" button, and the Items tab drops the `×count` for toys. +2 tests.
- **Hunger bar label no longer clipped.** The first need label was anchored
  south-west at y≈4, so its top fell above the canvas edge. Bars now lay out per a
  `BAR_SLOT` with the label anchored north-west at each slot's top (fully inside).

#### Disable-pet toggle + upper-right popups — ✅ (PRD #21, 2026-06-18, `/grill-me`)
A `tamagotchi_enabled` setting (default **True**) lets the card become a **simple hook
visualiser** — the same live state faces + sub-agent badges, with the whole pet layer
stripped. The disable is a **manager-level "don't wire the pet" gate**, not a
per-feature kill switch:
- **`settings.py`/`config.py`:** new `tamagotchi_enabled` default + `TAMAGOTCHI_ENABLED`
  flag (bool, read once at startup → restart-gated like the other settings).
- **`manager.py`:** in simple mode the pet is **never loaded, ticked, pushed, or
  saved** (`pet.json` is left untouched, so the next enable applies decay-on-load from
  the real `last_seen` — the off period counts as idle); cards are built with
  `on_open_pet`/`on_pet=None` + `pet_enabled=False`; the tray is built with
  `on_pet=None`.
- **`tkinter_app.py`:** `MascotWindow(pet_enabled=…)` gates the hover tooltip and makes
  a tap a **dead tap** (no hearts/coins). The mood-tinted idle faces + food/tired
  emotes fall out for free (the manager never pushes a mood → `effective_state` stays
  `content` → plain idle); the real-`sleeping` 💤 is unaffected (hook-driven).
- **`tray.py`:** `_build_menu` now drops any row whose action key has no callback, and
  `SystemTray` only registers provided callbacks — so omitting `on_pet` hides "Pet…"
  **without changing `MENU_SPEC`**. +1 test (`test_tray.py`).
- **`control_panel.py`:** a checkbox on the Behavior tab; it live-greys the footer
  "Pet" button + the "Reset progress" button when off (progress preserved), and the
  flag persists on Save & Apply.
- **Popups repositioned:** food, 💤, and the petting/feed **heart burst** now spawn at
  the creature's **upper-right** (right of, and above, center), drifting up-and-right
  into empty panel space — clearing the top-left paw button — and the food/💤 emote
  cell size is bumped `_s(2)`→`_s(3)` for legibility. Offsets use the `scale._s`
  primitive, so they scale with small/medium/large. (Requested "upper-left" → chosen
  **upper-right** because the paw button owns the top-left corner in pet mode.)
- **Decisions:** default ON (existing experience unchanged); simple mode is "the card
  minus the pet", not a redesigned layout; toggle is restart-gated; `demo.py` left
  as-is (still showcases the full pet). GUI verified via `demo.py` + a live off-mode run.

---

## Live Claude status on the card — effort background + usage bars (PRD #44) — 🔄 2026-07-09
Two live Claude signals the card didn't carry: the **reasoning effort** and the
**5h/weekly usage limits**. Both use Claude Code's own colors (extracted from the
2.1.205 binary, so the card matches the CLI). Filed as PRD #44 with five slices
(#45, #48, #46, #47 AFK + #49 HITL). Design locked in a `/grill-me` session (8
decisions + 6 derived).

### #45 — effort capture end-to-end + static tints (done, TDD)
- **`hooks/emit.py`** stamps an `effort` field from the **`CLAUDE_EFFORT`** env var
  Claude Code exposes to hook commands (per-turn accurate, after any silent model
  downgrade; identical on CLI + VSCode extension). Non-empty-only, so a missing var
  never erases the last level. `state_logic.default_state` documents `effort: ""`;
  the dict-copy carries it across transitions untouched. **No new hooks** — existing
  installs pick it up on the next event.
- **`mascot/effort.py`** (PURE, tested): `normalize` (case/space, `ultracode→xhigh`,
  `auto`/unknown→`""`), `resolve` precedence (state effort → global `effortLevel`
  fallback via an mtime-cached reader), the CLI palette (`TINTS`), `blend`, and
  `panel_fill` (unknown → `None` = today's exact look).
- **Card:** panel tinted per level; the gravestone suppresses the tint; the paw
  button follows the panel; `effort` joins the render signature (a level change
  repaints once). Verified live: this VSCode session's state file gained
  `effort: "xhigh"` on the next hook event.

### #48 — animated backgrounds: xhigh wave + max rainbow (done, TDD)
- **`effort.py`** animation math (clock passed in): `wave_color(t)` sweeps the
  shimmer purple gradient (`WAVE_LO↔WAVE_HI`, ~2.4s); `rainbow_color(t)` cycles the
  7-color rainbow ring (~6s, wrapping); `effort_color` routes xhigh→wave / max→
  rainbow / quiet→static; `border_accent` gives the two animated levels a moving
  border.
- **Card:** panel fill (+ border) restyled **in place on the existing 25fps clock**
  — never a full redraw, no new timers. Precedence: the waiting attention pulse
  always wins the border; the gravestone shows no effort background.

### #46 — statusline emitter + installer + footer (done, TDD)
- **`mascot/statusline.py`** (PURE): `snapshot_from_status` distills the `five_hour`
  + `seven_day` windows and effort from Claude's statusline JSON (tolerant of
  absent/malformed blocks); `footer_line` formats `model · effort · 5h% · wk% · dir`
  with the effort ANSI-tinted in its palette color.
- **`hooks/status_emit.py`** — thin always-exit-0 shell (mirrors `emit.py`): reads
  the statusline JSON on stdin, atomically writes the account-global
  `~/.claude/mascot/usage.json` (reusing emit's hardened writer), prints the footer.
  **Never clobbers a good snapshot** on malformed/empty input. This is a **second,
  independent writer** — one global file, last-writer-wins (limits are account-wide)
  — so it never races the per-session state files.
- **`scripts/install_hooks.py`** — `install_statusline`/`uninstall_statusline` pure
  transforms + wiring: install into a **free** slot, refresh our own, and **skip +
  warn** on a foreign `statusLine` (never clobber the user's); uninstall removes only
  ours. Verified live against a temp HOME (install/refresh/skip/uninstall).

### #47 — 5h/weekly usage bars on the card (done, TDD)
- **`mascot/usage.py`** (PURE): `usage_view(snapshot, now)` → ordered 5h/7d bars
  with **reset decay** (a window past its `resets_at` reads 0 — no staleness timers);
  `bar_color` = traffic-light thresholds (calm <70, warning amber ≥70, error red ≥90
  — the CLI's own 0.9 alarm); `load_usage` mtime-cached reader.
- **Card + manager:** the card grows `USAGE_ROW_H` for one bottom row of two labeled
  bars (**nothing above it moves**); shown in simple mode + on the gravestone; empty
  when there's no data. The manager pushes the snapshot to every card each poll
  (like the pet push), independent of the pet toggle.

### #49 — HITL: verification gates, tuning, docs (🔄 in progress)
- **Gate 1 (effort stamp):** ✅ confirmed on the **VSCode-extension** path (live state
  file carries `effort`). ⏳ CLI path is by the identical mechanism (same emit.py,
  same `CLAUDE_EFFORT`) — wants a real CLI-session confirmation.
- **Gate 2 (statusline in VSCode):** ⏳ needs the statusline installed into the real
  `~/.claude/settings.json` + one VSCode session to observe whether the extension
  runs the command. Accepted fallback (grill decision): last-known usage from CLI
  sessions with reset decay. **Outcome to be recorded in the README.**
- **Visual tuning pass:** ⏳ tint strengths (`_BLEND_STRENGTH` 0.18/0.32), wave/rainbow
  periods, and bar legibility at small/medium/large are first-pass magnitudes — tests
  assert shape/invariants, not values (like the pet-balance numbers). Wants a live
  `demo.py` review.
- **Docs:** README (feature bullets, statusline install/skip/uninstall, freshness
  note) + this entry — done.
- **Tests:** +60 across `test_effort.py` / `test_statusline.py` / `test_usage.py`
  (normalize/resolve/blend, wave/rainbow invariants, snapshot extraction + footer +
  installer transforms + subprocess round-trip, decay + thresholds + loader cache).
  Suite 378 → 440 green; ruff + mypy clean (new code). No new runtime deps (ADR-0001).

---

## Considered & rejected

### Real-.exe packaging for a Task Manager identity — 2026-06-17
Goal: make Task Manager show "Claude Familiar" + the mascot image instead of
`pythonw.exe` + the Python icon. **Rejected** — the process name can only change by
shipping a real executable, and every route is a bad fit:
- **PyInstaller** does it cleanly but adds a build-time dependency + a ~10–25 MB
  artifact, against the pure-stdlib / run-from-source ethos.
- The dependency-free hack (copy `pythonw.exe` → `Claude Familiar.exe`, inject the
  icon/version via the Win32 resource API) is too fragile: the copy can't locate
  `python3X.dll` outside the Python dir, and a renamed interpreter trips antivirus.

Decision: accept the `pythonw` process name. The taskbar/window icon is already the
mascot (`iconphoto`), and `install.py` + the tray + shortcuts already deliver the
"real installed app" feel. (A pure-stdlib `SetCurrentProcessExplicitAppUserModelID`
taskbar-grouping polish was also on the table, but skipped.) Don't re-open without a
new reason.

---

## Validation
```bash
pip install -r requirements-dev.txt  # pytest + hypothesis + ruff (dev-only, #13/#14)
python -m pytest -q        # state_logic counters (#4) + pet engine + property tests
python -m ruff check .     # lint (#14)
python demo.py             # visual: celebrate, blink, pet hearts, hover tooltip
python -m mascot           # live with a real Claude session; tray (Win/Linux/macOS)
```

### #13 — Hypothesis property-based tests (done)
Added `hypothesis` as a **dev-only** dependency (`requirements-dev.txt`; never
imported by `mascot/`/`hooks/`, which stay pure-stdlib) and `tests/test_properties.py`
— 9 property tests that fuzz the pure cores' invariants alongside the example-based
cases: `decay`/`apply_effects` clamping + immutability over negative/huge elapsed and
negative deltas (needs-only, never grants coins/XP), `award`/`apply_events` daily coin
cap + coins-only-increase + uncapped XP, `level_for_xp` monotonicity, `stage_for`
non-regression, and `shop.buy`/`feed`/`play` immutability + inventory/cooldown
consistency. Suite: 155 → 164 green. (A mutation check — disabling `_clamp_stat` —
confirmed the clamping properties are non-vacuous.)

### #14 — Ruff lint config + fixes (done)
Added `ruff` as a **dev-only** dependency and `ruff.toml` (line-length 99,
`target-version py311`). `ruff check .` now passes clean across `mascot/`/`hooks/`/
`scripts/`/`tests/`. Rule selection is deliberate:
- **Selected:** E, F, W, I, UP, B, C4, BLE, RUF — real bugs + cleanup. Fixed the
  findings: sorted imports, removed unused imports, wrapped 28 over-length lines,
  modernized a `%`-format/`int(round())`/`dict()`/concat, and annotated 11 more
  blind-`except` sites with `# noqa: BLE001 — reason` (matching the author's
  existing convention).
- **Excluded with rationale (style, not bugs):** `PLC0415` (the codebase imports the
  pure cores lazily inside functions, and every test imports its module locally —
  ~116 intentional sites), `SIM` (SIM105 would rewrite the explicit commented
  `try/except`; SIM115 flags the intentionally long-lived lock-file handle in
  `single_instance`), and `RUF001` (the UI deliberately uses the `×` glyph).
- **Format:** `ruff format` is *not* run as a bulk pass — the source is hand-aligned
  (dict literals, sprite grids, comment columns); `ruff check` is the enforced gate.
No behavior change (verified: `.format`/`%` byte-identical, `round`==`int(round)`);
suite stays 164 green.

### #16 — ADR: allow required runtime dependencies (decided)
**Reverses the pure-stdlib stance.** Recorded as
[ADR-0001](docs/adr/0001-runtime-dependencies.md) (the project's first ADR; new
`docs/adr/` dir). Third-party packages may now live in `requirements.txt` and be
imported by the widget where they replace fragile hand-rolled `ctypes` or extend
platform support; OS-specific deps are gated by environment markers
(`pywin32; sys_platform == "win32"`). README "no external dependencies" claim +
`requirements.txt` header updated; dev tools stay in `requirements-dev.txt`. This
**unblocks #17–#20** — but the ADR only *permits* deps; each issue is still judged
on whether the dependency earns its cost over the working hand-rolled code. (The
PyInstaller rejection stands on its own merits and is not reopened.)

### #18 — cross-platform system tray via pystray (done, first dep under ADR-0001)
Replaced the Windows-only Win32-`ctypes` tray with a single **pystray**-backed path
that works on Windows/Linux/macOS (first runtime dep landed under [ADR-0001](docs/adr/0001-runtime-dependencies.md);
`pystray`+`Pillow` added to `requirements.txt`).
- **Threading:** pystray runs the tray on its own thread, so menu callbacks fire
  off the Tk thread. They're marshaled back: the pystray thread only *enqueues*
  onto a thread-safe `_TkDispatcher`, and an 80ms `root.after` pump (scheduled on
  the Tk thread) drains it — so the manager's callbacks still run on the Tk thread
  and may touch Tk safely, exactly as the old ctypes tray did. Verified live on
  Windows (a simulated click ran the callback on `MainThread`).
- **Menu unchanged:** Pet… / Show / hide cards / Settings… / Quit; the toggle is the
  pystray `default` item, so a left-click still shows/hides cards on Windows (on
  Linux it's a normal menu entry — degrades gracefully).
- **Manager:** dropped the `osplatform.IS_WINDOWS` gate; tray construction stays
  best-effort (missing deps / no tray host → widget runs without an icon). `tray.py`
  keeps pystray/Pillow **lazy** so the module + its pure logic import without the deps.
- **Tests:** +10 in `tests/test_tray.py` (menu model, `_run_guarded`, `_TkDispatcher`
  order/error-guard, handler→dispatch routing; the live-`Menu` build skips if pystray
  is absent). Suite 164 → 174 green.

### #19 — native OS notifications via plyer (done)
A native OS toast now fires **alongside** the in-app speech bubble whenever a
session's `notify` (permission/attention or a usage/session limit) first appears —
so you notice even with the card off-screen (`plyer` added to `requirements.txt`).
- **New `mascot/notifier.py`** — pure core + thin shell, mirroring the other cores:
  `fresh_notifications(prev, next)` is **edge-triggered** (a notify persists across
  the 500ms polls, so it toasts once, not every poll; clears-then-returns or a
  changed message re-fires), `toast_for(notify)` formats the title (usage-limit vs
  permission vs generic attention) + message, and `emit(notify, show=…)` routes to
  `notify_native`, which runs `plyer` on a **daemon thread** so a toast never blocks
  Tk and is best-effort (missing dep / no notifier daemon → silent no-op).
- **Manager:** a best-effort `_notify_sessions(states)` step each poll, with its own
  `_notify_prev` edge tracker (parallel to the pet's `_pet_prev`). The bubble is
  untouched — this only adds. Verified live on Windows (a real toast fired) + an
  edge-trigger glue check (2 toasts across appear/repeat/clear/re-ask).
- **Tests:** +14 in `tests/test_notifier.py` (edge cases + formatting + `emit`
  routing via an injected `show`). Suite 174 → 188 green.

### #17 — psutil process detection + liveness (done)
Replaced the hand-rolled process code with **psutil** (added to `requirements.txt`):
`hooks/proc.py` dropped the Win32 Toolhelp snapshot + `/proc/<pid>/stat` parsing for
a psutil ancestor walk (`find_owner_pid`), and `mascot/proc.py` dropped the
kernel32/`os.kill` liveness for `psutil.pid_exists` (`pid_alive`). Public signatures
+ semantics unchanged: `find_owner_pid()` still returns the nearest Claude-ancestor
PID or None; `pid_alive()` still returns True on any uncertainty so a session is
never wrongly pruned. **psutil is imported lazily** inside both functions (so
`emit`'s top-level `from proc import …` can't crash if psutil is missing — it
degrades to "owner unknown" / "keep") — important because the hook runs in whatever
Python Claude Code invokes. Tests adapted: the `/proc`-parse + Linux-matcher cases
became a cross-platform `_is_owner_name` test + a `find_owner_pid` no-crash smoke;
`pid_alive` self/None/garbage test unchanged. Verified live: `find_owner_pid()`
returned a real PID when run under Claude Code. Suite stays 188 green.

### #20 — pywin32 for Windows shortcut creation (done)
Replaced the fragile **PowerShell-subprocess** `.lnk` creation in `shortcuts.py`
(`create_shortcut` built a PS command by string-interpolating paths — broke on
quotes/special chars, and spawned `powershell` each time) with **pywin32**'s
`WScript.Shell` COM (`win32com.client.Dispatch`). Same shortcut fields
(Target/Arguments/WorkingDirectory/Icon/Description/minimized WindowStyle), no
subprocess, no string injection. `pywin32; sys_platform == "win32"` added to
`requirements.txt`; imported **lazily** inside `create_shortcut` so `shortcuts.py`
still imports on Linux (its `.desktop` path is untouched). Dropped the now-unused
`subprocess` import. **Tests:** new `tests/test_shortcuts.py` — a real .lnk
round-trip (create → read back Target/Arguments/WorkingDirectory via the same COM
object) + `remove_shortcut` present/absent; all Windows + pywin32 gated (skip
elsewhere). Suite 188 → 191 green.

### #15 — static type-check pass with mypy (done)
Added **mypy** as a dev-only tool (`mypy.ini`; `mypy>=1.8` in `requirements-dev.txt`)
and made `python -m mypy mascot hooks` pass clean (33 files, 0 errors) at a pragmatic
baseline (not full `--strict`). The 19 initial findings were fixed honestly, not
blanket-ignored:
- **Real fixes:** annotated `manager._pet_win` (`PetWindow | None` via a
  `TYPE_CHECKING` import) and `single_instance._fd` (`TextIO | None`); narrowed
  Optionals in `tkinter_app._pet_flourish` / `_apply_attention_shake`; asserted the
  non-separator invariant in `tray._build_menu`; swapped three loop-capture lambdas
  in `pet_window` for `functools.partial` (also clearer); passed the 3-point
  `create_line` coords as a list (matches the tk stub overload); corrected a stale
  `# type: ignore[attr-defined]` → `[union-attr]` in `icon`.
- **Justified ignores:** `ignore_missing_imports` per-module for the stub-less deps
  (pystray/plyer/psutil/win32com); a single `# type: ignore[attr-defined]` on the
  POSIX-only `fcntl.flock` (with a per-module `warn_unused_ignores = False`, since
  that ignore is used on Windows but redundant on Linux — `single_instance` uses
  platform-only APIs on both sides).
No runtime behavior change (lambdas→partial and coords-as-list are equivalent);
suite stays 191 green, ruff clean.

## Notes
- `smooth` art lacks the new faces → falls back to `idle` (acceptable; can add later).
- Effective-state priority is the contract: `dizzy > happy > sleeping > raw`.
- Keep particle/blink work on the existing `_animate` loop — never thrash `_render`.
