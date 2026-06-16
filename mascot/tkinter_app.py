"""Tkinter mascot widget.

One window per Claude session. Native, built-in tkinter only — no external deps.
The mascot is a custom character drawn on a Canvas (see `sprite_pixel.py`), not
an emoji or image asset. Run with: python run_mascot.py  (or: python -m mascot)
"""
from __future__ import annotations

import math
import random
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from . import config, icon, osplatform, single_instance, sprite_pixel, sprite_smooth, state_store

# Mascot art modules, selectable via config.ART_STYLE. The smooth blob is kept
# on the side; the pixel creature is the default.
_ART = {"pixel": sprite_pixel, "smooth": sprite_smooth}

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pythonw() -> Path:
    """pythonw.exe (no console window) next to the running interpreter, if any."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


def _draw_gravestone(c, cx, cy) -> None:
    """A simple tombstone, drawn with canvas primitives (art-style independent)."""
    hw = _s(24)
    top = cy - _s(34)
    bottom = cy + _s(28)
    # grassy mound at the base
    c.create_oval(cx - _s(34), bottom - _s(5), cx + _s(34), bottom + _s(9),
                  fill=GRAVE_GROUND, outline="", tags="creature")
    # rounded-top stone tablet
    round_rect(c, cx - hw, top, cx + hw, bottom, _s(16),
               fill=GRAVESTONE_FILL, outline=GRAVESTONE_EDGE, width=_s(2), tags="creature")
    # engraved RIP
    c.create_text(cx, cy - _s(2), text="R.I.P", fill=GRAVESTONE_ENGRAVE,
                  font=_font(10, "bold"), tags="creature")


def _draw_creature(c, cx, cy, state, accent) -> None:
    """Draw the mascot using the configured art style, scaled to the widget size."""
    if state == "dead":
        _draw_gravestone(c, cx, cy)
        return
    size = CREATURE_PX if config.ART_STYLE == "pixel" else CREATURE_R
    _ART.get(config.ART_STYLE, sprite_pixel).draw_creature(c, cx, cy, state, accent, size)


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
    "thinking": "thinking…",
    "working": "working…",
    "waiting": "needs you!",
    "waiting_angry": "needs you!",   # angry variant once the card starts shaking
    "sleeping": "zzz…",
    "dizzy": "whoa…",
    "happy": "yay!",
    "dead": "out of usage",
}

# --- card geometry / palette ----------------------------------------------
# Every measurement below is authored at the "small" size, then multiplied by
# config.UI_SCALE so "medium"/"large" scale the whole card uniformly.
_SCALE = config.UI_SCALE


def _s(value: float) -> int:
    """Scale a base (small-size) measurement by the configured widget size."""
    return max(1, round(value * _SCALE))


def _font(size: int, *opts: str) -> tuple:
    """A Segoe UI font tuple whose point size tracks the widget size."""
    return ("Segoe UI", _s(size), *opts)


CARD_W = _s(158)
CARD_H = _s(196)
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
CREATURE_CY = _s(64)
CREATURE_PX = _s(5)         # pixel size of the main creature (pixel art)
CREATURE_R = _s(30)         # body radius of the main creature (smooth art)

CAPTION_Y = _s(114)
BADGE_Y = _s(136)
LABEL_Y = _s(160)
INFO_Y = _s(178)            # model · session duration

CAPTION_FONT = _font(9, "bold")
LABEL_FONT = _font(7)
INFO_FONT = _font(7)

LABEL_FG = "#8b8fa3"
INFO_FG = "#6b6f82"
BADGE_GAP = _s(26)          # spacing between sub-agent mini-mascots
MINI_PIXEL_PX = _s(1)       # pixel size for a mini sub-agent (pixel art) -> ~16px
MINI_SMOOTH_R = _s(7)       # body radius for a mini sub-agent (smooth art)

# Animation
BOB_AMPLITUDE = _s(4)
BOB_PERIOD_S = 2.0
PULSE_PERIOD_S = 1.2

# Comic speech bubble (shown above the card while Claude needs the user).
BUBBLE_W = _s(196)
BUBBLE_PAD = _s(10)
BUBBLE_GAP = _s(6)
BUBBLE_FONT = _font(9)
BUBBLE_FILL = "#fdf6e3"
BUBBLE_TEXT = "#1c1e26"
BUBBLE_MAX_CHARS = 160

# Stats tooltip — a small dark card shown beside the mascot on hover, surfacing
# the session's running counters (prompts · tools · agents · uptime).
TOOLTIP_FILL = "#252735"
TOOLTIP_TEXT = "#cdd2e6"
TOOLTIP_EDGE = "#3a3d4f"
TOOLTIP_FONT = _font(7)
TOOLTIP_PAD = _s(9)
TOOLTIP_GAP = _s(6)

# Shake-to-dizzy easter egg.
SHAKE_MIN_DIST = 7
SHAKE_WINDOW_S = 0.7
SHAKE_REVERSALS = 4
DIZZY_DURATION_S = 2.0

# Celebrate (happy) reaction: brief joy when Claude finishes a turn, and when the
# mascot is petted. A widget-side effective state, like dizzy/sleeping.
CELEBRATE_DURATION_S = 1.5

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

# Stall watchdog: a turn that ends abnormally (notably a usage/session-limit hit)
# fires no terminating hook, so the heartbeat freezes mid-`thinking`. Rather than
# look frozen forever, fall the *display* back to idle once thinking has gone this
# long without any new event. Generous, so a long pure-reasoning turn isn't cut off.
THINKING_STALL_S = 180.0

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


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


# Gravestone palette derived from the shared "dead" state color so it tracks
# config.STATE_COLORS; edge/engrave are progressively darker shades of it. The
# grassy mound is its own hue (not a state color).
_BLACK = (0, 0, 0)
_GRAVE_BASE = config.STATE_COLORS["dead"]
GRAVESTONE_FILL = _hex(_GRAVE_BASE)
GRAVESTONE_EDGE = _hex(_lerp(_GRAVE_BASE, _BLACK, 0.35))
GRAVESTONE_ENGRAVE = _hex(_lerp(_GRAVE_BASE, _BLACK, 0.6))
GRAVE_GROUND = "#39473b"


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


def _render_sig(state: dict[str, Any], effective_state: str) -> tuple:
    """Signature of the *visible* content (excludes the `ts` heartbeat)."""
    subs = tuple((s.get("type") or "?") for s in (state.get("subagents") or []))
    return (effective_state, subs, state.get("cwd", ""))


class BubbleWindow:
    """A speech bubble shown above a mascot while Claude needs the user.

    A small opaque, frameless Toplevel (Windows `-transparentcolor` layered
    windows render unreliably with `overrideredirect`, so we avoid them).
    """

    def __init__(self, manager_root: tk.Tk, message: str) -> None:
        self.message = ""
        self._width = BUBBLE_W
        self._height = 0

        self.top = tk.Toplevel(manager_root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=BUBBLE_TEXT)  # 2px dark border via padding below

        self.label = tk.Label(
            self.top,
            bg=BUBBLE_FILL,
            fg=BUBBLE_TEXT,
            font=BUBBLE_FONT,
            justify="center",
            wraplength=BUBBLE_W - 2 * BUBBLE_PAD,
            padx=BUBBLE_PAD,
            pady=BUBBLE_PAD,
        )
        self.label.pack(padx=2, pady=2)
        self.set_message(message)

    def set_message(self, message: str) -> None:
        message = (message or "Claude needs your attention")[:BUBBLE_MAX_CHARS]
        if message == self.message:
            return
        self.message = message
        self.label.config(text=message)
        self.top.update_idletasks()
        self._width = self.top.winfo_reqwidth()
        self._height = self.top.winfo_reqheight()

    def place_above(self, card_x: int, card_y: int, card_w: int, screen_w: int) -> None:
        x = card_x + card_w // 2 - self._width // 2
        x = max(0, min(x, screen_w - self._width))
        y = card_y - self._height - BUBBLE_GAP
        if y < 0:
            y = card_y
        self.top.geometry(f"+{x}+{y}")

    def destroy(self) -> None:
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class StatsTooltip:
    """A small dark tooltip shown beside a card while the pointer hovers it,
    surfacing the session's running counters. Mirrors BubbleWindow's lifecycle."""

    def __init__(self, manager_root: tk.Tk, text: str) -> None:
        self._width = 0
        self._height = 0
        self.top = tk.Toplevel(manager_root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=TOOLTIP_EDGE)  # 1px border via the padding below
        self.label = tk.Label(
            self.top, bg=TOOLTIP_FILL, fg=TOOLTIP_TEXT, font=TOOLTIP_FONT,
            justify="center", padx=TOOLTIP_PAD, pady=_s(5),
        )
        self.label.pack(padx=1, pady=1)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        if text == self.label.cget("text"):
            return
        self.label.config(text=text)
        self.top.update_idletasks()
        self._width = self.top.winfo_reqwidth()
        self._height = self.top.winfo_reqheight()

    def place_beside(self, card_x: int, card_y: int, card_w: int, card_h: int,
                     screen_w: int) -> None:
        x = card_x - self._width - TOOLTIP_GAP          # prefer the left of the card
        if x < 0:
            x = card_x + card_w + TOOLTIP_GAP           # no room left -> go right
        x = max(0, min(x, screen_w - self._width))
        y = card_y + (card_h - self._height) // 2
        self.top.geometry(f"+{x}+{y}")

    def destroy(self) -> None:
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class MascotWindow:
    """One mascot window (Toplevel) per session, drawn on a single Canvas."""

    def __init__(self, manager_root: tk.Tk, session_id: str, state: dict[str, Any], index: int) -> None:
        self.session_id = session_id
        self.state = state
        self._sig: tuple | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._alive = True
        self._hidden = False
        self._manager_root = manager_root
        self._bubble: BubbleWindow | None = None
        self._tooltip: StatsTooltip | None = None

        # effective-state / shake bookkeeping (must exist before first compute)
        self._dizzy_until = 0.0
        self._celebrate_until = 0.0
        self._blink_until = 0.0
        self._next_blink = 0.0
        self._hearts: list[dict[str, float]] = []
        self._press_pos: tuple[int, int] | None = None
        self._last_shake_pos: tuple[int, int] | None = None
        self._last_move: tuple[int, int] | None = None
        self._reversals: list[float] = []
        # Attention-shake bookkeeping: when the current "waiting" began, and the
        # window offset we've currently applied (so we can shake relative to wherever
        # the card rests — and settle it back — without drifting). The resting
        # position is captured once when a shake begins; every frame then sets an
        # absolute geometry of rest+offset (see _set_shake_offset for why).
        self._shake_offset: tuple[int, int] = (0, 0)
        self._rest_pos: tuple[int, int] | None = None

        raw = state.get("state", "idle")
        self._idle_since: float | None = time.time() if raw == "idle" else None
        self._waiting_since: float | None = time.time() if raw == "waiting" else None
        self._effective_state = self._compute_effective_state(time.time())
        self._anim_t0 = time.time()

        # canvas item ids we animate / restyle in place
        self._border_id: int | None = None
        self._info_id: int | None = None
        self._info_text_val = ""
        self._started = state.get("started")
        self._bob_y = 0.0

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
        self.canvas.bind("<Enter>", self._on_hover_enter)
        self.canvas.bind("<Leave>", self._on_hover_leave)

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
        accent = _accent(self._effective_state)

        # rounded panel + accent border (the border pulses while waiting)
        round_rect(c, PANEL_MARGIN, PANEL_MARGIN, CARD_W - PANEL_MARGIN,
                   CARD_H - PANEL_MARGIN, PANEL_RADIUS, fill=PANEL_FILL, outline="")
        self._border_id = round_rect(
            c, PANEL_MARGIN, PANEL_MARGIN, CARD_W - PANEL_MARGIN, CARD_H - PANEL_MARGIN,
            PANEL_RADIUS, fill="", outline=accent, width=2,
        )

        _draw_creature(c, CREATURE_CX, CREATURE_CY, self._effective_state, accent)
        self._bob_y = 0.0

        c.create_text(CREATURE_CX, CAPTION_Y,
                      text=STATE_CAPTIONS.get(self._effective_state, "—"),
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

        self._sig = _render_sig(self.state, self._effective_state)

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
        module = _ART.get(config.ART_STYLE, sprite_pixel)
        size = MINI_PIXEL_PX if config.ART_STYLE == "pixel" else MINI_SMOOTH_R
        accent = _hex(config.SUBAGENT_COLOR)
        total = (len(subs) - 1) * BADGE_GAP
        x0 = CREATURE_CX - total / 2
        for i in range(len(subs)):
            x = x0 + i * BADGE_GAP
            module.draw_creature(c, x, BADGE_Y, "working", accent, size, tag="subagent")

    # --- positioning ------------------------------------------------------
    def _place_initial(self, index: int) -> None:
        """Anchor the card to the bottom-right of the *primary* monitor's work
        area, stacking extra sessions upward, and clamp so it can never land
        off-screen (wrong monitor / behind the taskbar / too many stacked)."""
        area = osplatform.primary_work_area()
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
        self._hide_tooltip()  # don't keep a stale tooltip floating during a drag
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
        # A tap (press+release without a real drag or shake) pets the mascot.
        now = time.time()
        raw = self.state.get("state", "idle")
        if (moved < PET_TAP_MAX_DIST and now >= self._dizzy_until
                and raw not in ("waiting", "dead")):
            self._pet(now)

    # --- pet hearts -------------------------------------------------------
    def _pet(self, now: float) -> None:
        """Reward a tap with a happy face and a few rising pixel hearts."""
        self._celebrate_until = now + CELEBRATE_DURATION_S
        self._emit_hearts(now)
        self._refresh_render(now)

    def _emit_hearts(self, now: float) -> None:
        """Spawn a small staggered burst of hearts above the creature."""
        for _ in range(3):
            self._hearts.append({
                "x": float(CREATURE_CX + random.uniform(-14, 14)),
                "y0": float(CREATURE_CY - _s(6)),
                "t0": now + random.uniform(0.0, 0.15),
                "drift": random.uniform(-10.0, 10.0),
            })
        self._hearts = self._hearts[-MAX_HEARTS:]

    def _animate_hearts(self, now: float) -> None:
        """Move active hearts up while fading them toward the panel; drop expired."""
        self.canvas.delete("heart")
        if not self._hearts:
            return
        base = config.STATE_COLORS["happy"]
        alive: list[dict[str, float]] = []
        for h in self._hearts:
            prog = (now - h["t0"]) / HEART_LIFETIME_S
            if prog < 0.0:        # staggered start: not visible yet
                alive.append(h)
                continue
            if prog >= 1.0:       # finished
                continue
            x = h["x"] + h["drift"] * prog
            y = h["y0"] - prog * HEART_RISE_PX
            color = _hex(_lerp(base, _PANEL_FILL_RGB, prog))
            sprite_pixel.draw_heart(self.canvas, x, y, HEART_PX, color)
            alive.append(h)
        self._hearts = alive

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
        self._dizzy_until = now + DIZZY_DURATION_S
        self._refresh_render(now)

    # --- effective state --------------------------------------------------
    def _compute_effective_state(self, now: float) -> str:
        """Effective (displayed) state. These overlays are widget-side only,
        in priority order:
          - `dizzy`      while a recent shake is still in effect (top priority),
          - `happy`      briefly after Claude finishes a turn, or on a pet,
          - `sleeping`   after the raw state has been idle for SLEEP_AFTER_IDLE_S,
          - `idle_blink` a brief blink while idle (before dozing off).
        """
        if now < self._dizzy_until:
            return "dizzy"
        if now < self._celebrate_until:
            return "happy"
        raw = self.state.get("state", "idle")
        # Glare (angry face) once an unanswered prompt has waited long enough that
        # the card starts shaking — same threshold as the attention shake.
        if (raw == "waiting" and self._waiting_since is not None
                and now - self._waiting_since >= WAITING_SHAKE_AFTER_S):
            return "waiting_angry"
        # Don't sit frozen on `thinking` if the turn died with no closing hook
        # (e.g. a session-limit hit): after a long stale stretch, show idle.
        ts = self.state.get("ts")
        if raw == "thinking" and ts is not None and now - ts > THINKING_STALL_S:
            raw = "idle"
        if raw == "idle" and self._idle_since is not None:
            if now - self._idle_since >= config.SLEEP_AFTER_IDLE_S:
                return "sleeping"
            if now < self._blink_until:
                return "idle_blink"
        return raw

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
        # -> idle). Not on waiting->idle (the user just answered) or dead.
        if prev_raw in ("working", "thinking") and raw == "idle":
            self._celebrate_until = now + CELEBRATE_DURATION_S
        if raw == "idle":
            if self._idle_since is None:
                self._idle_since = now
        else:
            self._idle_since = None

        # Track how long an attention prompt has gone unanswered (drives the shake).
        if raw == "waiting":
            if self._waiting_since is None:
                self._waiting_since = now
        else:
            self._waiting_since = None

        self._refresh_render(now)
        self._sync_bubble(state.get("notify"))

    def _refresh_render(self, now: float) -> None:
        """Recompute effective state; redraw only if the visible content changed."""
        self._effective_state = self._compute_effective_state(now)
        new_sig = _render_sig(self.state, self._effective_state)
        if new_sig == self._sig:
            return
        self._render()

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
            self._blink_until = now + BLINK_DURATION_S
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

    def _reposition_bubble(self) -> None:
        if self._bubble is None:
            return
        try:
            self._bubble.place_above(
                self.root.winfo_x(), self.root.winfo_y(),
                CARD_W, self.root.winfo_screenwidth(),
            )
        except tk.TclError:
            pass

    # --- stats tooltip ----------------------------------------------------
    def _stats_text(self, now: float) -> str:
        st = self.state
        prompts = st.get("prompts", 0)
        tools = st.get("tools_run", 0)
        agents = st.get("subagents_spawned", 0)
        up = _format_duration(now - self._started) if self._started else "—"
        agent_part = f"   ·   {agents} agents" if agents else ""
        return f"{prompts} prompts   ·   {tools} tools{agent_part}\nup {up}"

    def _on_hover_enter(self, _event: tk.Event) -> None:
        text = self._stats_text(time.time())
        if self._tooltip is None:
            self._tooltip = StatsTooltip(self._manager_root, text)
        else:
            self._tooltip.set_text(text)
        self._position_tooltip()

    def _on_hover_leave(self, _event: tk.Event) -> None:
        self._hide_tooltip()

    def _hide_tooltip(self) -> None:
        if self._tooltip is not None:
            self._tooltip.destroy()
            self._tooltip = None

    def _position_tooltip(self) -> None:
        if self._tooltip is None:
            return
        try:
            self._tooltip.place_beside(
                self.root.winfo_x(), self.root.winfo_y(),
                CARD_W, CARD_H, self.root.winfo_screenwidth(),
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

            # Rising heart particles from a pet.
            self._animate_hearts(now)

            # Gentle border pulse while the raw state needs the user's attention.
            if self._border_id is not None:
                if self.state.get("state", "idle") == "waiting":
                    phase = (elapsed / PULSE_PERIOD_S) * 2 * math.pi
                    t = (math.sin(phase) + 1) / 2
                    color = _hex(_lerp((42, 45, 59), config.STATE_COLORS["waiting"], t))
                    self.canvas.itemconfig(self._border_id, outline=color)

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
            if self._tooltip is not None:        # keep counters/uptime live while hovering
                self._tooltip.set_text(self._stats_text(now))
                self._position_tooltip()
        except tk.TclError:
            return

        self.root.after(config.ANIM_INTERVAL_MS, self._animate)

    # --- attention shake --------------------------------------------------
    def _apply_attention_shake(self, now: float) -> None:
        """Jostle the card while a prompt sits unanswered; the longer it's been
        ignored, the wider and faster the shake — up to a frantic maximum."""
        if self._drag_offset is not None:
            return  # the user is holding it; don't fight the drag
        waiting = (self.state.get("state", "idle") == "waiting"
                   and self._waiting_since is not None)
        elapsed = (now - self._waiting_since) if waiting else 0.0
        if not waiting or elapsed < WAITING_SHAKE_AFTER_S:
            self._reset_shake_offset()  # settle back to rest
            return

        intensity = min(1.0, (elapsed - WAITING_SHAKE_AFTER_S) / WAITING_SHAKE_RAMP_S)
        amp = WAITING_SHAKE_AMP_MIN + (WAITING_SHAKE_AMP_MAX - WAITING_SHAKE_AMP_MIN) * intensity
        freq = WAITING_SHAKE_FREQ_MIN + (WAITING_SHAKE_FREQ_MAX - WAITING_SHAKE_FREQ_MIN) * intensity
        phase = (now - self._anim_t0) * freq * 2 * math.pi
        # A steady horizontal sway, plus a jitter that grows with intensity so it
        # reads as a gentle wobble at first and a violent buzz once ignored a while.
        ox = amp * math.sin(phase) + random.uniform(-1.0, 1.0) * amp * 0.5 * intensity
        oy = random.uniform(-1.0, 1.0) * amp * 0.6
        self._set_shake_offset(round(ox), round(oy))

    def _set_shake_offset(self, ox: int, oy: int) -> None:
        """Offset the card from its resting position by (ox, oy).

        The rest position is captured once, the moment the shake begins, and every
        frame then sets an *absolute* geometry of rest+(ox, oy). An earlier version
        moved by deltas off ``winfo_x()``; because that value lags a frame behind a
        just-applied ``geometry`` on Windows, the error accumulated on every shake
        reversal and slowly walked a frantically shaking card clean off-screen."""
        if (ox, oy) == self._shake_offset:
            return
        if self._rest_pos is None:        # starting to shake: remember where it rests
            try:
                self._rest_pos = (self.root.winfo_x(), self.root.winfo_y())
            except tk.TclError:
                return
        try:
            self.root.geometry(f"+{self._rest_pos[0] + ox}+{self._rest_pos[1] + oy}")
        except tk.TclError:
            return
        self._shake_offset = (ox, oy)

    def _reset_shake_offset(self) -> None:
        """Settle the card back onto its captured resting position (zero shake)."""
        if self._shake_offset == (0, 0):
            return
        if self._rest_pos is not None:
            try:
                self.root.geometry(f"+{self._rest_pos[0]}+{self._rest_pos[1]}")
            except tk.TclError:
                pass
        self._shake_offset = (0, 0)
        self._rest_pos = None

    def set_hidden(self, hidden: bool) -> None:
        """Withdraw or restore this card (and its speech bubble) for the tray's
        'show / hide cards' toggle. Windows drops the always-on-top flag when a
        withdrawn window is shown again, so re-assert it after deiconify."""
        self._hidden = hidden
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
        self._hide_tooltip()
        self.root.destroy()


class MascotManager:
    """Owns the single Tk root; spawns one Toplevel window per live session."""

    def __init__(self) -> None:
        self.windows: dict[str, MascotWindow] = {}
        self.root = tk.Tk()
        self.root.withdraw()  # hidden controller window
        self.root.title("Mascot Manager")
        icon.apply(self.root)  # mascot icon for the taskbar / any child windows

        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        print("[mascot] state dir:", config.STATE_DIR)
        print("[mascot] tkinter app started")

        # System-tray icon (Windows only). Best-effort: any failure leaves the
        # widget fully working, just without a tray icon.
        self._cards_hidden = False
        self.tray = None
        if osplatform.IS_WINDOWS:
            try:
                from .tray import SystemTray
                self.tray = SystemTray(
                    tooltip="Claude Familiar",
                    on_toggle=self._on_tray_toggle,
                    on_settings=self._on_tray_settings,
                    on_quit=self._on_tray_quit,
                )
            except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
                print("[mascot] system tray unavailable:", exc)
                self.tray = None

        self.root.after(500, self._refresh)

    def _refresh(self) -> None:
        now = time.time()
        states = state_store.load_states(config.STATE_DIR, now)

        for sid in list(self.windows):
            if sid not in states:
                self.windows[sid].close()
                del self.windows[sid]

        for index, (sid, state) in enumerate(sorted(states.items())):
            win = self.windows.get(sid)
            if win is None:
                win = MascotWindow(self.root, sid, state, index)
                self.windows[sid] = win
                if self._cards_hidden:        # honor a tray "hide" for new sessions
                    win.set_hidden(True)
            else:
                win.update_state(state, now)

        self.root.after(500, self._refresh)

    # --- system-tray callbacks (run on the Tk thread) ---------------------
    def _on_tray_toggle(self) -> None:
        """Show / hide every card at once."""
        self._cards_hidden = not self._cards_hidden
        for win in self.windows.values():
            win.set_hidden(self._cards_hidden)

    def _on_tray_settings(self) -> None:
        """Open the settings panel as its own process, like the rest of the app."""
        try:
            subprocess.Popen([str(_pythonw()), "-m", "mascot.control_panel"],
                             cwd=str(PROJECT_ROOT))
        except OSError as exc:
            print("[mascot] could not open settings:", exc)

    def _on_tray_quit(self) -> None:
        """Close every card, drop the tray icon, and end the main loop."""
        for win in list(self.windows.values()):
            win.close()
        self.windows.clear()
        if self.tray is not None:
            self.tray.dispose()
            self.tray = None
        self.root.quit()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            if self.tray is not None:        # also covers a normal window-close exit
                self.tray.dispose()
                self.tray = None


def main() -> None:
    # Only one widget process at a time. A second one would poll the same state
    # dir and draw a duplicate, exactly-overlapping card for every session.
    guard = single_instance.acquire()
    if guard is None:
        print("[mascot] another Claude Familiar widget is already running; exiting.")
        return
    MascotManager().run()


if __name__ == "__main__":
    main()
