"""Tkinter mascot card.

Defines `MascotWindow` — one always-on-top Toplevel per Claude session, drawn on
a single Canvas (the creature itself lives in `sprite_pixel.py`). The process
entry point and session manager live in `mascot/manager.py`. Native, built-in
tkinter only — no external deps. Run with: python -m mascot.
"""
from __future__ import annotations

import math
import random
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from . import (
    config,
    effective_state,
    osplatform,
    particles,
    pet_actions,
    pet_logic,
    shake,
    sprite_pixel,
    ui_icons,
)
from . import effort as effort_mod
from . import overlay as overlay_mod
from . import usage as usage_mod
from .pet_host import PetHost
from .pet_view import PetView, pet_view
from .popups import BubbleWindow, StatsTooltip
from .scale import font as _font
from .scale import s as _s


def _draw_creature(c, cx, cy, state, accent, view) -> None:
    """Draw the mascot (pixel art) for the pet's look `view`, scaled to the widget.

    The creature grows with its evolution stage and gets a milestone flourish at
    higher levels; the "dead" state is the pixel gravestone (stage-independent, and
    it wears no hat -- nor does the egg, both handled inside `draw_pet`)."""
    if state == "dead":
        sprite_pixel.draw_gravestone(c, cx, cy, CREATURE_PX)
        return
    px = max(1, round(CREATURE_PX * sprite_pixel.STAGE_SCALE.get(view.stage, 1.0)))
    sprite_pixel.draw_pet(c, cx, cy, view, state=state, accent=accent, px=px)


def round_rect(c, x1, y1, x2, y2, r, **kw) -> int:
    """A rounded rectangle as a smoothed polygon (canvas util, not art)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


STATE_CAPTIONS = {
    "idle": "idle",
    "idle_blink": "idle",       # a blink is still "idle" — keep the caption steady
    "idle_happy": "idle",       # idle-mood faces are still "idle" to the caption
    "idle_hungry": "idle",
    "idle_sad": "idle",
    "idle_tired": "idle",
    "thinking": "thinking…",
    "working": "working…",
    "working_read": "working…",    # per-tool faces are still "working" to the caption
    "working_edit": "working…",    # (the tool name itself takes over when running)
    "working_run": "working…",
    "working_web": "working…",
    "planning": "planning…",       # plan mode: pondering, not yet building
    "stumble": "oops…",            # a turn died on a transient API error
    "compacting": "tidying memories…",  # Claude Code is compacting its context
    "waiting": "needs you!",
    "waiting_angry": "needs you!",   # angry variant once the card starts shaking
    "sleeping": "zzz…",
    "dizzy": "whoa…",
    "happy": "yay!",
    "dead": "out of usage",
}

# --- card geometry / palette ----------------------------------------------
# Measurements are authored at the "small" size and scaled by `_s` (mascot.scale)
# so "medium"/"large" scale the whole card uniformly.
CARD_W = _s(158)
# Height carries enough headroom above the caption for the *adult* sprite (the
# tallest stage at 16x7px); the creature zone (margin..caption) is sized to it so
# the grown-up's ears clear the top border and its feet clear the caption text.
# The extra USAGE_ROW_H at the bottom holds the 5h/weekly usage bars (below the
# info line) — a pure addition, so nothing above it moves.
USAGE_ROW_H = _s(24)
CARD_H = _s(211) + USAGE_ROW_H
WIN_BG = "#101117"          # window backdrop (blends with the panel's corners)
CHROMA = "#ff00ff"          # chroma key -> transparent when TRANSPARENT_BG (unused elsewhere)
# Chroma-key transparency (-transparentcolor) is a Windows-only Tk feature; on
# X11/macOS it raises TclError, so we fall back to an opaque card there.
_SUPPORTS_CHROMA = sys.platform == "win32"
PANEL_FILL = "#1d1f29"
_PANEL_FILL_RGB = (29, 31, 41)   # PANEL_FILL as RGB, for fading heart particles
PANEL_EDGE = "#2a2d3b"      # resting border color
PANEL_MARGIN = _s(7)
PANEL_RADIUS = _s(20)

CREATURE_CX = CARD_W // 2
# Centered in the creature zone (margin..caption) so the adult grows symmetrically
# into the headroom rather than crowding the top edge or the caption below.
CREATURE_CY = _s(68)
CREATURE_PX = _s(5)         # pixel size of the main creature

CAPTION_Y = _s(129)
BADGE_Y = _s(151)
LABEL_Y = _s(175)
INFO_Y = _s(193)            # model · session duration

CAPTION_FONT = _font(9, "bold")
LABEL_FONT = _font(7)
INFO_FONT = _font(7)

LABEL_FG = "#8b8fa3"
INFO_FG = "#6b6f82"
BADGE_GAP = _s(26)          # spacing between sub-agent mini-mascots
MINI_PIXEL_PX = _s(1)       # pixel size for a mini sub-agent -> ~16px

# Usage bars (5h / weekly) — two thin labeled bars at the very bottom, in the same
# visual language as the tooltip's need bars. Laid out below INFO_Y so no existing
# element moves; the row is empty space when there's no usage data to show.
USAGE_BAR_H = _s(6)
USAGE_BAR_GAP = _s(5)               # vertical gap between the two bars
USAGE_ROW_TOP = _s(205)             # first bar's top edge (below the info line)
USAGE_LABEL_X = PANEL_MARGIN + _s(10)   # "5h" / "7d" label, west-anchored
USAGE_BAR_X0 = PANEL_MARGIN + _s(26)    # track left
USAGE_BAR_X1 = CARD_W - PANEL_MARGIN - _s(34)   # track right
USAGE_PCT_X = CARD_W - PANEL_MARGIN - _s(6)     # "NN%" text, east-anchored
USAGE_TRACK = "#2a2d3b"             # bar track (matches PANEL_EDGE)
USAGE_FONT = _font(6)

# Animation
BOB_AMPLITUDE = _s(4)
BOB_PERIOD_S = 2.0
PULSE_PERIOD_S = 1.2

# The speech bubble and hover tooltip (their constants + classes) live in
# mascot/popups.py.

# Shake-to-dizzy easter egg.
SHAKE_MIN_DIST = 7
SHAKE_WINDOW_S = 0.7
SHAKE_REVERSALS = 4
DIZZY_DURATION_S = 2.0

# Celebrate (happy) reaction: brief joy when Claude finishes a turn, and when the
# mascot is petted. A widget-side effective state, like dizzy/sleeping.
CELEBRATE_DURATION_S = 1.5

# Stumble: how long the embarrassed "oops" face lingers after a turn dies on a
# transient API error (measured from the state file's heartbeat at that moment).
STUMBLE_FACE_S = 8.0

# Click-to-pet: a press+release that moves less than this (px) is a pet tap, not a
# drag. Petting emits rising pixel hearts that fade as they climb.
PET_TAP_MAX_DIST = 5
HEART_PX = _s(2)                 # pixel size of a heart particle
HEART_RISE_PX = _s(34)           # how far a heart climbs over its life
HEART_LIFETIME_S = 0.85
MAX_HEARTS = 6

# Idle "life": occasional blink while idle, before the mascot dozes off.
BLINK_DURATION_S = 0.12
BLINK_MIN_GAP_S = 4.0
BLINK_MAX_GAP_S = 7.0

# Mood emotes: a small popup at the creature's upper-right every few seconds while
# it's in a low-need idle mood — a piece of food when hungry, a drifting "Z" when
# sleepy/tired. They rise and drift up-and-right, fading like the pet hearts, on the
# same animate clock. Placed upper-right (not over the face) so they read clearly,
# and clear of the paw button, which lives in the top-LEFT corner.
EMOTE_PX = _s(3)                 # slightly larger than the body pixels, for legibility
EMOTE_RISE_PX = _s(16)
EMOTE_LIFETIME_S = 1.4
EMOTE_MIN_GAP_S = 3.0
EMOTE_MAX_GAP_S = 5.0
_EMOTE_FOR_STATE = {"idle_hungry": "food", "idle_tired": "zzz", "sleeping": "zzz"}

# Stall watchdog: a turn that ends abnormally (notably a usage/session-limit hit)
# fires NO terminating hook, so the heartbeat just freezes wherever it was. Rather
# than look frozen-busy forever, effective_state.compute falls the *display* back
# to idle once a busy state has gone this long with no new event. A real limit
# lands in `working` far more often than `thinking` (after the first tool, every
# PostToolUse keeps the state `working`), so the watchdog covers both.
#   - `thinking`: short grace; pure-reasoning stretches are brief.
#   - `working`:  longer grace, since one tool (a big build/test) can legitimately
#     block for minutes with no intermediate hook. If it really is still running,
#     its PostToolUse refreshes `ts` and snaps the mascot straight back; sub-agent
#     work keeps `ts` warm via nested hooks, so it never trips this at all.
# Both stay under config.STALE_TIMEOUT_S so the fallback shows before the whole
# card is pruned as stale.
THINKING_STALL_S = 180.0
WORKING_STALL_S = 270.0          # just under STALE_TIMEOUT_S; demoted to a backstop
                                 # now that StopFailure resolves real turn-deaths

# Attention shake: while a permission/attention prompt sits unanswered, the whole
# card starts to shake after WAITING_SHAKE_AFTER_S, then grows steadily more
# frantic the longer it's ignored, reaching full aggression WAITING_SHAKE_RAMP_S
# later. Amplitude scales with the widget size; frequency does not (it's a rate).
WAITING_SHAKE_AFTER_S = config.SHAKE_AFTER_S          # configurable: delay before shaking
WAITING_SHAKE_RAMP_S = 60.0                           # ramps to full aggression over this
WAITING_SHAKE_AMP_MAX = _s(config.SHAKE_MAX_AMP_PX)   # configurable: how violent (max sway px)
WAITING_SHAKE_AMP_MIN = min(_s(2), WAITING_SHAKE_AMP_MAX)  # gentle start, never wider than max
WAITING_SHAKE_FREQ_MIN = 4.0     # sways/sec when gentle
WAITING_SHAKE_FREQ_MAX = 11.0    # sways/sec when frantic

# The fixed thresholds every card's effective-state overlay feeds into the pure
# core: overlay durations (dizzy/celebrate/blink) plus the sleep / watchdog /
# shake delays. Shared by all cards — the timers themselves are per-card.
_OVERLAY_CONFIG = overlay_mod.OverlayConfig(
    dizzy_duration_s=DIZZY_DURATION_S,
    celebrate_duration_s=CELEBRATE_DURATION_S,
    blink_duration_s=BLINK_DURATION_S,
    sleep_after_idle_s=config.SLEEP_AFTER_IDLE_S,
    shake_after_s=WAITING_SHAKE_AFTER_S,
    thinking_stall_s=THINKING_STALL_S,
    working_stall_s=WORKING_STALL_S,
)


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


# --- particle kinds (hearts + mood emotes) --------------------------------
# The thin per-kind sprite shells the particle field calls. Each adapts the
# generic (canvas, x, y, px, rgb-or-None) draw signature to the sprite call,
# resolving the fade RGB to a hex string where the sprite wants one. The shared
# lifetime/position/fade math lives in mascot/particles.py.
_ZZZ_FADE_RGB = (247, 243, 238)   # the "Z" starts near-white and fades to the panel


def _draw_heart_sprite(c, x, y, px, rgb) -> None:
    sprite_pixel.draw_heart(c, x, y, px, _hex(rgb))


def _draw_food_sprite(c, x, y, px, _rgb) -> None:
    sprite_pixel.draw_food(c, x, y, px)


def _draw_zzz_sprite(c, x, y, px, rgb) -> None:
    sprite_pixel.draw_zzz(c, x, y, px, color=_hex(rgb))


_PARTICLE_KINDS = {
    "heart": particles.ParticleKind(
        name="heart", lifetime_s=HEART_LIFETIME_S, rise_px=HEART_RISE_PX,
        pixel_px=HEART_PX, tag="heart", max_count=MAX_HEARTS,
        draw_sprite=_draw_heart_sprite, fade_from=config.STATE_COLORS["happy"],
    ),
    "food": particles.ParticleKind(
        name="food", lifetime_s=EMOTE_LIFETIME_S, rise_px=EMOTE_RISE_PX,
        pixel_px=EMOTE_PX, tag="emote", max_count=3,
        draw_sprite=_draw_food_sprite, fade_from=None,
    ),
    "zzz": particles.ParticleKind(
        name="zzz", lifetime_s=EMOTE_LIFETIME_S, rise_px=EMOTE_RISE_PX,
        pixel_px=EMOTE_PX, tag="emote", max_count=3,
        draw_sprite=_draw_zzz_sprite, fade_from=_ZZZ_FADE_RGB,
    ),
}

# The attention-shake recipe (intensity ramp + amplitude/frequency bands), fed to
# the Shake seam that owns the absolute-from-rest offset math.
_SHAKE_CONFIG = shake.ShakeConfig(
    after_s=WAITING_SHAKE_AFTER_S,
    ramp_s=WAITING_SHAKE_RAMP_S,
    amp_min=WAITING_SHAKE_AMP_MIN,
    amp_max=WAITING_SHAKE_AMP_MAX,
    freq_min=WAITING_SHAKE_FREQ_MIN,
    freq_max=WAITING_SHAKE_FREQ_MAX,
)


def _accent(state: str) -> str:
    return _hex(config.STATE_COLORS.get(state, config.STATE_COLORS["idle"]))


def _short_model(model: str) -> str:
    """A compact, friendly model name (e.g. 'claude-opus-4-8' -> 'Opus')."""
    if not model:
        return ""
    low = model.lower()
    for name in ("opus", "sonnet", "haiku", "fable"):
        if name in low:
            return name.capitalize()
    return model.replace("claude-", "")[:14]


def _format_duration(seconds: float) -> str:
    """Human-friendly elapsed time: '45s', '12m', '1h 3m'."""
    s = int(max(0, seconds))
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def _render_sig(state: dict[str, Any], effective: str, face: str,
                view: PetView, effort: str) -> tuple:
    """Signature of the *visible* content (excludes the `ts` heartbeat)."""
    subs = tuple((s.get("type") or "?") for s in (state.get("subagents") or []))
    # Include the active tool so the caption refreshes as it changes (only while
    # working, where it's surfaced — see _caption).
    tool = state.get("tool") if effective == "working" else None
    # Include the display face (it can change while the effective state doesn't —
    # e.g. the tool kind swaps mid-working) and the pet's look `view` (stage /
    # flourish / worn hat) so the card redraws when the pet evolves or re-dresses.
    # `effort` drives the panel tint, so a level change repaints the card once.
    return (effective, face, view, subs, state.get("cwd", ""), tool, effort)


def _usage_sig(bars: list) -> tuple:
    """Signature of the usage row — labels + rounded percents, so the card
    repaints when a bar's value changes (incl. a window decaying to 0 at reset)."""
    return tuple((b.label, round(b.pct)) for b in bars)


# Faces whose caption is superseded by the running tool's name (the working family
# — plus planning, where a running tool is still the more informative caption).
_TOOL_CAPTION_FACES = frozenset(
    {"working", "working_read", "working_edit", "working_run", "working_web",
     "planning"})


def _caption(face: str, tool: str | None) -> str:
    """Caption under the creature. While a tool is actively running, name it
    (e.g. 'Bash…') instead of the generic 'working…'."""
    if tool and face in _TOOL_CAPTION_FACES:
        return f"{tool}…"
    return STATE_CAPTIONS.get(face, "—")


class MascotWindow:
    """One mascot window (Toplevel) per session, drawn on a single Canvas."""

    def __init__(self, manager_root: tk.Tk, session_id: str, state: dict[str, Any], index: int,
                 host: PetHost) -> None:
        self.session_id = session_id
        self.state = state
        # Simple hook-visualiser mode (pet disabled): no tooltip, no tap-to-pet/hearts.
        # The mood faces + food/tired emotes fall out on their own (the manager never
        # pushes a pet mood); only these card-local affordances need an explicit gate.
        # `pet_enabled` is fixed at startup, so snapshot it; the host serves the rest.
        self._host = host
        self._pet_enabled = host.pet_enabled
        self._sig: tuple | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._alive = True
        self._hidden = False
        self._manager_root = manager_root
        self._bubble: BubbleWindow | None = None
        # The global pet (pushed by the manager) drives the idle-face mood and the
        # hover tooltip. None until the first push -> a neutral "content" mood.
        self._pet_data: dict[str, Any] | None = None
        self._tooltip: StatsTooltip | None = None

        # effective-state / shake bookkeeping (must exist before first compute).
        # The five expiry timers now live in the overlay (see `self._overlay`,
        # built once the raw state is known below); only the blink *scheduler*
        # clock stays here, as it drives when to ASK the overlay for a blink.
        self._next_blink = 0.0
        # The rising-particle field (hearts from a pet, food/zzz mood emotes) owns
        # the lifetime math and the two formerly-parallel state lists.
        self._particles = particles.Particles(_PARTICLE_KINDS, panel_fill=_PANEL_FILL_RGB)
        self._next_emote = 0.0
        self._press_pos: tuple[int, int] | None = None
        self._last_shake_pos: tuple[int, int] | None = None
        self._last_move: tuple[int, int] | None = None
        self._reversals: list[float] = []
        # Attention-shake: the Shake seam owns the intensity ramp, the amplitude/
        # frequency derivation and the absolute-from-rest offset (it captures the
        # resting position once when a shake begins; every frame then sets an
        # absolute geometry of rest+offset — see mascot/shake.py for why). The
        # last applied offset is tracked here only to skip redundant geometry calls.
        self._shake_offset: tuple[int, int] = (0, 0)

        raw = state.get("state", "idle")
        self._overlay = overlay_mod.Overlay(_OVERLAY_CONFIG, raw=raw, now=time.time())
        self._effective_state = self._compute_effective_state(time.time())
        self._display_face = self._compute_display_face(time.time())
        self._anim_t0 = time.time()
        # The shake's phase clock is aligned with the animation clock so the sway is
        # continuous (the original derived its phase from ``now - self._anim_t0``).
        self._shake = shake.Shake(_SHAKE_CONFIG, t0=self._anim_t0)

        # canvas item ids we animate / restyle in place
        self._border_id: int | None = None
        self._panel_id: int | None = None      # the filled panel; restyled for the effort tint
        self._info_id: int | None = None
        self._info_text_val = ""
        self._started = state.get("started")
        self._bob_y = 0.0
        # The resolved effort (per-session state -> global settings fallback) drives
        # the panel tint. Computed here so the first _render below can use it.
        self._effort_display = self._resolve_effort()
        # The account-global usage snapshot (pushed by the manager) drives the two
        # bottom bars. None until the first push -> an empty row.
        self._usage: dict[str, Any] | None = None
        self._usage_bars: list[usage_mod.UsageBar] = []

        # IMPORTANT: extra windows must be Toplevel, not Tk(). Only one Tk root.
        # Outside the rounded panel is painted with this bg; when transparency is
        # on it's the chroma key, so only the rounded card shows.
        use_chroma = config.TRANSPARENT_BG and _SUPPORTS_CHROMA
        win_bg = CHROMA if use_chroma else WIN_BG

        self.root = tk.Toplevel(manager_root)
        self.root.title(f"Mascot - {session_id[:8]}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=win_bg)
        if use_chroma:
            try:
                self.root.attributes("-transparentcolor", CHROMA)
            except tk.TclError:
                pass  # fall back to an opaque backdrop if unsupported
        self.root.geometry(f"{CARD_W}x{CARD_H}")

        self.canvas = tk.Canvas(
            self.root, width=CARD_W, height=CARD_H,
            bg=win_bg, highlightthickness=0, bd=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<Button-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self.canvas.bind("<Enter>", self._on_enter)   # hover -> pet status tooltip
        self.canvas.bind("<Leave>", self._on_leave)

        # A small paw button that opens the Pet window (a child of the toplevel, so
        # it survives the canvas's full redraws). Only shown when wired by the manager.
        self._pet_btn: tk.Button | None = None
        self._paw_img = None
        if self._pet_enabled:
            # A pixel-art paw button (bigger than the old glyph), top-left of the card.
            self._paw_img = ui_icons.photo(self.root, "paw", px=max(2, _s(2)))
            self._pet_btn = tk.Button(
                self.root, image=self._paw_img, command=self._open_pet, cursor="hand2",
                bd=0, highlightthickness=0, relief="flat", takefocus=0,
                bg=PANEL_FILL, activebackground=PANEL_EDGE,
            )
            self._pet_btn.place(x=PANEL_MARGIN + _s(5), y=PANEL_MARGIN + _s(5), anchor="nw")

        self._place_initial(index)
        self._render()
        self._sync_bubble(state.get("notify"))
        self.root.after(config.ANIM_INTERVAL_MS, self._animate)

    # --- drawing ----------------------------------------------------------
    def _render(self) -> None:
        """Redraw the whole card. The Canvas widget itself persists, so the drag
        binding survives — safe to call mid-drag and on any visible change."""
        c = self.canvas
        c.delete("all")
        accent = _accent(self._display_face)
        panel = self._panel_color(time.time() - self._anim_t0)

        # rounded panel (tinted by the session's effort) + accent border (the
        # border pulses while waiting). The panel id is kept so the effort tint
        # can be restyled in place on the animate clock.
        self._panel_id = round_rect(c, PANEL_MARGIN, PANEL_MARGIN, CARD_W - PANEL_MARGIN,
                                    CARD_H - PANEL_MARGIN, PANEL_RADIUS, fill=panel, outline="")
        self._border_id = round_rect(
            c, PANEL_MARGIN, PANEL_MARGIN, CARD_W - PANEL_MARGIN, CARD_H - PANEL_MARGIN,
            PANEL_RADIUS, fill="", outline=accent, width=2,
        )

        view = self._pet_view()
        _draw_creature(c, CREATURE_CX, CREATURE_CY, self._display_face, accent, view)
        self._bob_y = 0.0

        c.create_text(CREATURE_CX, CAPTION_Y,
                      text=_caption(self._display_face, self.state.get("tool")),
                      font=CAPTION_FONT, fill=accent)

        self._draw_badges(c)

        cwd = self.state.get("cwd", "")
        label_text = Path(cwd).name if cwd else self.session_id[:8]
        c.create_text(CREATURE_CX, LABEL_Y, text=label_text,
                      font=LABEL_FONT, fill=LABEL_FG, width=CARD_W - 16)

        # model · session duration (duration ticks live in _animate)
        self._info_text_val = self._info_line(time.time())
        self._info_id = c.create_text(CREATURE_CX, INFO_Y, text=self._info_text_val,
                                      font=INFO_FONT, fill=INFO_FG)

        self._draw_usage(c)

        # Keep the paw button on the tinted panel (it's a real widget, not canvas).
        if self._pet_btn is not None:
            self._pet_btn.configure(bg=panel)

        self._sig = (*_render_sig(self.state, self._effective_state, self._display_face,
                                  view, self._effort_display), _usage_sig(self._usage_bars))

    def _info_line(self, now: float) -> str:
        """'<model> · <duration>' — either part omitted if unknown."""
        parts = []
        model = _short_model(self.state.get("model", ""))
        if model:
            parts.append(model)
        if self._started:
            parts.append(_format_duration(now - self._started))
        return "   ·   ".join(parts)

    def _draw_badges(self, c: tk.Canvas) -> None:
        """Draw each sub-agent as a small version of the mascot (purple sparkle)."""
        subs = (self.state.get("subagents") or [])[:4]
        if not subs:
            return
        accent = _hex(config.SUBAGENT_COLOR)
        total = (len(subs) - 1) * BADGE_GAP
        x0 = CREATURE_CX - total / 2
        for i in range(len(subs)):
            x = x0 + i * BADGE_GAP
            sprite_pixel.draw_creature(c, x, BADGE_Y, "working", accent, MINI_PIXEL_PX,
                                       tag="subagent")

    def _draw_usage(self, c: tk.Canvas) -> None:
        """Draw the 5h / weekly usage bars at the bottom of the card (nothing when
        there's no usage data — API-key users, or before the first snapshot). Each
        bar: a short label, a track, a traffic-light fill, and a NN% readout."""
        for i, bar in enumerate(self._usage_bars):
            top = USAGE_ROW_TOP + i * (USAGE_BAR_H + USAGE_BAR_GAP)
            mid = top + USAGE_BAR_H / 2
            c.create_text(USAGE_LABEL_X, mid, text=bar.label, anchor="e",
                          font=USAGE_FONT, fill=LABEL_FG)
            c.create_rectangle(USAGE_BAR_X0, top, USAGE_BAR_X1, top + USAGE_BAR_H,
                               fill=USAGE_TRACK, outline="")
            frac = max(0.0, min(1.0, bar.pct / 100.0))
            if frac > 0:
                fill_x = USAGE_BAR_X0 + (USAGE_BAR_X1 - USAGE_BAR_X0) * frac
                c.create_rectangle(USAGE_BAR_X0, top, fill_x, top + USAGE_BAR_H,
                                   fill=_hex(usage_mod.bar_color(bar.pct)), outline="")
            c.create_text(USAGE_PCT_X, mid, text=f"{round(bar.pct)}%", anchor="e",
                          font=USAGE_FONT, fill=INFO_FG)

    # --- positioning ------------------------------------------------------
    def _place_initial(self, index: int) -> None:
        """Anchor the card to the bottom-right of the *primary* monitor's work
        area, stacking extra sessions upward, and clamp so it can never land
        off-screen (wrong monitor / behind the taskbar / too many stacked)."""
        area = osplatform.choose_work_area(
            config.HOME_MONITOR, osplatform.enumerate_work_areas(),
            osplatform.primary_work_area(),
        )
        if area is not None:
            ax, ay, aw, ah = area
        else:  # non-Windows / lookup failed: fall back to Tk's screen metrics
            ax, ay = 0, 0
            aw, ah = self.root.winfo_screenwidth(), self.root.winfo_screenheight()

        x = ax + aw - CARD_W - 20
        y = ay + ah - (CARD_H + 12) * (index + 1) - 20
        x = max(ax, min(x, ax + aw - CARD_W))
        y = max(ay, min(y, ay + ah - CARD_H))
        self.root.geometry(f"+{x}+{y}")

    # --- drag -------------------------------------------------------------
    def _on_drag_start(self, event: tk.Event) -> None:
        # Undo any active attention-shake first so the grab point maps to the
        # card's true resting position (no jump as the shake is removed).
        self._reset_shake_offset()
        self._on_leave(event)   # hide the hover tooltip while dragging
        self._press_pos = (event.x_root, event.y_root)
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())
        self._last_shake_pos = None
        self._last_move = None
        self._reversals = []

    def _on_drag_motion(self, event: tk.Event) -> None:
        if self._drag_offset is not None:
            x = event.x_root - self._drag_offset[0]
            y = event.y_root - self._drag_offset[1]
            self.root.geometry(f"+{x}+{y}")
            self._track_shake(event.x_root, event.y_root)

    def _on_drag_end(self, event: tk.Event) -> None:
        moved = 0.0
        if self._press_pos is not None:
            moved = math.hypot(event.x_root - self._press_pos[0],
                               event.y_root - self._press_pos[1])
        self._drag_offset = None
        self._press_pos = None
        # A tap (press+release without a real drag or shake) pets the mascot. In
        # simple mode the card is a read-only indicator, so a tap is a dead tap.
        now = time.time()
        raw = self.state.get("state", "idle")
        if (self._pet_enabled and moved < PET_TAP_MAX_DIST and not self._overlay.is_dizzy(now)
                and raw not in ("waiting", "dead")):
            self._pet(now)
            pet_actions.pet_tap(self._host, now)   # a pet earns a small coin trickle

    # --- pet hearts -------------------------------------------------------
    def celebrate(self) -> None:
        """Public hook: play the happy reaction + hearts (e.g. when the pet is fed
        or played with in the Pet window), so care feels consistent with petting."""
        self._pet(time.time())

    def _open_pet(self) -> None:
        """The on-card paw button: ask the host to open the Pet window."""
        self._host.open_pet()

    def _pet(self, now: float) -> None:
        """Reward a tap with a happy face and a few rising pixel hearts."""
        self._overlay.note_celebrate(now)
        self._emit_hearts(now)
        self._refresh_render(now)

    def _emit_hearts(self, now: float) -> None:
        """Spawn a small staggered burst of hearts at the creature's upper-right —
        the same origin as the mood emotes, drifting up-and-right."""
        origin = (float(CREATURE_CX + _s(20)), float(CREATURE_CY - _s(14)))
        for _ in range(3):
            jitter = (origin[0] + random.uniform(-4, 6), origin[1])
            self._particles.emit("heart", jitter, now,
                                  stagger_s=0.15, drift_range=(2.0, 12.0))

    # --- mood emotes (food / zzz popups) ----------------------------------
    def _schedule_emote(self, now: float) -> None:
        """Pop a mood emote every few seconds while the pet is hungry/sleepy. The
        kind follows the effective state, so it only shows in the matching mood."""
        kind = _EMOTE_FOR_STATE.get(self._effective_state)
        if kind is None:
            self._next_emote = 0.0
            return
        if self._next_emote == 0.0:
            self._next_emote = now + random.uniform(EMOTE_MIN_GAP_S, EMOTE_MAX_GAP_S)
        elif now >= self._next_emote:
            # Upper-right of the creature, drifting up-and-right into empty panel.
            origin = (float(CREATURE_CX + _s(24) + random.uniform(-2, 6)),
                      float(CREATURE_CY - _s(20)))
            self._particles.emit(kind, origin, now, drift_range=(2.0, 9.0))
            self._next_emote = now + random.uniform(EMOTE_MIN_GAP_S, EMOTE_MAX_GAP_S)

    def _track_shake(self, x_root: int, y_root: int) -> None:
        """Count rapid direction reversals on any axis; enough -> go dizzy."""
        if self._last_shake_pos is None:
            self._last_shake_pos = (x_root, y_root)
            return
        dx = x_root - self._last_shake_pos[0]
        dy = y_root - self._last_shake_pos[1]
        if math.hypot(dx, dy) < SHAKE_MIN_DIST:
            return
        self._last_shake_pos = (x_root, y_root)
        if self._last_move is not None:
            dot = dx * self._last_move[0] + dy * self._last_move[1]
            if dot < 0:
                now = time.time()
                self._reversals = [t for t in self._reversals if t >= now - SHAKE_WINDOW_S]
                self._reversals.append(now)
                if len(self._reversals) >= SHAKE_REVERSALS:
                    self._trigger_dizzy(now)
                    self._reversals = []
                    self._last_move = None
                    return
        self._last_move = (dx, dy)

    def _trigger_dizzy(self, now: float) -> None:
        self._overlay.note_dizzy(now)
        self._refresh_render(now)

    # --- effective state --------------------------------------------------
    def _compute_effective_state(self, now: float) -> str:
        """Ask the overlay for the displayed state: it owns this card's live timers
        and thresholds and delegates to the pure core, layering the pet's mood
        (idle-only) on top."""
        mood = pet_logic.mood(self._pet_data) if self._pet_data else "content"
        return self._overlay.effective(
            self.state.get("state", "idle"), now, ts=self.state.get("ts"), mood=mood)

    def set_pet(self, pet: dict[str, Any]) -> None:
        """Receive the latest global pet from the manager: drives the idle-face mood
        and the hover tooltip. Cheap — the next animate tick picks up any mood change."""
        self._pet_data = pet
        if self._tooltip is not None:
            self._tooltip.set_pet(pet)

    def set_usage(self, snapshot: dict[str, Any] | None) -> None:
        """Receive the latest account-global usage snapshot from the manager; the
        next animate tick recomputes the bars (with reset decay) and repaints if
        they changed. Cheap — like set_pet, this only stores the data."""
        self._usage = snapshot

    # --- state ------------------------------------------------------------
    def update_state(self, state: dict[str, Any], now: float | None = None) -> None:
        if now is None:
            now = time.time()
        prev_raw = self.state.get("state", "idle")
        self.state = state
        if state.get("started"):
            self._started = state["started"]

        raw = state.get("state", "idle")
        # Celebrate briefly when Claude finishes an active turn (working/thinking
        # -> idle). Not on waiting->idle (the user just answered), dead, or a
        # stumble (a turn that died on an API error is nothing to cheer).
        if effective_state.should_celebrate(prev_raw, raw, bool(state.get("stumbled"))):
            self._overlay.note_celebrate(now)
        # Track the raw-state clocks (how long idle -> dozing; how long an attention
        # prompt has gone unanswered -> shake/glare).
        self._overlay.note_raw(raw, now)

        self._refresh_render(now)
        self._sync_bubble(state.get("notify"))

    def _refresh_render(self, now: float) -> None:
        """Recompute effective state + display face; redraw only if the visible
        content changed."""
        self._effective_state = self._compute_effective_state(now)
        self._display_face = self._compute_display_face(now)
        self._effort_display = self._resolve_effort()
        self._usage_bars = usage_mod.usage_view(self._usage, now)
        view = self._pet_view()
        new_sig = (*_render_sig(self.state, self._effective_state, self._display_face,
                                view, self._effort_display), _usage_sig(self._usage_bars))
        if new_sig == self._sig:
            return
        self._render()

    def _resolve_effort(self) -> str:
        """The effort level to display: the session's per-turn level (from the
        state file) wins, falling back to Claude's global ``effortLevel``."""
        return effort_mod.resolve(self.state.get("effort", ""), effort_mod.settings_effort())

    def _panel_color(self, t: float = 0.0) -> str:
        """The card panel fill for the current effort at animation time ``t`` — a
        subtle tint in the effort's own color (xhigh waves purple, max cycles the
        rainbow). The gravestone (dead) suppresses the tint so a finished session
        stays sombre; unknown/absent effort keeps the default panel."""
        if self._display_face == "dead":
            return PANEL_FILL
        fill = effort_mod.panel_fill(self._effort_display, _PANEL_FILL_RGB, t)
        return _hex(fill) if fill is not None else PANEL_FILL

    def _effort_animates(self) -> bool:
        """True while the current effort has a moving background (xhigh/max) and
        the card isn't a gravestone — the only case that needs per-frame restyle."""
        return (self._display_face != "dead"
                and effort_mod.border_accent(self._effort_display, 0.0) is not None)

    def _pet_view(self) -> PetView:
        """The pet's look (stage/hat/flourish) for the sprite draw, via the pure
        `pet_view` projection. Two edge looks bypass it: simple hook-visualiser mode
        (pet disabled) shows the fixed life stage picked in Settings, and before the
        first pet push there's no pet yet (the baby). Both are bare, no flourish."""
        if not self._pet_enabled:
            return PetView(config.SIMPLE_STAGE, None, False, "content")
        if not self._pet_data:
            return PetView("baby", None, False, "content")
        return pet_view(self._pet_data, now=time.time())

    def _compute_display_face(self, now: float) -> str:
        """The face to draw for the current effective state (per-tool working
        variants, plan-mode planning, the brief post-stumble "oops"). Purely
        visual — captions/emotes key off the effective state where they should."""
        stumbled_recent = (bool(self.state.get("stumbled"))
                           and now - (self.state.get("ts") or 0.0) < STUMBLE_FACE_S)
        return effective_state.display_face(
            self._effective_state, tool=self.state.get("tool"),
            permission_mode=self.state.get("permission_mode", ""),
            stumbled_recent=stumbled_recent)

    def _schedule_blink(self, now: float) -> None:
        """Trigger an occasional blink, but only while genuinely idle (not busy,
        celebrating, or already dozing). The blink itself is just a brief
        `idle_blink` effective state picked up by the next render."""
        if (self.state.get("state", "idle") != "idle"
                or self._effective_state not in ("idle", "idle_blink")):
            self._next_blink = 0.0
            return
        if self._next_blink == 0.0:
            self._next_blink = now + random.uniform(BLINK_MIN_GAP_S, BLINK_MAX_GAP_S)
        elif now >= self._next_blink:
            self._overlay.note_blink(now)
            self._next_blink = (now + BLINK_DURATION_S
                                + random.uniform(BLINK_MIN_GAP_S, BLINK_MAX_GAP_S))

    # --- speech bubble ----------------------------------------------------
    def _sync_bubble(self, notify: dict[str, Any] | None) -> None:
        if notify:
            message = notify.get("message") or "Claude needs your attention"
            if self._bubble is None:
                self._bubble = BubbleWindow(self._manager_root, message)
                self._reposition_bubble()
                if self._hidden:                 # cards are hidden via the tray
                    self._bubble.top.withdraw()
            else:
                self._bubble.set_message(message)
        elif self._bubble is not None:
            self._bubble.destroy()
            self._bubble = None

    def _card_bounds(self) -> tuple[int, int, int, int]:
        """Work area of the monitor the card currently sits on, so popups clamp to
        the same screen after the card is dragged across monitors. Falls back to
        Tk's (primary) screen metrics off Windows or on any lookup failure."""
        cx, cy = self.root.winfo_x(), self.root.winfo_y()
        return osplatform.monitor_work_area_at(cx, cy) or (
            0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        )

    def _reposition_bubble(self) -> None:
        if self._bubble is None:
            return
        try:
            self._bubble.place_above(
                self.root.winfo_x(), self.root.winfo_y(), CARD_W, self._card_bounds(),
            )
        except tk.TclError:
            pass

    # --- hover tooltip (pet status) ---------------------------------------
    def _on_enter(self, _event: tk.Event) -> None:
        """Show the pet-status tooltip on hover (not while hidden or mid-drag). The
        tooltip is pet status, so it's suppressed in simple hook-visualiser mode."""
        if not self._pet_enabled:
            return
        if self._hidden or self._drag_offset is not None or self._tooltip is not None:
            return
        self._tooltip = StatsTooltip(self._manager_root, self._pet_data)
        self._reposition_tooltip()

    def _on_leave(self, _event: tk.Event) -> None:
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def _reposition_tooltip(self) -> None:
        if self._tooltip is None:
            return
        try:
            self._tooltip.place_beside(
                self.root.winfo_x(), self.root.winfo_y(), CARD_W, CARD_H, self._card_bounds(),
            )
        except tk.TclError:
            pass

    # --- animation --------------------------------------------------------
    def _animate(self) -> None:
        """Cheap ~25fps loop: bob the creature, pulse the border while waiting."""
        if not self._alive:
            return
        try:
            now = time.time()
            elapsed = now - self._anim_t0

            # Clears the dizzy/celebrate face when it expires; flips idle→sleeping;
            # drives the occasional idle blink.
            self._refresh_render(now)
            self._schedule_blink(now)

            # Subtle vertical float — move the whole creature group.
            phase = (elapsed / BOB_PERIOD_S) * 2 * math.pi
            target = -(math.sin(phase) + 1) / 2 * BOB_AMPLITUDE  # 0..-amplitude
            if self._effective_state == "happy":
                target = -abs(math.sin(elapsed * 9.0)) * BOB_AMPLITUDE * 2.0  # excited hop
            elif self._effective_state == "dead":
                target = 0.0  # a gravestone sits still; it does not float
            self.canvas.move("creature", 0, target - self._bob_y)
            self._bob_y = target

            # Mood popups (food when hungry, "Z" when sleepy), every few seconds —
            # scheduled before the field is drawn so a freshly emitted emote shows
            # this frame, as before.
            self._schedule_emote(now)

            # Rising particles: pet hearts + the mood emotes, one shared lifetime
            # path (mascot/particles.py). Repaints the live ones, drops the expired.
            self._particles.draw(self.canvas, now)

            # Effort background animation: xhigh waves purple, max cycles the
            # rainbow. Cheap in-place restyle of the existing panel item (never a
            # full redraw) on this same clock — only the two animated levels move.
            if self._panel_id is not None and self._effort_animates():
                fill = self._panel_color(elapsed)
                self.canvas.itemconfig(self._panel_id, fill=fill)
                if self._pet_btn is not None:
                    self._pet_btn.configure(bg=fill)

            # Border: the waiting attention pulse always wins; otherwise the two
            # animated effort levels tint the border in their live color.
            if self._border_id is not None:
                if self.state.get("state", "idle") == "waiting":
                    phase = (elapsed / PULSE_PERIOD_S) * 2 * math.pi
                    t = (math.sin(phase) + 1) / 2
                    color = _hex(_lerp((42, 45, 59), config.STATE_COLORS["waiting"], t))
                    self.canvas.itemconfig(self._border_id, outline=color)
                elif self._effort_animates():
                    accent = effort_mod.border_accent(self._effort_display, elapsed)
                    if accent is not None:
                        self.canvas.itemconfig(self._border_id, outline=_hex(accent))

            # Tick the live session-duration text (cheap: only on change).
            if self._info_id is not None:
                new_info = self._info_line(now)
                if new_info != self._info_text_val:
                    self.canvas.itemconfig(self._info_id, text=new_info)
                    self._info_text_val = new_info

            # Shake the whole card when a prompt has been ignored too long. Done
            # before the bubble reposition so the speech bubble shakes along too.
            self._apply_attention_shake(now)

            if self._bubble is not None:
                self._reposition_bubble()
            if self._tooltip is not None:    # follow the card (incl. shake)
                self._reposition_tooltip()
        except tk.TclError:
            return

        self.root.after(config.ANIM_INTERVAL_MS, self._animate)

    # --- attention shake --------------------------------------------------
    def _apply_attention_shake(self, now: float) -> None:
        """Jostle the card while a prompt sits unanswered; the longer it's been
        ignored, the wider and faster the shake — up to a frantic maximum."""
        if self._drag_offset is not None:
            return  # the user is holding it; don't fight the drag
        elapsed = self._overlay.waiting_elapsed(now)
        if self.state.get("state", "idle") != "waiting" or elapsed is None:
            self._reset_shake_offset()  # not waiting -> settle back to rest
            return
        if elapsed < WAITING_SHAKE_AFTER_S:
            self._reset_shake_offset()  # still within the grace window
            return

        ox, oy = self._shake.offset(now, elapsed)
        self._set_shake_offset(ox, oy)

    def _set_shake_offset(self, ox: int, oy: int) -> None:
        """Apply the Shake seam's (ox, oy) as an *absolute* geometry of rest+(ox, oy).

        The seam holds the resting position (captured here, once, the moment the
        shake begins) and the offset math; the card just reads ``winfo_x/y`` to seed
        the anchor and pushes the geometry — see mascot/shake.py for why this avoids
        the old Windows delta-drift that walked a frantic card off-screen."""
        if (ox, oy) == self._shake_offset:
            return
        if not self._shake.is_shaking:    # starting to shake: remember where it rests
            try:
                self._shake.begin((self.root.winfo_x(), self.root.winfo_y()))
            except tk.TclError:
                return
        rest = self._shake.rest_pos
        assert rest is not None           # begin() succeeded, so rest is captured
        try:
            self.root.geometry(f"+{rest[0] + ox}+{rest[1] + oy}")
        except tk.TclError:
            return
        self._shake_offset = (ox, oy)

    def _reset_shake_offset(self) -> None:
        """Settle the card back onto its captured resting position (zero shake)."""
        if self._shake_offset == (0, 0):
            return
        rest = self._shake.rest_pos
        if rest is not None:
            try:
                self.root.geometry(f"+{rest[0]}+{rest[1]}")
            except tk.TclError:
                pass
        self._shake_offset = (0, 0)
        self._shake.end()

    def set_hidden(self, hidden: bool) -> None:
        """Withdraw or restore this card (and its speech bubble) for the tray's
        'show / hide cards' toggle. Windows drops the always-on-top flag when a
        withdrawn window is shown again, so re-assert it after deiconify."""
        self._hidden = hidden
        if hidden and self._tooltip is not None:   # no hover tooltip while hidden
            self._tooltip.destroy()
            self._tooltip = None
        try:
            if hidden:
                self.root.withdraw()
                if self._bubble is not None:
                    self._bubble.top.withdraw()
            else:
                self.root.deiconify()
                self.root.attributes("-topmost", True)
                if self._bubble is not None:
                    self._bubble.top.deiconify()
                    self._bubble.top.attributes("-topmost", True)
        except tk.TclError:
            pass

    def close(self) -> None:
        self._alive = False
        if self._bubble is not None:
            self._bubble.destroy()
            self._bubble = None
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None
        self.root.destroy()
