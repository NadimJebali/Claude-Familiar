# ADR-0002: Migrate the widget view layer to PySide6 (Qt), hard cutover

- **Status:** Accepted — **delivered** (cutover [#63](https://github.com/NadimJebali/Claude-Familiar/issues/63), 2026-07-10)
- **Date:** 2026-07-09
- **Resolves:** [#51](https://github.com/NadimJebali/Claude-Familiar/issues/51) (PRD)
- **Builds on:** [ADR-0001](0001-runtime-dependencies.md) (runtime dependencies permitted)

## Context

The widget's view layer is Tkinter. That choice has hit ceilings the project
already feels (root-caused in PRD #51):

- **Jank while Claude works.** State files and the pet are re-read on the Tk UI
  thread every poll, and any visible change triggers a full `delete("all")` +
  recreate of the card's canvas. The face animation hitches exactly when the
  card matters most.
- **No per-pixel transparency on Linux.** The card is an opaque rectangle there
  (a documented limitation); Windows only gets transparency via chroma-keying,
  which fights anti-aliased edges and shadows.
- **No vsync / compositor.** Slow animations step visibly; there is no realistic
  path to crossfades, drop shadows, or smooth evolution scaling.

These are capability ceilings, not tuning problems — no amount of Tk tweaking
delivers cross-platform per-pixel alpha or vsynced motion.

## Decision

**Migrate the view layer to PySide6 (Qt for Python) as a hard cutover.** PySide6
becomes a **required runtime dependency**. There is no dual-renderer setting and
no transition fallback: once the Qt widget reaches parity plus the glow-up, the
Tk view layer is deleted (issue #63).

Scope and guarantees:

- **"Pixel soul, smooth body."** The 16×16 pixel-grid art stays the single
  source of truth. Qt renders those exact grids — integer-scaled so pixels stay
  crisp — but with the polish Tk cannot: per-pixel-alpha rounded cards with a
  painted drop shadow on every platform, crossfades, and vsynced motion.
- **SpriteRenderer seam.** Sprite drawing goes behind an interface that consumes
  the grid data, with a Qt pixel renderer as its only implementation now. An
  alternate art style (e.g. a vector skin) becomes an additive second
  implementation later — the seam is built, the second renderer is not.
- **The pure cores and the hooks pipeline are untouched** — the state machine,
  pet engine, shop, effective-state overlay, roster, popup placement, scaling,
  and the whole `hooks/` emit path. Their pytest/Hypothesis suites are the
  safety net and must pass unmodified.

## Cost reversal vs ADR-0001

ADR-0001 permitted runtime dependencies but set a bar: *"a dep that only saves a
few lines is not worth the install/supply-chain cost,"* and it flagged Pillow as
*"a comparatively large native dependency."* PySide6 is far larger still
(a ~150 MB Qt install). This ADR clears that bar deliberately:

- **It is not saving a few lines.** PySide6 replaces the entire view layer and is
  the *only* way to get the required capabilities (cross-platform per-pixel
  alpha, vsync, a compositor for shadows/crossfades). The cost buys capability,
  not convenience.
- **It partially offsets other deps.** Qt subsumes the system tray (retiring
  **pystray** and, for tray purposes, **Pillow**) and native toasts (retiring
  **plyer**). Those are removed at the cutover (#63), so the net new dependency
  weight is smaller than PySide6's raw size suggests. `psutil` and `pywin32`
  remain.

## Consequences

**Positive**
- Fixes the jank *by architecture*: event-driven ingestion (a filesystem watcher
  + slow backstop), file I/O off the UI thread, and pre-rendered pixmaps blitted
  instead of a per-change canvas rebuild.
- Real per-pixel transparency and a painted drop shadow on Windows **and** Linux.
- A path to the glow-up: crossfades, sub-pixel particle motion, smooth evolution.
- **One renderer to maintain** after the cutover — every future feature is built
  and tested once.

**Negative**
- The largest dependency the project has taken; install is heavier.
- A Qt learning curve, and real cross-platform risks to retire during the port:
  HiDPI scaling, frameless-window dragging, and translucency across Linux
  compositors (X11 vs Wayland).

**Mitigations**
- The Qt sprite renderer is verified head­less with an offscreen smoke test
  (every face/stage renders non-blank); visual quality is checked through a
  gallery/demo, as the GUI always has been.
- The migration is phased (PRD #51 tickets #53–#63) so each Qt surface lands and
  is reviewed on its own; the cutover that deletes Tk is last.

## Notes

This reverses the Tk view-layer choice, not ADR-0001's dependency policy — it
*applies* it. The PyInstaller rejection (TASK.md) still stands on its own merits
and is not reopened. macOS support beyond what the tray already offers remains
out of scope.

**Delivered (2026-07-10, #63).** The whole view layer is PySide6: card, popups, pet
window, control panel, tray + native toasts. The Tk view modules are deleted and
pystray/Pillow/plyer are dropped from `requirements.txt`; no module imports tkinter,
and the running widget pulls in none of the retired deps. Every entry point
(`run_mascot.py`, `python -m mascot`, `demo.py`, the shortcut Settings) launches Qt.
One renderer remains — the `SpriteRenderer` seam over the same 16×16 grids. The pure
cores and their tests were untouched by the swap.
