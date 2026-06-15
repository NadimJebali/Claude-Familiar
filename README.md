# Claude Familiar 🐾

A little desktop **familiar** for Claude Code on Windows. It floats a mascot card
on your screen and changes its face to reflect what Claude is doing **live** —
driven entirely by Claude Code's [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks).

One mascot per Claude session. Sub-agents show up as little badges underneath.

The mascot is a **pixel-art creature** styled after Claude's blocky terminal
mascot — drawn cell-by-cell on a Tkinter canvas, no image files, no GPU, no
dependencies. Its face changes per state, with a sparkle that glows in the
state's accent color:

```
idle (calm) · thinking (looking up) · working (focused) ·
waiting (wide-eyed) · sleeping (zzz) · dizzy (shake easter egg)
```

Two art styles ship in the box, selectable via `ART_STYLE` in
`mascot/config.py`:

- `"pixel"` (default) — the Claude-style blocky creature (`mascot/sprite_pixel.py`)
- `"smooth"` — an original rounded vector character (`mascot/sprite_smooth.py`)

The pixel faces are plain 16×16 ASCII grids in `sprite_pixel.py` — edit a grid,
see the change.

## What it does

- **One card per session.** Multiple Claude windows = multiple cards, stacked in
  the bottom-right corner and labeled by project folder.
- **Live state.** The card face tracks Claude in real time: thinking when you
  submit a prompt, working while a tool runs, waiting when Claude needs you.
- **Sub-agent badges.** When Claude spawns a sub-agent (the `Agent` tool), a small
  badge appears under the mascot and disappears when it finishes.
- **Sleeping.** After 30s idle the mascot dozes off (💤).
- **Permission speech bubble.** When Claude needs you (e.g. a permission prompt),
  a comic-style speech bubble pops up over the mascot with the message.
- **Shake-to-dizzy.** Grab a card and shake it — the mascot gets dizzy (😵‍💫).
- **Self-cleaning.** Closing a terminal removes its mascot immediately; crashed
  sessions are pruned by a heartbeat timeout.

It is **display only** — it never approves anything or interferes with Claude.
Hooks just write a small JSON state file; the widget polls and renders it.

## Requirements

- **Windows** (tested on Windows 11 Pro)
- **Python 3.11+** with Tkinter (bundled with the standard python.org installer)
- No external dependencies — the widget is pure standard library.
  `pytest` is only needed to run the tests.

## Install

**One-click (recommended):**

```bash
python install.py          # or double-click install.bat
```

This installs the Claude Code hooks and opens the **settings panel**, where you
can pick the mascot art, toggle the transparent floating card, enable
run-at-login, and launch the widget. Reopen it any time with `settings.bat` or
`python -m mascot.control_panel`. Settings live in
`~/.claude/mascot/settings.json`.

**Manual (hooks only):**

```bash
# 1. (optional) install dev/test deps
pip install -r requirements.txt

# 2. install the Claude Code hooks (writes to ~/.claude/settings.json)
python scripts/install_hooks.py
```

The install script:
- writes hook entries using the **absolute path** to your current Python
  interpreter and to `hooks/emit.py`, so they work from any cwd;
- backs up your original `settings.json` to `settings.json.mascot-backup`;
- is **idempotent** — safe to re-run (it refreshes the entries in place) and
  leaves any other hooks you have untouched.

To remove the hooks later:

```bash
python scripts/install_hooks.py --uninstall
```

## Run

```bash
python -m mascot
```

or, equivalently:

```bash
python run_mascot.py        # script entry point
run_mascot.bat              # double-click launcher
```

Then start a Claude Code session in any folder — a card appears and starts
reacting. Run the widget once; it manages all your sessions.

### Try it without Claude

```bash
python demo.py
```

This spawns two fake sessions so you can see the cards and cycle through states.

## Autostart on login (optional)

So the familiar is always there when you sign in:

1. Press `Win + R`, type `shell:startup`, press Enter. This opens your Startup
   folder.
2. Create a shortcut in that folder pointing at the launcher. To run it **without
   a console window**, target `pythonw.exe`:

   ```
   "C:\Path\To\pythonw.exe" "C:\Users\Vinny\Desktop\claude-mascot\run_mascot.py"
   ```

   (`pythonw.exe` sits next to `python.exe` in your Python install. Set the
   shortcut's *Start in* to the project folder.)

Alternatively, drop a shortcut to `run_mascot.bat` in the Startup folder if you
don't mind a console window.

## How it works

```
Claude Code session ──hooks──▶ emit.py ──atomic write──▶ ~/.claude/mascot/state/<session_id>.json
                                                                  │ (one file per session)
                                                                  ▼  widget polls every second
                                                    one frameless, always-on-top card per session
```

- **`hooks/emit.py`** is invoked by every hook with the event name as an argument
  and the hook payload on stdin. It updates that session's state file with an
  atomic `os.replace` and **always exits 0** — it can never block or break Claude,
  even if the widget isn't running.
- **`hooks/state_logic.py`** holds `compute_next_state(current, event, payload)`,
  a pure function (the unit-tested core) that maps each hook event to the next
  state.
- **`mascot/tkinter_app.py`** polls the state directory every second and
  creates/destroys one native Tkinter window per active session. Each card is a
  single Canvas; the mascot is drawn by **`mascot/sprite_pixel.py`** (or
  `sprite_smooth.py`, per `config.ART_STYLE`).

State files live in `~/.claude/mascot/state/`. Each carries a heartbeat (`ts`)
and the owning `claude.exe` PID so stale/closed sessions get cleaned up.

## Project layout

```
claude-mascot/
  mascot/
    tkinter_app.py    # MascotManager (one Tk root) + per-session windows + speech bubble
    sprite_pixel.py   # Claude-style pixel-art creature (default art)
    sprite_smooth.py  # original rounded vector character (kept on the side)
    state_store.py    # read state dir, staleness + dead-PID pruning
    proc.py           # is the owning claude.exe still alive?
    config.py         # paths, timeouts, sizes, colors
    __main__.py       # python -m mascot
  hooks/
    emit.py           # invoked by every hook; stdin JSON -> atomic state update
    state_logic.py    # compute_next_state (pure, tested)
    proc.py           # find owning claude.exe PID via process ancestry
  scripts/
    install_hooks.py  # install/uninstall hooks in ~/.claude/settings.json
  tests/              # pytest suite for state_logic + emit
  run_mascot.py       # entry point
  run_mascot.bat      # double-click launcher
  demo.py             # preview with fake sessions
  docs/PLAN.md        # design notes & phase tracker
```

## Tests

```bash
python -m pytest -q
```

Covers the state machine and the emit read-modify-write path (GUI excluded).

## Troubleshooting

- **No card appears when Claude runs.** Make sure the widget is running
  (`python -m mascot`) and that hooks installed cleanly — re-run
  `python scripts/install_hooks.py` and check `~/.claude/settings.json`. The
  interpreter in the hook command must be a Python that can import `tkinter`.
- **Card lingers after closing a terminal.** It should vanish immediately; if a
  session crashed hard it's pruned within the staleness timeout (~5 min).
- **Wrong Python gets used by hooks.** Re-run the install script *with the Python
  you want* — it records `sys.executable` at install time.

## Uninstall

```bash
python scripts/install_hooks.py --uninstall   # remove hooks
```

Then delete the project folder. Leftover state files (if any) live in
`~/.claude/mascot/`.
