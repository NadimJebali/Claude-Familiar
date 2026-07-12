"""The session presenter — one place that decides what a session shows (#101).

The two themes (the Classic card, the Compact row) used to each re-compose the
"what is Claude doing right now" decision: the card inline in its render method,
the compact panel through a parallel, partial copy that skipped the ladder — so
a wedged turn read idle on a card yet "working…" forever in a row. This module
is the single deep interface that ends that split.

A :class:`SessionPresenter` — one per live session, stateful, clock-injected,
Qt-free — owns the effective-state ladder (the :class:`~mascot.overlay.Overlay`
is its implementation detail) and composes, in order:

    pending-tool promotion  →  usage-death override  →  raw-state clocks
      →  the overlay ladder  →  the display face  →  the caption

It answers one question, :meth:`SessionPresenter.view`, returning an immutable
:class:`SessionView` — the facts a theme renders. Both themes are paint adapters
over that view: the Classic card reads :attr:`SessionView.caption`; the Compact
row builds its richer text with :func:`status_line`. The same session state then
reads identically in both themes by construction.

This finishes the deepening the overlay began: the overlay turned a twelve-arg
ladder call into intent-notes plus one read; the presenter extends that move to
the rest of the decision. Kept clock-free (``now`` is always passed in) so every
transition is unit-tested exactly like the pure cores it composes.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from . import config, effective_state, effort, usage
from .overlay import Overlay, OverlayConfig

# --- overlay timing (authored once here; the card + compact both read these) ---
# How long a dizzy/celebrate/blink overlay lasts, the stumble-face window, the
# stall-watchdog graces, and the pending-permission wait. These moved off the
# Classic card so the presenter owns every threshold the ladder needs.
DIZZY_DURATION_S = 2.0
CELEBRATE_DURATION_S = 1.5
BLINK_DURATION_S = 0.12
STUMBLE_FACE_S = 8.0
THINKING_STALL_S = 180.0
WORKING_STALL_S = 270.0
# A main-thread tool left pending this long with no closing PostToolUse is most
# likely blocked on a permission prompt ("allow this command?"), which the VS Code
# extension emits no hook for — so the presenter reads it as "needs you" (#52).
# Kept well under WORKING_STALL_S so a truly wedged turn still falls to idle.
PERMISSION_WAIT_S = 45.0

# The default thresholds the widget runs with: the presenter's own constants plus
# the two user-configurable delays from settings. Tests inject their own config
# so the time-based ladder stays deterministic regardless of settings.json.
_OVERLAY_CONFIG = OverlayConfig(
    dizzy_duration_s=DIZZY_DURATION_S,
    celebrate_duration_s=CELEBRATE_DURATION_S,
    blink_duration_s=BLINK_DURATION_S,
    sleep_after_idle_s=config.SLEEP_AFTER_IDLE_S,
    shake_after_s=config.SHAKE_AFTER_S,
    permission_wait_s=PERMISSION_WAIT_S,
    thinking_stall_s=THINKING_STALL_S,
    working_stall_s=WORKING_STALL_S,
)

# Caption per displayed face — the canonical short word the Classic card shows;
# an unknown face falls back to the raw state. Moved off the card so the caption
# lives with the decision, not the painting.
_CAPTIONS = {
    "idle": "idle", "idle_blink": "idle", "idle_happy": "idle", "idle_hungry": "idle",
    "idle_sad": "idle", "idle_tired": "idle",
    "thinking": "thinking…",
    "working": "working…", "working_read": "working…", "working_edit": "working…",
    "working_run": "working…", "working_web": "working…",
    "planning": "planning…", "stumble": "oops…", "compacting": "tidying memories…",
    "waiting": "needs you!", "waiting_angry": "needs you!",
    "sleeping": "sleeping…", "dizzy": "whoa…", "happy": "yay!",
    "dead": "out of usage",
}

# The working-family faces (all captioned "working…"): the Compact row appends the
# tool · file detail for these; every other face shows its plain caption.
WORKING_FACES = frozenset(
    {"working", "working_read", "working_edit", "working_run", "working_web"})

# The waiting-family faces the Compact row inlines its notify message onto.
_WAITING_FACES = frozenset({"waiting", "waiting_angry"})

# The dark panel base the effort tints blend over (PANEL_FILL "#1d1f29" as RGB).
# Lives here so the chrome decision — quiet tint vs animated marker — is computed
# once; the adapters import it for the per-cell pixel animation they still paint.
_PANEL_FILL_RGB = (29, 31, 41)


def file_basename(path: object) -> str:
    """The display name of a stamped working file — the final path segment
    (both separators handled; hooks write native paths)."""
    if not isinstance(path, str) or not path:
        return ""
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _hex(rgb: tuple[int, int, int]) -> str:
    """An ``#rrggbb`` string for an (r, g, b) triple. Clamps + rounds so a lerped
    (float) color hexes cleanly too."""
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _accent_for(face: str) -> str:
    """The sprite accent for a displayed face — the per-state color, falling back
    to the idle accent for any face without its own (so a new face can't crash)."""
    return _hex(config.STATE_COLORS.get(face, config.STATE_COLORS["idle"]))


def usage_bars(snapshot: Any, now: float) -> tuple[tuple[str, float, str], ...]:
    """The account-usage bars to draw — ``(label, percent, traffic-light color)``,
    in order (5h then 7d), the percentage already reset-decayed by ``usage``. The
    one bars derivation both themes share: a Classic card draws it per-card, the
    Compact panel once at its foot (the bars are account-global, not per-session)."""
    return tuple((bar.label, bar.pct, _hex(usage.bar_color(bar.pct)))
                 for bar in usage.usage_view(snapshot, now))


def _ring(context_pct: float | None) -> tuple[float, str] | None:
    """The per-session context gauge: ``(percent, traffic-light color)`` or ``None``
    until the transcript tailer has a first result for the session."""
    if context_pct is None:
        return None
    return context_pct, _hex(usage.bar_color(context_pct))


def bg_marker(kind: str, t: float) -> tuple:
    """The animated-background marker an adapter paints: ``(kind, rounded t)`` for
    the animated kinds, or the clock-free ``("solid",)`` — so a non-animating frame
    keeps a stable signature and the repaint guard skips it."""
    return ("solid",) if kind == "solid" else (kind, round(t, 3))


def _dot_color(draw_raw: str, is_dead: bool, effort_level: str) -> str:
    """The Compact activity dot, by precedence: an attention state (tombstoned or
    waiting — real or pending-promoted) wears its own accent; else the resolved
    effort tint; else the state accent (an unknown state reads as idle grey). Only
    the dot carries effort — the sprite accent never does."""
    if is_dead:
        return _hex(config.STATE_COLORS["dead"])
    if draw_raw == "waiting":
        return _hex(config.STATE_COLORS["waiting"])
    if effort_level:
        return _hex(effort.TINTS[effort_level])
    return _hex(config.STATE_COLORS.get(draw_raw, config.STATE_COLORS["idle"]))


def _effort_chrome(effort_level: str, *, contested: bool
                   ) -> tuple[str, str | None, str]:
    """The effort chrome decision: ``(chrome_level, effort_fill, bg_kind)``.

    A contested session — tombstoned, or demanding attention (waiting) — stays
    uncontested: no effort decoration competes with the attention state, in either
    theme. Otherwise the quiet levels get a flat tint (``effort_fill``, static, so
    it's baked here) and the two animated levels get a background marker
    (``rainbow``/``ripple``) the adapter animates; the marker's ``bg_kind`` and the
    ``chrome_level`` (for the adapter's animated border color) are the decision."""
    chrome_level = "" if contested else effort_level
    if chrome_level and not effort.is_animated(chrome_level):
        # A quiet, known level: its flat tint is static (t-free), so bake it here.
        # panel_fill is guaranteed non-None for a known level (the None-guard is for
        # mypy, not a reachable case in this branch).
        fill_rgb = effort.panel_fill(chrome_level, _PANEL_FILL_RGB, 0.0)
        effort_fill = _hex(fill_rgb) if fill_rgb is not None else None
    else:
        effort_fill = None
    if effort.is_animated(chrome_level):
        bg_kind = "rainbow" if chrome_level == "max" else "ripple"
    else:
        bg_kind = "solid"
    return chrome_level, effort_fill, bg_kind


@dataclass(frozen=True)
class SessionView:
    """The immutable facts a theme renders for one session at one instant.

    ``effective`` is the semantic state (drives motion / emotes / gates);
    ``face`` is the sprite face DRAWN for it; ``caption`` is the canonical short
    word (the Classic card shows this directly). ``draw_raw`` is the promoted raw
    with the usage-death override applied — the value gates and the compact status
    branch on. The remaining fields are the semantic facts a theme composes text
    from: whether the account is tombstoned (``is_dead``) and when it returns
    (``reset_at``), the pending attention message, the active tool, and the
    working file's display name.

    The view has grown a fact group per ticket: #101 the state text, #102 the
    visual-identity trio (accent, dot color, dim), #103 the effort chrome, #104 the
    usage bars + staleness + context ring. The info line is added by a later ticket.
    """
    effective: str
    face: str
    draw_raw: str
    caption: str
    is_dead: bool
    reset_at: float | None
    notify_message: str | None
    tool: str | None
    file_name: str
    # Visual identity (#102). ``accent`` is the sprite tint the Classic card paints;
    # ``dot_color`` is the Compact activity dot (attention > effort > state); ``dim``
    # is whether a Compact row reads quiet (effectively idle, never a tombstone).
    accent: str
    dot_color: str
    dim: bool
    # Effort chrome (#103), the uncontested decision — the adapter supplies the clock
    # and paints the pixels. ``chrome_level`` is the effort level driving chrome ("" when
    # a waiting/dead state contests it, so the animated border color the adapter derives
    # from it goes quiet); ``effort_fill`` is the quiet levels' flat panel tint (None for
    # the animated levels / no effort); ``effort_bg_kind`` is "rainbow"/"ripple"/"solid".
    chrome_level: str
    effort_fill: str | None
    effort_bg_kind: str
    # Usage instrumentation (#104). ``bars`` is the account-global 5h/7d usage bars
    # (label, percent, color) — same for every session, drawn per-card / once in
    # compact; ``usage_stale`` labels an aged snapshot; ``ring`` is this session's
    # own context-window gauge (percent, color) or None until the first tailer result.
    bars: tuple[tuple[str, float, str], ...]
    usage_stale: bool
    ring: tuple[float, str] | None


class SessionPresenter:
    """Owns one session's presentation decision around an injected clock.

    The theme pushes inputs in — :meth:`adopt_state` each hook update,
    :meth:`adopt_usage` each usage snapshot — and marks gestures with the
    intent-notes (:meth:`note_dizzy`, :meth:`note_celebrate`, :meth:`note_blink`);
    it then asks :meth:`view` for the facts to render. The transient overlays are
    naturally gated by their notes: a Compact row's presenter is never sent a
    dizzy/blink note and is built with ``celebrates=False``, so its rows stay
    still while a card hops and blinks off the same ladder.
    """

    def __init__(self, cfg: OverlayConfig = _OVERLAY_CONFIG, *,
                 raw: str = "idle", now: float = 0.0, celebrates: bool = True) -> None:
        self._overlay = Overlay(cfg, raw=raw, now=now)
        self._raw = raw
        self._celebrates = celebrates
        self._state: dict[str, Any] = {"state": raw}
        self._usage: Any = None
        self._context_pct: float | None = None

    # --- inputs pushed in -------------------------------------------------
    def adopt_state(self, state: dict[str, Any], now: float) -> None:
        """Adopt a fresh hook state, celebrating a just-finished turn (when this
        presenter celebrates). The finished-turn detection lives here — the
        decision the Classic card used to make inline — so both themes' presenters
        agree on what counts as a clean finish."""
        prev_raw = self._raw
        self._state = dict(state)
        raw = str(state.get("state", "idle"))
        if self._celebrates and effective_state.should_celebrate(
                prev_raw, raw, bool(state.get("stumbled"))):
            self._overlay.note_celebrate(now)
        self._raw = raw

    def adopt_usage(self, snapshot: Any) -> None:
        """Adopt the latest account-global usage snapshot; the next :meth:`view`
        applies the death override from it (a full window tombstones the session
        until its reset), reading the clock at :meth:`view` time, and derives the
        usage bars + staleness."""
        self._usage = snapshot

    def adopt_context(self, pct: float | None) -> None:
        """Adopt this session's context-window fill % (from the transcript tailer);
        ``None`` = not known yet (no ring). Drives the view's context gauge."""
        self._context_pct = pct

    # --- gesture intent notes (card-only sources leave a compact row still) ---
    def note_dizzy(self, now: float) -> None:
        self._overlay.note_dizzy(now)

    def note_celebrate(self, now: float) -> None:
        self._overlay.note_celebrate(now)

    def note_blink(self, now: float) -> None:
        self._overlay.note_blink(now)

    # --- narrow reads for behaviours that aren't the displayed state ------
    def is_dizzy(self, now: float) -> bool:
        """Whether the dizzy overlay is still in effect (the card's tap gate)."""
        return self._overlay.is_dizzy(now)

    def waiting_elapsed(self, now: float) -> float | None:
        """How long the current attention prompt has gone unanswered, or ``None``
        (the card's attention-shake ramp)."""
        return self._overlay.waiting_elapsed(now)

    # --- the single read --------------------------------------------------
    def view(self, now: float, *, mood: str = "content",
             effort_fallback: str = "") -> SessionView:
        """The facts to render this frame. Composes, in the order the Classic card
        established: promote a long-pending tool, override to ``dead`` when usage
        is exhausted, run the raw clocks, layer the ladder, then pick the display
        face and caption. ``mood`` tints the idle face (the pet's mood, ``content``
        when there's no pet).

        The session's reasoning effort is resolved here — its own per-turn level
        (from the state) over the account-wide ``effort_fallback`` the adapter
        supplies. Reading that fallback is I/O (Claude's settings.json), so it stays
        adapter-side; the resolve pairing and everything it drives — the Compact
        dot tint and the effort chrome — live on this pure seam so both themes get
        one answer."""
        state = self._state
        ts = state.get("ts")
        # Promote a pending permission prompt off the *original* raw, then let a
        # full usage window tombstone every state. Drive the clocks + ladder off
        # this promoted raw so the normal waiting machinery still engages.
        draw_raw = self._overlay.promote(self._raw, now, ts=ts, tool=state.get("tool"))
        reset_at = usage.exhausted_until(self._usage, now)
        if reset_at is not None:
            draw_raw = "dead"
        self._overlay.note_raw(draw_raw, now)
        effective = self._overlay.effective(draw_raw, now, ts=ts, mood=mood)
        stumbled_recent = (bool(state.get("stumbled")) and ts is not None
                           and (now - float(ts)) < STUMBLE_FACE_S)
        face = effective_state.display_face(
            effective, tool=state.get("tool"),
            permission_mode=str(state.get("permission_mode", "")),
            stumbled_recent=stumbled_recent)
        notify = state.get("notify")
        notify_message = notify.get("message") if isinstance(notify, dict) else None
        effort_level = effort.resolve(state.get("effort", ""), effort_fallback)
        is_dead = draw_raw == "dead"
        contested = is_dead or draw_raw == "waiting"
        chrome_level, effort_fill, effort_bg_kind = _effort_chrome(
            effort_level, contested=contested)
        return SessionView(
            effective=effective,
            face=face,
            draw_raw=draw_raw,
            caption=_CAPTIONS.get(face, self._raw),
            is_dead=is_dead,
            reset_at=reset_at,
            notify_message=notify_message if isinstance(notify_message, str) else None,
            tool=state.get("tool"),
            file_name=file_basename(state.get("file")),
            accent=_accent_for(face),
            dot_color=_dot_color(draw_raw, is_dead, effort_level),
            dim=not is_dead and draw_raw == "idle",
            chrome_level=chrome_level,
            effort_fill=effort_fill,
            effort_bg_kind=effort_bg_kind,
            bars=usage_bars(self._usage, now),
            usage_stale=usage.is_stale(self._usage, now),
            ring=_ring(self._context_pct),
        )


def status_line(view: SessionView, *, notify_max_chars: int) -> str:
    """The Compact row's rich state text, composed from ``view``.

    The canonical caption, except: a tombstoned row carries its reset time, a
    waiting row inlines the (truncated) notify message — compact has no popup
    bubbles — and a working row appends the tool · file detail. ``notify_max_chars``
    is the adapter's width budget for the inlined message.
    """
    if view.is_dead:
        if view.reset_at is not None:
            return "out of usage · resets " + time.strftime(
                "%H:%M", time.localtime(view.reset_at))
        return "out of usage"
    if view.face in _WAITING_FACES:
        message = view.notify_message
        if message:
            if len(message) > notify_max_chars:
                message = message[:notify_max_chars] + "…"
            return f"needs you! · {message}"
        return "needs you!"
    if view.face in WORKING_FACES:
        parts = [p for p in (view.tool, view.file_name) if p]
        return "working · " + " · ".join(parts) if parts else "working…"
    return view.caption
