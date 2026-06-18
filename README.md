# Claude Familiar 🐾

A little desktop **familiar** for Claude Code on Windows and Linux. It floats a mascot card
on your screen and changes its face to reflect what Claude is doing **live** —
driven entirely by Claude Code's [hooks](https://docs.anthropic.com/en/docs/claude-code/hooks).

One mascot per Claude session. Sub-agents show up as little badges underneath.

The mascot is a **pixel-art creature** styled after Claude's blocky terminal
mascot — drawn cell-by-cell on a Tkinter canvas, no image files, no GPU. Its face
changes per state, with a sparkle that glows in the state's accent color:

```
idle (calm) · thinking (looking up) · working (focused) ·
waiting (wide-eyed) · happy (celebrating / petted) · sleeping (zzz) ·
dizzy (shake easter egg) · dead (gravestone, when usage runs out)
```

When idle, the face also reflects the **pet's mood** (see below) — droopy when
hungry, sad, sleepy, or sparkly when well cared-for — but Claude-activity states
always take priority, so the mascot never lies about what Claude is doing.

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
- **Celebrate.** When Claude finishes a turn, the mascot does a happy little hop
  before settling back to idle.
- **Pet it.** Click (tap) the mascot and it perks up happily with a few rising
  pixel hearts — a hand-drawn heart sprite, no image files.
- **Sleeping.** After a stretch of idle (90s by default, configurable) the mascot
  dozes off (💤) — and blinks now and then until it does.
- **Resizable.** Pick **small / medium / large** in the settings panel — the whole
  card (creature, text, badges) scales uniformly.
- **Mascot app icon.** Windows shortcuts and the running app use an icon rendered
  straight from the pixel mascot, so the taskbar matches the card on screen.
- **System tray (Windows / Linux / macOS).** A tray icon (via
  [pystray](https://github.com/moses-palmer/pystray)) sits in the notification
  area; its menu has *Pet…*, *Show / hide cards*, *Settings…*, and *Quit*. On
  Windows a left-click also shows/hides all the cards.
- **Permission speech bubble.** When Claude needs you (e.g. a permission prompt),
  a comic-style speech bubble pops up over the mascot with the message.
- **Impatient shake.** If a permission/attention prompt goes unanswered for 30s,
  the card starts to shake — and the longer you ignore it, the more frantic it
  gets, until you respond.
- **Gravestone.** When the session runs out of usage (a usage- or session-limit
  notification), the mascot becomes a 🪦 and keeps the message so you can read the
  reset time. It revives on your next prompt.
- **Shake-to-dizzy.** Grab a card and shake it — the mascot gets dizzy (😵‍💫).
- **Self-cleaning.** A card stays as long as its Claude process is alive — even
  idle or asleep — and vanishes the moment that process exits. (A heartbeat
  timeout is a backstop only for sessions whose owner can't be tracked.)

It is **display only** — it never approves anything or interferes with Claude.
Hooks just write a small JSON state file; the widget polls and renders it.

## Raise a pet (Tamagotchi mode) 🥚

Beyond the live status, the familiar is a **virtual pet you raise over time** —
one global creature shared across all your sessions, a delight rather than a chore.

- **Earn coins from real work.** Finishing a turn (+5), a sub-agent finishing (+3),
  your first prompt of the day (+20), and petting (+1) all earn coins — under a
  gentle **daily cap**, so it never pays to over-use Claude just to farm currency.
- **A shop.** Spend coins on **food** (consumable) and **toys** (reusable, on a
  play cooldown). Some items have trade-offs — an energy drink raises energy but
  lowers happiness — and higher-tier items unlock as the pet levels up.
- **Three gentle needs** — hunger, happiness, energy — drift over time; energy
  drains while Claude works and refills while it's idle/asleep. Needs only ever
  dull the mood, **never sickness or death** (the gravestone stays reserved for
  usage limits).
- **Mood on the face.** While idle, the mascot's face reflects the pet's mood, with
  a piece of food or a 💤 popping up now and then when it's hungry or sleepy.
- **It grows up.** The pet earns XP, levels up, and visibly evolves —
  **egg → baby → teen → adult** (gated by both level and real age) — with a
  milestone sparkle at higher levels.
- **The Pet window.** Open it from the tray (*Pet…*), the 🐾 button on a card, or
  Settings. It's the home for the pet: need bars, coins, level, name, inventory,
  and the shop with **Buy / Feed / Play**. Name your pet there too.
- **Glance tooltip.** Hover a card for a compact status — the three need bars,
  coins, level, and name.
- **Reset any time.** Settings → *Reset progress* starts over with a fresh egg.

The pet lives in `~/.claude/mascot/pet.json`; the widget is its single writer (it
applies decay and derives coins/XP from your session transitions — the hook
emitter is untouched). The balance numbers (decay rates, coin amounts, level/stage
curves) are easy to tune in `mascot/pet_logic.py`, and item prices/effects in
`mascot/shop.py`.

## Requirements

- **Windows** (tested on Windows 11 Pro) or **Linux** (X11; freedesktop `.desktop`
  launchers). On Linux the floating card is opaque — X11 Tk has no chroma-key
  transparency — so leave the "transparent card" option off there.
- **Python 3.11+** with Tkinter (bundled with the standard python.org installer;
  on Debian/Ubuntu install `python3-tk`)
- **Runtime dependencies** are permitted as of
  [ADR-0001](docs/adr/0001-runtime-dependencies.md) — the project no longer commits
  to pure standard library. Any runtime deps live in `requirements.txt`
  (`pip install -r requirements.txt`), with OS-specific ones gated by environment
  markers. (The core today still runs on the standard library alone; third-party
  packages land as issues #17–#20 are implemented.)
- The dev/test tools (`pytest`, `hypothesis`, `ruff`) live in `requirements-dev.txt`:
  `pip install -r requirements-dev.txt`.

## Install

**One-click (recommended):**

```bash
python install.py          # or double-click install.bat
```

This installs Claude Familiar as a real desktop app: it installs the Claude Code
hooks, adds **application-menu and desktop shortcuts** (Start-menu `.lnk` files on
Windows, freedesktop `.desktop` entries on Linux — so you can launch it with the
mascot icon, just like any other app), and opens the **settings panel**. There you can pick the mascot art, choose the
**widget size** (small / medium / large), toggle the transparent floating card,
add/remove the app shortcuts, enable run-at-login, and launch the widget.
Reopen it any time with `settings.bat` or `python -m mascot.control_panel`.
Settings live in `~/.claude/mascot/settings.json`.

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

This spawns two fake sessions (one working, one idle) **and a demo pet**, so you
can see the cards, the idle-face mood, the food/💤 popups, the hover tooltip, and
the Pet window — without a live Claude session. Your real `pet.json` is backed up
and restored on exit, so the demo never touches your actual progress.

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
- **`mascot/manager.py`** (`MascotManager`) polls the state directory every second
  and creates/destroys one native Tkinter window (`mascot/tkinter_app.py`) per
  active session. Each card is a single Canvas; the mascot is drawn by
  **`mascot/sprite_pixel.py`** (or `sprite_smooth.py`, per `config.ART_STYLE`). The
  manager is also the single writer of the pet (`pet.json`), applying decay and
  awarding coins/XP from the polled state transitions.

State files live in `~/.claude/mascot/state/`. Each carries a heartbeat (`ts`)
and the owning `claude.exe` PID; a card is pruned the moment that process exits.

## Project layout

```
claude-mascot/
  mascot/
    manager.py        # MascotManager: one Tk root, polls sessions, single writer of the pet
    tkinter_app.py    # MascotWindow: one card per session (canvas, drag, pet, tooltip, paw btn)
    effective_state.py# pure overlay: dizzy/happy/sleeping/blink + stall watchdog + idle mood
    popups.py         # speech bubble + pet status tooltip (frameless Toplevels)
    popup_place.py    # pure multi-monitor popup placement (tested)
    scale.py          # widget-size scaling primitives
    sprite_pixel.py   # Claude-style pixel creature: faces + evolution stages + hearts/emotes
    sprite_smooth.py  # original rounded vector character (kept on the side)
    pet_logic.py      # PURE pet core: decay, item effects, coins/XP, mood, level, stage (tested)
    pet_store.py      # pet.json wrapper: load/save + decay-on-load (single source of truth)
    shop.py           # data-driven shop catalog + buy/feed/play (pure, tested)
    pet_window.py     # the Pet window: dashboard + shop + feed/play (in-process or standalone)
    item_art.py       # pixel art for the shop items
    icon.py           # app icon (.ico/.png + iconphoto) rendered from the pixel mascot
    tray.py           # cross-platform system-tray icon + menu (pystray)
    single_instance.py# one-widget-at-a-time guard (named mutex / flock)
    control_panel.py  # settings panel: art, size, display, install, autostart, hooks, reset pet
    settings.py       # load/save ~/.claude/mascot/settings.json
    osplatform.py     # IS_WINDOWS / IS_LINUX / IS_MACOS + monitor work areas
    desktop_entry.py  # write freedesktop .desktop launchers (Linux)
    shortcuts.py      # app shortcuts: .lnk (Windows) / .desktop (Linux)
    autostart.py      # run-at-login entry: Startup .lnk (Windows) / XDG autostart (Linux)
    state_store.py    # read state dir; prune by process liveness (staleness backstop)
    proc.py           # is the owning claude process still alive? (kernel32 / os.kill)
    config.py         # paths, timeouts, sizes (UI_SCALE), colors
    __main__.py       # python -m mascot
  hooks/
    emit.py           # invoked by every hook; stdin JSON -> atomic state update
    state_logic.py    # compute_next_state (pure, tested)
    proc.py           # find owning Claude PID via process ancestry (Toolhelp / /proc)
  scripts/
    install_hooks.py  # install/uninstall hooks in ~/.claude/settings.json
  tests/              # pytest suite for state_logic + emit
  install.py          # one-click installer (install.bat wraps it)
  settings.bat        # open the settings / control panel
  run_mascot.py       # entry point
  run_mascot.bat      # double-click launcher
  demo.py             # preview with fake sessions
  docs/PLAN.md        # design notes & phase tracker
```

The app icon (`assets/claude_familiar.ico`) is generated from the pixel mascot on
install (and whenever autostart is enabled), so it is not checked into the repo.

## Tests

```bash
pip install -r requirements-dev.txt   # pytest + hypothesis + ruff (dev-only)
python -m pytest -q                    # tests
python -m ruff check .                 # lint
```

Covers the state machine, the **pet engine** (decay, item effects, coins/XP with
the daily cap, mood, level, stage, and the shop buy/feed/play), and the file-I/O
wrappers (`emit`, `pet_store`). The example-based cases in `tests/test_phase1.py`
are complemented by **property-based tests** (`tests/test_properties.py`,
[Hypothesis](https://hypothesis.readthedocs.io/)) that fuzz the pure cores'
invariants — stat clamping, immutability, the daily coin cap, level monotonicity,
and stage non-regression. GUI is excluded — verified visually via `demo.py`.

Linting is [Ruff](https://docs.astral.sh/ruff/) (config in `ruff.toml`, line
length 99); `ruff check` is the gate. `ruff format` is intentionally not run as a
bulk pass — the source is hand-formatted, so the lint config leaves layout alone.

## Troubleshooting

- **No card appears when Claude runs.** Make sure the widget is running
  (`python -m mascot`) and that hooks installed cleanly — re-run
  `python scripts/install_hooks.py` and check `~/.claude/settings.json`. The
  interpreter in the hook command must be a Python that can import `tkinter`.
- **Card lingers after closing a terminal.** It should vanish the moment the
  Claude process exits. If a session crashed in a way that hides its process from
  the widget, an owner-less card is pruned by the staleness backstop (~5 min).
- **Wrong Python gets used by hooks.** Re-run the install script *with the Python
  you want* — it records `sys.executable` at install time.
- **Desktop icon says "Untrusted" (Linux/GNOME).** GNOME marks newly created
  `.desktop` launchers untrusted until you allow them. Click the icon and choose
  **Allow Launching**, or mark it trusted from a terminal:
  `gio set ~/Desktop/claude-familiar.desktop metadata::trusted true`
  (the application-menu entry doesn't need this).
- **"Transparent card" does nothing on Linux.** Chroma-key transparency
  (`-transparentcolor`) is a Windows-only Tk feature; on X11/Wayland the card is
  always opaque regardless of the setting. Leave the toggle off on Linux.
- **No system-tray icon.** The tray needs `pystray` + `Pillow`
  (`pip install -r requirements.txt`) and a notification area to host it. If
  they're missing — or the desktop has no tray host — the widget runs exactly the
  same, just without an icon. (On Linux, pystray's AppIndicator backend may need
  `gir1.2-appindicator3`.) Open settings with `python -m mascot.control_panel` and
  quit the widget from its launcher/process.
- **Only one widget runs at a time.** Launching the widget again (e.g. autostart
  plus a manual launch) is a no-op — a single-instance guard makes the second one
  exit cleanly, so cards never appear doubled.

## Uninstall

```bash
python scripts/install_hooks.py --uninstall   # remove hooks
python -c "from mascot import shortcuts; shortcuts.uninstall_app_shortcuts()"  # remove Start-menu/desktop shortcuts
```

(You can also remove the shortcuts from the settings panel's **Install** section.)
Then delete the project folder. Leftover state files (if any) live in
`~/.claude/mascot/`.
