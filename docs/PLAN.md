# Claude Code Mascot Widget — Implementation Plan & Reference

> Reference doc for future sessions. Read this first before resuming work.
> **Status tracker is at the bottom — update it as phases complete.**

## What we're building
A PyQt6 desktop widget for **Windows** that floats a mascot on screen and changes
its state to reflect what Claude Code is doing live, driven by Claude Code's
**hooks** system. One mascot **per Claude session**. Sub-agents (spawned via the
`Task` tool) appear as small sprites underneath the mascot.

## Locked decisions
| Decision | Choice |
|---|---|
| GUI stack | **Tkinter** — built-in, native windows, simple, reliable, no external dependencies |
| Multi-session | **One window per session** (multiple sessions = multiple windows stacked, labeled by cwd) |
| Scope (v1) | Core states + multi-session |
| Core states | `idle / thinking / working / waiting / sleeping` + sub-agent badges |
| Transport | Per-session JSON file in `~/.claude/mascot/state/`, polled every 500ms |
| Art | **Emoji + badges** (simple, clear, no asset generation needed); upgrade to custom art later if desired |
| Animation | None (static display); add animations later if desired |
| Location | `C:\Users\Vinny\Desktop\claude-mascot\` |

## Architecture (3 decoupled parts)
```
Claude Code session ──hooks──▶ emit.py ──atomic write──▶ ~/.claude/mascot/state/<session_id>.json
                                                                  │ (one file per session)
                                                                  ▼ Tkinter polls every 500ms
                                                  One window per session
                                                  (native, frameless, always-on-top, draggable)
```
- **emit.py** is invoked by every hook. It reads the event name (argv) + the hook
  JSON payload (stdin), updates that session's state file with an atomic
  `os.replace`, and **always exits 0** — it must never block or break Claude, even
  if the widget isn't running.
- The **Tkinter manager** polls `state_store.load_states()` every 500ms and creates/destroys
  one native window per active session. If emit.py or Claude isn't running, no windows appear.

## State derivation (hook → state) — VERIFIED against real payloads (Phase 0)
| Hook event | Match | Effect |
|---|---|---|
| `SessionStart` | — | create file, `state=idle`, record `cwd` + `model` |
| `UserPromptSubmit` | — | `state=thinking` |
| `PreToolUse` | `tool_name=="Agent"` AND no top-level `agent_id` | push sub-agent keyed by `tool_use_id`, `state=working` |
| `PreToolUse` | other tools | `state=working`, record `tool` (= `tool_name`) |
| `PostToolUse` | `tool_name=="Agent"` | pop sub-agent matching `tool_use_id` |
| `Notification` | — | `state=waiting` (`notification_type`/`message` say why) |
| `Stop` | — | `state=idle`, clear sub-agents |
| `SubagentStop` | — | **no-op for sprites** (heartbeat only) |
| `SessionEnd` | — | delete state file |

### Phase 0 verified facts (DO NOT re-guess these)
- **Sub-agent tool is `Agent`, not `Task`.** `tool_input = {description, prompt}`; `subagent_type` is present only when explicitly set. Resolved type is in `PostToolUse.tool_response.agentType`.
- **`SubagentStop` is noisy** — fires for internal/background harness agents (`agent_type: ""`) unrelated to user spawns. Do NOT pop sprites on it. Pop on `PostToolUse(Agent)` keyed by `tool_use_id`; clear stragglers on `Stop`.
- **Nested tool calls** (tools run *inside* a sub-agent) carry top-level `agent_id` + `agent_type`; top-level `Agent` spawn does not. That's how to distinguish a spawn from nested activity.
- Common fields on every event: `session_id`, `cwd`, `hook_event_name`, `transcript_path` (+ usually `permission_mode`).
- `Notification` → `{message, notification_type}` (saw `idle_prompt`). `SessionEnd` → `{reason}`. `SessionStart` → `{source, model}`.
- GateGuard fact-forcing comes from the **ecc plugin**, not settings.json hooks. Disable via `ECC_DISABLED_HOOKS=pre:edit-write:gateguard-fact-force` (env), not a settings hook entry.

- **sleeping** is widget-side: after N seconds in `idle` with no change, swap to the
  sleeping sprite. No hook needed.
- Core logic lives in a **pure function** `compute_next_state(current, event, payload) -> new_state`
  in `hooks/state_logic.py` — this is the main unit-tested surface.

## Session state file schema
`~/.claude/mascot/state/<session_id>.json`
```json
{
  "session_id": "abc123",
  "cwd": "C:\\Users\\Vinny\\Desktop\\some-project",
  "state": "working",
  "tool": "Edit",
  "subagents": [{ "type": "code-reviewer", "id": "..." }],
  "ts": 1718000000.0
}
```
- `ts` = heartbeat (epoch seconds), written on every update. Widget prunes a
  mascot if `ts` is older than the staleness timeout (default 300s) — crash safety
  net in case `SessionEnd` never fires.

## Project structure (current)
```
claude-mascot/
  mascot/
    tkinter_app.py    # MascotManager (one Tk root) + MascotWindow (Toplevel per session)
    state_store.py    # read state dir, staleness pruning
    config.py         # paths, timeouts, constants
    __main__.py       # `python -m mascot` -> tkinter_app.main
  hooks/
    emit.py           # invoked by every hook; stdin JSON -> atomic state update
    emit_logging.py   # PHASE 0 ONLY: dumps raw hook payloads to a log file
    state_logic.py    # compute_next_state (pure, tested)
  scripts/
    install_hooks.py          # merge real hook entries into ~/.claude/settings.json
    install_logging_hooks.py  # PHASE 0: install logging hooks (backup + uninstall)
  tests/
    test_phase1.py    # state_logic + emit (12 tests)
  docs/PLAN.md        # this file
  run_mascot.py       # entry point (python run_mascot.py)
  run_mascot.bat      # double-click launcher
  demo.py             # spawn fake sessions to preview the widget
  requirements.txt    # stdlib only; pytest for dev
```
> History: PyQt6 (frameless windows unreliable on Win11) and Flask+pywebview
> (overkill) were both removed in favor of plain tkinter.

## Phases
### Phase 0 — Verify hook schema (DO FIRST, de-risk)
- Install a logging `emit_logging.py` via `install_logging_hooks.py` (backs up
  settings.json, idempotent, `--uninstall` to revert).
- Run a real Claude session, trigger each event, inspect the log at
  `~/.claude/mascot/hook-log.jsonl`.
- **Confirm exact field names**: `session_id`, `tool_name`, `tool_input.subagent_type`,
  `cwd`, and what `Notification`/`Stop`/`SessionEnd` payloads actually contain.
- The entire design depends on these — verify before building on them.

### Phase 1 — State core (TDD, no GUI)
- `hooks/state_logic.py::compute_next_state` + session JSON schema.
- `hooks/emit.py`: argv event + stdin payload → read-modify-write atomic replace,
  always exit 0, swallow all errors.
- Tests: feed sample payloads for every event, assert resulting state. 80%+ on
  `state_logic`/`emit`.

### Phase 2 — Widget shell (Tkinter)
- `MascotWindow` (`mascot/tkinter_app.py`): one native Tkinter window per session.
  Frameless, always-on-top, draggable. Sized exactly to fit card (140x154).
- `MascotManager`: polls `state_store.load_states()` every 500ms, creates/destroys windows
  as sessions start/end. Stacks windows vertically in bottom-right corner.
- Card UI: emoji display (state), sub-agent badges, session label (project name).
- Entry point: `python run_mascot.py` or double-click `run_mascot.bat`.
- Emoji: `😴 idle`, `🤔 thinking`, `⚙️ working`, `⏳ waiting`, `💤 sleeping`.
- Sub-agent badges: single letter per type (R=reviewer, T=tdd, S=security, etc).

### Phase 3 — Optional: Custom art generation
- **Keep emoji placeholders** if they're sufficient and cute enough.
- **Or:** Generate a custom mascot character:
  - Tool: ComfyUI + SD 1.5 (RTX 4060, 8 GB VRAM)
  - Generate base character + 5 states via IP-Adapter consistency
  - Swap emoji display for `<img src="/static/mascot-{state}.png">` in HTML
  - No change to Flask server or state logic — just asset swap
- **Or:** Use a hand-drawn or SVG mascot character (simpler, no GPU needed).

### Phase 4 — Polish  ← RESUME HERE (next session)
All work is in `mascot/tkinter_app.py`. The 5 states + emojis already render and
sub-agent badges + session label already work. Remaining polish:

1. **Idle→sleeping timeout (was lost in the PyQt6→tkinter rewrite — reimplement).**
   - No hook emits `sleeping`. It's widget-side: when a window's raw state is
     `idle` for > `config.SLEEP_AFTER_IDLE_S` (30s), render the 💤 sprite instead.
   - Per-window: record `_idle_since` (time the raw state became `idle`); reset it
     whenever raw state changes away from idle. Compute an *effective* state in the
     refresh tick: `sleeping` if `idle` and elapsed > 30s, else the raw state.
   - The 500ms refresh tick already runs (`MascotManager._refresh`) — drive the
     idle check from there, or add a per-window `after()` timer. Remember
     `_render_sig` must include the *effective* state so the card rebuilds when it
     flips idle→sleeping.
2. **Waiting-state attention cue** — gentle border pulse (animate card bg/border
   color) while raw state == `waiting`, so the user notices Claude needs them.
3. **Optional bob** — subtle vertical float on the emoji label to feel alive
   (use `after()` loop nudging `pady`, or a Canvas). Keep it cheap.

State→emoji map (in tkinter_app.py): idle 😴 · thinking 🤔 · working ⚙️ ·
waiting ⏳ · sleeping 💤. Constants live in `mascot/config.py`
(`SLEEP_AFTER_IDLE_S=30`, `STATE_COLORS` per-state RGB available for the pulse).

### Phase 5 — Install & docs
- `install_hooks.py`: merge all real hook entries into `~/.claude/settings.json`
  using the **absolute venv interpreter path**, idempotent, `--uninstall`, backup
  settings.json first.
- README: setup, run, autostart-on-login.

## Risks & mitigations
| Risk | Level | Mitigation |
|---|---|---|
| Hook JSON field names differ from assumptions | HIGH | Phase 0 logging pass first |
| Local cross-state character consistency | HIGH | IP-Adapter with locked base reference |
| Which sub-agent stopped (matching) | MED | `PreToolUse`/`PostToolUse(Task)` pairing primary; `SubagentStop` backup |
| Hooks can't find Python / wrong env | MED | Install script writes absolute venv interpreter path |
| Transparent always-on-top Windows quirks (taskbar/DPI) | MED | `Qt.Tool` flag + high-DPI attrs; verify on Win 11 Pro |
| Stale mascots after crash | LOW | heartbeat `ts` + staleness timeout |
| Concurrent state writes within a session | LOW | atomic `os.replace` |
| 8 GB VRAM limits | MED | SD 1.5 default; ComfyUI low-VRAM mode |

## Conventions (greenfield — no repo to mirror)
- Naming: `snake_case` functions/modules, `PascalCase` classes, `UPPER_SNAKE` constants.
- Errors in hook path: swallow + exit 0 (never break Claude). Errors in widget: log, keep running.
- Tests: pytest, AAA structure, in `tests/`, target 80%+ on logic modules (GUI excluded).
- All hook scripts must be fast and side-effect-light (just a file write).

## Environment notes
- Machine: i5-12500H / RTX 4060 (8 GB VRAM) / 32 GB RAM, Windows 11 Pro.
- Python 3.11+; PyQt6; pytest + pytest-qt.
- Claude state dir: `~/.claude/mascot/state/`; Phase 0 log: `~/.claude/mascot/hook-log.jsonl`.

---

## STATUS TRACKER (update me)
- [x] **Phase 0** — verify hook schema  ✅ captured & verified; findings folded into the hook table above; logging hooks uninstalled
- [x] **Phase 1** — state core (TDD)  ✅ `hooks/state_logic.py` + `hooks/emit.py` + `tests/test_phase1.py` (12 tests passing)
- [x] **Phase 2** — widget shell (Tkinter)  ✅ **FINAL:** PyQt6 → Flask+pywebview → **Tkinter (winner)**. Native Tkinter windows, one per session, perfect size (140x154), stacked in bottom-right, real-time updates every 500ms, fully draggable. Hooks installed in settings.json. Run: `python run_mascot.py`
- [x] **Phase 3** — custom art & redesign  ✅ **Pixel-art mascot (default)** styled after Claude's blocky terminal creature (`mascot/sprite_pixel.py`): 16×16 ASCII grids, one face per state, Claude burnt-orange palette, accent sparkle on top. The earlier smooth vector blob is **kept on the side** in `mascot/sprite_smooth.py`; pick via `config.ART_STYLE` (`"pixel"`/`"smooth"`). `tkinter_app` dispatches on it and owns `round_rect` (a canvas util). Originally replaced emoji with an **original vector character** drawn on a Tkinter Canvas (`mascot/sprite.py::draw_creature`) — coral "familiar" with per-state faces (idle/thinking/working/waiting/sleeping/dizzy) and an antenna bulb that glows in the state accent. Stayed pure-stdlib (no ComfyUI/SD, no image assets). Card redesigned to a single rounded-panel Canvas with accent ring, state caption, canvas-drawn sub-agent badges + project label; drag/shake-dizzy/speech-bubble/bob/waiting-pulse all preserved (bob now moves the `creature` tag group; pulse via `itemconfig` on the border item). Cleanup: removed Phase-0 leftovers `hooks/emit_logging.py`, `scripts/install_logging_hooks.py`, ad-hoc `test_bubble.py`, and the empty `assets/` dir.
- [x] **Phase 4** — polish  ✅ idle→sleeping timeout (effective-state in `_render_sig`), waiting-state border pulse, subtle emoji bob. Plus closed-terminal cleanup (see below). All in `mascot/tkinter_app.py`.
- [x] **Phase 5** — install & docs  ✅ `scripts/install_hooks.py` rewritten to emit Claude Code's **real** hook format (matcher + hooks array, incl. `SubagentStop`), absolute interpreter + emit.py paths, idempotent (refreshes our blocks, preserves the user's other hooks), `--uninstall` removes only our blocks, backs up settings.json. `README.md` covers install/run/autostart-on-login/troubleshooting/uninstall. Tested on a temp settings file (idempotency + preservation + clean uninstall). Pushed to GitHub `Claude-Familiar` main.

### Open items / findings
- (Post-Phase) **Model + session duration on the card — ADDED.** The card now shows an info line `<Model> · <duration>` under the project name. `emit.py` stamps a `started` epoch once per session (key-presence, like `owner_pid`; `compute_next_state` preserves it); the widget reads `state["model"]` (captured at `SessionStart`) and `state["started"]`, shortens the model to its family (`Opus`/`Sonnet`/`Haiku`/`Fable`), and ticks the duration live in `_animate`. Card height grew to 196 to fit.
- (Phase 2) **RESOLVED:** PyQt6 frameless windows weren't rendering on Win11. Switched to Flask+pywebview: Flask handles state/polling/API, pywebview provides the native always-on-top window. Then **finalized on plain Tkinter** (see Phase 2 tracker).
- (Phase 4) **Shake-to-dizzy easter egg — ADDED.** Drag-shaking the card (rapid direction reversals on **any axis** — horizontal/vertical/diagonal, detected via move-vector dot product < 0: `SHAKE_REVERSALS` flips within `SHAKE_WINDOW_S`, each move ≥ `SHAKE_MIN_DIST`) shows the 😵‍💫 `dizzy` face for `DIZZY_DURATION_S`, then reverts. Widget-only (no hook/state-logic change). `dizzy` is a top-priority *effective* state alongside `sleeping`; effective-state changes now swap the emoji **in place** (`_refresh_render`) instead of rebuilding the card, so it's flicker-free and survives an in-progress drag grab. `_animate` drives expiry.
- (Phase 4) **Permission speech bubble — ADDED.** The `Notification` hook fires when Claude needs the user (incl. permission prompts). `state_logic` now captures `notify={message,type}` on `Notification` and clears it on the next forward event (prompt/tool/stop); `SubagentStop` preserves it. The widget shows a comic speech bubble (`BubbleWindow` in `mascot/tkinter_app.py`: transparent-corner Toplevel, rounded body + downward tail, follows the card while dragged) above the mascot with the message text. Detection/display only — approval still happens in the terminal (user chose the safe scope over a blocking-PreToolUse interactive-buttons design). **TO CONFIRM LIVE:** exact `message`/`notification_type` for a real permission prompt (Phase 0 only captured `idle_prompt`); the bubble shows whatever text arrives regardless.
- (Phase 4) **Closed-terminal lingering — FIXED.** When a terminal was killed, `SessionEnd` never fired, so the widget lingered up to the 300s staleness timeout. Fix: the hook records the owning `claude.exe` PID (`owner_pid`) once per session by walking the process ancestor chain (`hooks/proc.py`, ctypes Toolhelp32 snapshot — verified chain: `python → bash×N → claude.exe`). The widget prunes a session the moment that PID is dead (`mascot/proc.py::pid_alive` via `OpenProcess`/`WaitForSingleObject`), wired into `state_store.load_states` alongside staleness. Unknown/unconfirmed owner ⇒ never prune (staleness stays the backstop). The orphaned state *file* still clears at the 300s staleness mark; only the window disappears instantly.
