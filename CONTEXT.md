# Domain glossary — Claude Familiar

The shared language for this codebase. Use these terms exactly in code, comments,
commits, specs, and reviews — consistency is the point. Architecture nouns
(**module**, **interface**, **seam**, **adapter**, **deep module**, **leverage**,
**locality**) come from the `/codebase-design` skill and mean the same here.

## The widget

- **Familiar** (a.k.a. **mascot**) — the pixel-art creature the widget floats on
  screen. One per **session**. Styled after Claude Code's blocky terminal mascot;
  its faces are 16×16 ASCII grids rasterized by the **SpriteRenderer** seam.
- **Session** — one live Claude Code run, identified by its session id. The hooks
  write one **state file** per session; the widget shows one presentation per
  session (a card, or a compact row).
- **Theme** — how sessions are presented. **Classic** = one **card** per session
  (the animated mascot). **Compact** = one panel listing sessions as **rows**.
  Chosen in Settings, switchable live.
- **Theme adapter** — the painting half of a theme (the Classic card, the Compact
  row). An adapter reads a **session view** and paints it; it does not decide what
  a session is doing. Both adapters sit over one seam, the **presenter**.

## State

- **Raw state** — what the hooks stamp into the state file: one of `idle`,
  `thinking`, `working`, `waiting`, `compacting`, `dead`. The writer's vocabulary;
  see `hooks/state_logic.py` and `docs/state-file-schema.md`.
- **Effective state** — the raw state with the widget's time-based overlays layered
  on (dizzy, celebrate, the waiting glare, the stall watchdog, dozing, blink, the
  pet-mood idle). Semantic — it drives captions, emotes, motion, and gates. Pure
  core: `mascot/effective_state.py`.
- **Display face** — the sprite face *drawn* for an effective state. Purely visual:
  the per-tool working eyes, the plan-mode `planning` face, the `stumble`. A face
  the sprite doesn't define falls back to the idle face, so a new state never
  crashes a render.
- **Tombstone** — the `dead` look (a pixel gravestone) shown when the account is out
  of usage. The reliable death signal is the usage feed, not the hooks: a full usage
  window tombstones every session until its reset, and a passed reset auto-revives.

## The presentation seam (#101)

- **Presenter** (`SessionPresenter`, `mascot/presenter.py`) — the **deep module**
  that decides what one session shows. Stateful, one per session, clock-injected,
  Qt-free. It owns the effective-state ladder (the **overlay** is its implementation
  detail) and composes, in order: pending-tool promotion → usage-death override →
  raw clocks → the ladder → display face → caption. Both theme adapters read it, so
  a card and a row can never disagree about what a session is doing.
- **Session view** (`SessionView`) — the immutable facts a theme adapter renders for
  one session at one instant (effective state, face, caption, tombstone facts, …).
  The interface of the presenter: the Classic card reads `view.caption`; the Compact
  row builds its richer text with `status_line(view)`.
- **Overlay** (`mascot/overlay.py`) — the small home for a session's effective-state
  timers (dizzy/celebrate/blink/idle/waiting) behind intent-notes plus one read. The
  presenter owns one; nothing else touches it. The deepening pattern the presenter
  extends.

## Effort & usage

- **Effort chrome** — the effort-reactive panel decoration: a quiet static tint for
  low/medium/high, the purple **ripple** for xhigh, the flowing **rainbow** for max.
  Keyed off one resolved effort level. Pure color math in `mascot/effort.py`, matching
  Claude Code's own palette.
- **Usage bars** — the 5h / 7d account-usage bars, with reset decay and a traffic-light
  color; a stale snapshot is labeled. Pure core: `mascot/usage.py`.
- **Context ring** — the per-session gauge that fills as the context window fills.

## Pet (Tamagotchi layer)

- **Pet** — the optional creature economy: hunger/happiness/energy, evolution
  (egg → baby → teen → adult), coins, a shop, cosmetics. Off by default; when off the
  familiar is a plain **hook visualiser**.
- **Pet view** (`PetView`, `mascot/pet_view.py`) — the pet projected to its visual
  facts: stage, hat, flourish, and the **mood** that tints the idle face. The pattern
  the session view mirrors for Claude activity.
