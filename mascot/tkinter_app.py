"""Tkinter mascot widget.

One window per Claude session. Native, built-in tkinter only — no external deps.
The mascot is a custom character drawn on a Canvas (see `sprite_pixel.py`), not
an emoji or image asset. Run with: python run_mascot.py  (or: python -m mascot)
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from . import config, icon, sprite_pixel, sprite_smooth, state_store

# Mascot art modules, selectable via config.ART_STYLE. The smooth blob is kept
# on the side; the pixel creature is the default.
_ART = {"pixel": sprite_pixel, "smooth": sprite_smooth}


def _draw_creature(c, cx, cy, state, accent) -> None:
    """Draw the mascot using the configured art style, scaled to the widget size."""
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
    "thinking": "thinking…",
    "working": "working…",
    "waiting": "needs you!",
    "sleeping": "zzz…",
    "dizzy": "whoa…",
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
PANEL_FILL = "#1d1f29"
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

# Shake-to-dizzy easter egg.
SHAKE_MIN_DIST = 7
SHAKE_WINDOW_S = 0.7
SHAKE_REVERSALS = 4
DIZZY_DURATION_S = 2.0


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


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


class MascotWindow:
    """One mascot window (Toplevel) per session, drawn on a single Canvas."""

    def __init__(self, manager_root: tk.Tk, session_id: str, state: dict[str, Any], index: int) -> None:
        self.session_id = session_id
        self.state = state
        self._sig: tuple | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._alive = True
        self._manager_root = manager_root
        self._bubble: BubbleWindow | None = None

        # effective-state / shake bookkeeping (must exist before first compute)
        self._dizzy_until = 0.0
        self._last_shake_pos: tuple[int, int] | None = None
        self._last_move: tuple[int, int] | None = None
        self._reversals: list[float] = []

        raw = state.get("state", "idle")
        self._idle_since: float | None = time.time() if raw == "idle" else None
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
        win_bg = CHROMA if config.TRANSPARENT_BG else WIN_BG

        self.root = tk.Toplevel(manager_root)
        self.root.title(f"Mascot - {session_id[:8]}")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=win_bg)
        if config.TRANSPARENT_BG:
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
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - CARD_W - 20
        y = sh - (CARD_H + 12) * (index + 1) - 20
        self.root.geometry(f"+{x}+{y}")

    # --- drag -------------------------------------------------------------
    def _on_drag_start(self, event: tk.Event) -> None:
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
        """Effective (displayed) state. Both extra states are widget-side only:
          - `dizzy`    while a recent shake is still in effect (top priority),
          - `sleeping` after the raw state has been idle for SLEEP_AFTER_IDLE_S.
        """
        if now < self._dizzy_until:
            return "dizzy"
        raw = self.state.get("state", "idle")
        if raw == "idle" and self._idle_since is not None:
            if now - self._idle_since >= config.SLEEP_AFTER_IDLE_S:
                return "sleeping"
        return raw

    # --- state ------------------------------------------------------------
    def update_state(self, state: dict[str, Any], now: float | None = None) -> None:
        if now is None:
            now = time.time()
        self.state = state
        if state.get("started"):
            self._started = state["started"]

        raw = state.get("state", "idle")
        if raw == "idle":
            if self._idle_since is None:
                self._idle_since = now
        else:
            self._idle_since = None

        self._refresh_render(now)
        self._sync_bubble(state.get("notify"))

    def _refresh_render(self, now: float) -> None:
        """Recompute effective state; redraw only if the visible content changed."""
        self._effective_state = self._compute_effective_state(now)
        new_sig = _render_sig(self.state, self._effective_state)
        if new_sig == self._sig:
            return
        self._render()

    # --- speech bubble ----------------------------------------------------
    def _sync_bubble(self, notify: dict[str, Any] | None) -> None:
        if notify:
            message = notify.get("message") or "Claude needs your attention"
            if self._bubble is None:
                self._bubble = BubbleWindow(self._manager_root, message)
                self._reposition_bubble()
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

    # --- animation --------------------------------------------------------
    def _animate(self) -> None:
        """Cheap ~25fps loop: bob the creature, pulse the border while waiting."""
        if not self._alive:
            return
        try:
            now = time.time()
            elapsed = now - self._anim_t0

            # Clears the dizzy face when it expires; also flips idle→sleeping.
            self._refresh_render(now)

            # Subtle vertical float — move the whole creature group.
            phase = (elapsed / BOB_PERIOD_S) * 2 * math.pi
            target = -(math.sin(phase) + 1) / 2 * BOB_AMPLITUDE  # 0..-amplitude
            self.canvas.move("creature", 0, target - self._bob_y)
            self._bob_y = target

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

            if self._bubble is not None:
                self._reposition_bubble()
        except tk.TclError:
            return

        self.root.after(config.ANIM_INTERVAL_MS, self._animate)

    def close(self) -> None:
        self._alive = False
        if self._bubble is not None:
            self._bubble.destroy()
            self._bubble = None
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
                self.windows[sid] = MascotWindow(self.root, sid, state, index)
            else:
                win.update_state(state, now)

        self.root.after(500, self._refresh)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    MascotManager().run()


if __name__ == "__main__":
    main()
