"""Tkinter mascot widget.

One window per Claude session. Native, built-in tkinter only — no external deps.
Run with: python run_mascot.py  (or: python -m mascot)
"""
from __future__ import annotations

import math
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from . import config, state_store


STATE_EMOJIS = {
    "idle": "😴",
    "thinking": "🤔",
    "working": "⚙️",
    "waiting": "⏳",
    "sleeping": "💤",
    "dizzy": "😵‍💫",  # widget-side easter egg: shake the mascot to make it dizzy
}

SUBAGENT_LETTERS = {
    "code-reviewer": "R",
    "tdd-guide": "T",
    "security-reviewer": "S",
    "architect": "A",
    "code-simplifier": "C",
}

CARD_WIDTH = 140
CARD_HEIGHT = 154
CARD_BG = "#1c1e26"
CARD_BG_RGB = (28, 30, 38)

BORDER_W = 3            # px; pulses to the waiting color, else stays CARD_BG
BOB_AMPLITUDE = 4       # px of vertical float on the emoji
EMOJI_PADY_TOP = 8      # baseline top padding for the emoji label
BOB_PERIOD_S = 2.0      # one full bob cycle
PULSE_PERIOD_S = 1.2    # one full waiting-pulse cycle

# Comic speech bubble (shown above the card while Claude needs the user).
BUBBLE_W = 196
BUBBLE_PAD = 10         # text inset inside the bubble
BUBBLE_TAIL_H = 12      # height of the little pointer tail
BUBBLE_GAP = 6          # gap between tail tip and the card top
BUBBLE_FILL = "#fdf6e3"
BUBBLE_TEXT = "#1c1e26"
BUBBLE_TRANSPARENT = "#ff00ff"  # magic key color -> click-through transparent
BUBBLE_MAX_CHARS = 160          # guard against a runaway message

# Shake-to-dizzy easter egg: count rapid direction reversals while dragging (any
# axis — horizontal, vertical, or diagonal); enough within the window -> show the
# dizzy face for a moment.
SHAKE_MIN_DIST = 7         # px of travel for a move to "count"
SHAKE_WINDOW_S = 0.7       # reversals must happen within this rolling window
SHAKE_REVERSALS = 4        # direction flips needed to trigger dizzy
DIZZY_DURATION_S = 2.0     # how long the dizzy face lingers


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


def _render_sig(state: dict[str, Any], effective_state: str) -> tuple:
    """Signature of the *visible* parts of a state.

    Excludes the `ts` heartbeat so we only rebuild the card when something the
    user can actually see changes (avoids flicker + needless rebuilds). Uses the
    *effective* state so an idle→sleeping flip triggers a rebuild.
    """
    subs = tuple((s.get("type") or "?") for s in (state.get("subagents") or []))
    return (effective_state, subs, state.get("cwd", ""))


class BubbleWindow:
    """A speech bubble shown above a mascot while Claude needs the user.

    A small opaque, frameless Toplevel: a dark outer frame (the border) wrapping
    a cream text label. Opaque on purpose — Windows `-transparentcolor` layered
    windows render unreliably with `overrideredirect` (often fully invisible), so
    we avoid them entirely.
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
            font=("Segoe UI", 9),
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
        self.top.update_idletasks()  # so winfo_req* reflect the new text
        self._width = self.top.winfo_reqwidth()
        self._height = self.top.winfo_reqheight()

    def place_above(self, card_x: int, card_y: int, card_w: int, screen_w: int) -> None:
        """Position the bubble centered just above the card."""
        x = card_x + card_w // 2 - self._width // 2
        x = max(0, min(x, screen_w - self._width))
        y = card_y - self._height - BUBBLE_GAP
        if y < 0:
            y = card_y  # no room above -> sit over the card instead of off-screen
        self.top.geometry(f"+{x}+{y}")

    def destroy(self) -> None:
        try:
            self.top.destroy()
        except tk.TclError:
            pass


class MascotWindow:
    """One mascot window (Toplevel) per session."""

    def __init__(self, manager_root: tk.Tk, session_id: str, state: dict[str, Any], index: int) -> None:
        self.session_id = session_id
        self.state = state
        self._sig: tuple | None = None
        self._drag_offset: tuple[int, int] | None = None
        self._alive = True
        self._manager_root = manager_root
        self._bubble: BubbleWindow | None = None

        # --- effective-state / animation bookkeeping ---
        # Shake-to-dizzy fields must exist before _compute_effective_state runs.
        self._dizzy_until = 0.0
        self._last_shake_pos: tuple[int, int] | None = None
        self._last_move: tuple[int, int] | None = None
        self._reversals: list[float] = []

        raw = state.get("state", "idle")
        self._idle_since: float | None = time.time() if raw == "idle" else None
        self._effective_state = self._compute_effective_state(time.time())
        self._emoji_label: tk.Label | None = None
        self._border: tk.Frame | None = None
        self._anim_t0 = time.time()

        # IMPORTANT: extra windows must be Toplevel, not Tk(). Only one Tk root.
        self.root = tk.Toplevel(manager_root)
        self.root.title(f"Mascot - {session_id[:8]}")
        self.root.overrideredirect(True)       # frameless
        self.root.attributes("-topmost", True)  # always on top
        self.root.configure(bg=CARD_BG)
        self.root.geometry(f"{CARD_WIDTH}x{CARD_HEIGHT}")

        # Position once, at creation. We never reposition again, so a window the
        # user drags stays exactly where they put it.
        self._place_initial(index)

        self._build_card()
        self._sync_bubble(state.get("notify"))
        self.root.after(config.ANIM_INTERVAL_MS, self._animate)

    # --- UI ---------------------------------------------------------------
    def _build_card(self) -> None:
        """(Re)build the card UI for the current (effective) state."""
        for widget in self.root.winfo_children():
            widget.destroy()

        state_type = self._effective_state

        # Outer border frame — its padding shows as a border we can pulse.
        self._border = tk.Frame(self.root, bg=CARD_BG, padx=BORDER_W, pady=BORDER_W)
        self._border.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(self._border, bg=CARD_BG)
        inner.pack(fill=tk.BOTH, expand=True)

        emoji = tk.Label(
            inner,
            text=STATE_EMOJIS.get(state_type, "❓"),
            font=("Segoe UI Emoji", 40),
            bg=CARD_BG,
            fg="#ffffff",
        )
        emoji.pack(pady=(EMOJI_PADY_TOP, 2))
        self._emoji_label = emoji

        subs = self.state.get("subagents", []) or []
        if subs:
            subs_frame = tk.Frame(inner, bg=CARD_BG)
            subs_frame.pack()
            for sub in subs[:4]:  # cap badges shown
                letter = SUBAGENT_LETTERS.get(sub.get("type", "?"), "?")
                badge = tk.Label(
                    subs_frame,
                    text=letter,
                    font=("Arial", 8, "bold"),
                    bg="#9f7aea",
                    fg=CARD_BG,
                    padx=4,
                    pady=1,
                )
                badge.pack(side=tk.LEFT, padx=2)

        cwd = self.state.get("cwd", "")
        label_text = Path(cwd).name if cwd else self.session_id[:8]
        label = tk.Label(
            inner,
            text=label_text,
            font=("Arial", 7),
            bg=CARD_BG,
            fg="#ebebeb",
            wraplength=CARD_WIDTH - 10,
        )
        label.pack(side=tk.BOTTOM, pady=4)

        # Make the whole card draggable: bind to root AND every descendant, so a
        # click anywhere on the card grabs it (not just the bare background).
        self._bind_draggable(self.root)

        self._sig = _render_sig(self.state, self._effective_state)

    def _bind_draggable(self, widget: tk.Misc) -> None:
        widget.bind("<Button-1>", self._on_drag_start)
        widget.bind("<B1-Motion>", self._on_drag_motion)
        for child in widget.winfo_children():
            self._bind_draggable(child)

    # --- positioning ------------------------------------------------------
    def _place_initial(self, index: int) -> None:
        """Place window in the bottom-right, stacked by index. Called once."""
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - CARD_WIDTH - 20
        y = sh - (CARD_HEIGHT + 12) * (index + 1) - 20
        self.root.geometry(f"+{x}+{y}")

    # --- drag -------------------------------------------------------------
    def _on_drag_start(self, event: tk.Event) -> None:
        # Offset of the cursor within the window, so dragging feels anchored.
        self._drag_offset = (event.x_root - self.root.winfo_x(),
                             event.y_root - self.root.winfo_y())
        # Reset shake tracking for this fresh drag.
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
        """Count rapid direction reversals on any axis; enough -> go dizzy.

        A "reversal" is a move that points more than 90° away from the previous
        move (dot product < 0), so a back-and-forth wiggle in any direction —
        horizontal, vertical, or diagonal — counts.
        """
        if self._last_shake_pos is None:
            self._last_shake_pos = (x_root, y_root)
            return
        dx = x_root - self._last_shake_pos[0]
        dy = y_root - self._last_shake_pos[1]
        if math.hypot(dx, dy) < SHAKE_MIN_DIST:
            return  # ignore jitter; keep the baseline until a real move
        self._last_shake_pos = (x_root, y_root)
        if self._last_move is not None:
            dot = dx * self._last_move[0] + dy * self._last_move[1]
            if dot < 0:  # direction flipped by > 90°
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
        self._refresh_render(now)  # show the dizzy face immediately

    # --- effective state --------------------------------------------------
    def _compute_effective_state(self, now: float) -> str:
        """Effective (displayed) state. Both extra states are widget-side only —
        no hook emits them:
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
        """Update display only if the visible (effective) content changed."""
        if now is None:
            now = time.time()
        self.state = state

        raw = state.get("state", "idle")
        if raw == "idle":
            if self._idle_since is None:
                self._idle_since = now
        else:
            self._idle_since = None

        self._refresh_render(now)
        self._sync_bubble(state.get("notify"))

    def _refresh_render(self, now: float) -> None:
        """Recompute the effective state and reflect it on screen.

        A state-only change (e.g. idle→sleeping, →dizzy) swaps the emoji text in
        place — cheap, flicker-free, and safe to do mid-drag (no widget is
        destroyed, so the drag grab survives). Sub-agent/cwd changes still do a
        full rebuild.
        """
        self._effective_state = self._compute_effective_state(now)
        new_sig = _render_sig(self.state, self._effective_state)
        if new_sig == self._sig:
            return
        only_state_changed = self._sig is not None and new_sig[1:] == self._sig[1:]
        if only_state_changed and self._emoji_label is not None:
            try:
                self._emoji_label.config(text=STATE_EMOJIS.get(self._effective_state, "❓"))
                self._sig = new_sig
                return
            except tk.TclError:
                pass
        self._build_card()

    # --- speech bubble ----------------------------------------------------
    def _sync_bubble(self, notify: dict[str, Any] | None) -> None:
        """Show/update/hide the comic bubble to match the notify payload."""
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
                CARD_WIDTH, self.root.winfo_screenwidth(),
            )
        except tk.TclError:
            pass

    # --- animation --------------------------------------------------------
    def _animate(self) -> None:
        """Cheap ~25fps loop: bob the emoji, pulse the border while waiting."""
        if not self._alive:
            return
        try:
            now = time.time()
            elapsed = now - self._anim_t0

            # Clears the dizzy face when it expires; also flips idle→sleeping.
            self._refresh_render(now)

            # Subtle vertical float on the emoji to feel alive.
            if self._emoji_label is not None and self._emoji_label.winfo_exists():
                phase = (elapsed / BOB_PERIOD_S) * 2 * math.pi
                offset = (math.sin(phase) + 1) / 2 * BOB_AMPLITUDE  # 0..amplitude
                self._emoji_label.pack_configure(pady=(EMOJI_PADY_TOP + int(offset), 2))

            # Gentle border pulse while the raw state needs the user's attention.
            if self._border is not None and self._border.winfo_exists():
                if self.state.get("state", "idle") == "waiting":
                    phase = (elapsed / PULSE_PERIOD_S) * 2 * math.pi
                    t = (math.sin(phase) + 1) / 2  # 0..1
                    color = _hex(_lerp(CARD_BG_RGB, config.STATE_COLORS["waiting"], t))
                    self._border.configure(bg=color)
                else:
                    self._border.configure(bg=CARD_BG)

            # Keep the bubble glued above the card (even while it's dragged).
            if self._bubble is not None:
                self._reposition_bubble()
        except tk.TclError:
            return  # window went away mid-frame; stop quietly

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

        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        print("[mascot] state dir:", config.STATE_DIR)
        print("[mascot] tkinter app started")

        self.root.after(500, self._refresh)

    def _refresh(self) -> None:
        now = time.time()
        states = state_store.load_states(config.STATE_DIR, now)

        # Close windows for sessions that ended.
        for sid in list(self.windows):
            if sid not in states:
                self.windows[sid].close()
                del self.windows[sid]

        # Create new windows; update existing ones in place (no repositioning,
        # so dragged windows keep their location).
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
