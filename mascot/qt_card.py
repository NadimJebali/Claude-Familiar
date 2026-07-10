"""The Qt session card — animated and interactive (issues #56, #57).

One frameless, per-pixel-translucent, always-on-top window per live Claude
session. Real ``WA_TranslucentBackground`` alpha gives a rounded panel with a
painted drop shadow on Windows **and** composited Linux, with no chroma-key hack.

The displayed face is computed by reusing the pure cores the Tk card uses — so
the port inherits their tested behaviour rather than re-deriving it:
``Overlay`` + ``effective_state`` layer dozing, the idle blink, the celebrate
hop, dizzy, the waiting glare, per-tool working faces, plan-mode and the stumble
over the raw hook state. The face is a cached (integer-scaled, crisp) pixmap from the
``SpriteRenderer`` seam, re-rendered only when the face (or the pet's look) changes;
a ~60fps timer drives sub-pixel motion, faces **crossfade** rather than snap, and an
evolution **scales** the creature up — all transform-based over the cached pixmaps
(the glow-up, #59). The card is draggable, a quick tap (no drag) pets it — a happy hop
plus a ``petted`` signal the manager turns into the coin trickle — and vigorously
shaking it with the mouse makes it dizzy.

The manager pushes the global pet's look via :meth:`QtCard.set_pet`: the mood tints
the idle face and the stage/hat/flourish dress the sprite (parity with the Tk card).
A paw button at the panel's top-left (shown only when the pet is live) asks the
manager to open the Pet window via the ``open_pet_requested`` signal.

While a prompt sits unanswered the whole card jostles (the pure ``shake.Shake`` seam),
gently at first then more frantic the longer it's ignored — settling the moment it's
answered or grabbed. Petting spawns rising pixel hearts, and a hungry/tired mood pops
food/Z emotes — the shared lifetime math is the pure ``particles`` core, painted by
the panel.

Each live sub-agent shows as a small mini-mascot badge in a centered row below the
caption (capped so a swarm can't crowd the card). The card anchors to the *home*
monitor's work area (the one picked in Settings, enumerated via ``qt_screens`` — the
same index space the settings picker uses), and in simple hook-visualiser mode (pet
off) it shows the fixed life stage from Settings with no paw button and no hover
tooltip — a read-only indicator.

Two satellite popups (``mascot.qt_popups``) follow the card: a speech bubble while
Claude needs the user, and a pet-status tooltip on hover (pet-enabled only).
"""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import (
    config,
    effective_state,
    osplatform,
    particles,
    pixel_qt,
    qt_screens,
    shake,
    sprite_pixel,
)
from .overlay import Overlay, OverlayConfig
from .pet_view import PetView, pet_view
from .pixel_grid import grid_cells
from .qt_popups import QtBubble, QtStatsTooltip
from .sprite_qt import SpriteRenderer, SpriteSpec

# --- card geometry (mirrors the Tk card's authored "small" size) ------------
CARD_W = 158
CARD_H = 211
CREATURE_PX = 5
CREATURE_CY = 68        # vertical center of the creature zone
CAPTION_Y = 132
SHADOW_PAD = 18         # room around the panel so the drop shadow isn't clipped

# Sub-agent badges: each live sub-agent shows as a small "working" mini-mascot in
# the sub-agent accent, in a centered row below the caption (capped so a swarm can't
# crowd the card).
MAX_BADGES = 4
BADGE_MINI_PX = 1       # 1px/cell -> a ~16px mini creature (matches the Tk badge)
BADGE_GAP = 24          # spacing between badge centers
BADGE_CY = 176          # vertical center of the badge row

PANEL_FILL = "#1d1f29"
PANEL_EDGE = "#2a2d3b"
PANEL_RADIUS = 20
CAPTION_FG = "#e8e6ef"

# The paw button (opens the Pet window) sits at the panel's top-left, mirroring the
# Tk card. Its icon is the same pixel-art paw, rasterized once to a QPixmap.
PAW_PX = 2              # pixel size of the paw icon (a 12x12 grid -> 24px)
PAW_INSET = 8          # offset from the panel's top-left corner

# --- animation / interaction constants (match the Tk card) ------------------
ANIM_MS = 16            # ~60fps — refresh-synced, smooth motion (the glow-up, #59)
BOB_AMPLITUDE = 4
BOB_PERIOD_S = 2.0
# Glow-up (#59): faces crossfade instead of snapping, and an evolution scales the
# creature up smoothly. Motion is transform-based over the cached (integer-scaled)
# pixmaps, so the pixel art stays crisp.
CROSSFADE_S = 0.18      # fast enough to never mask a real state change
STAGE_SCALE_S = 0.6     # a stage change grows the creature over this
STAGE_SCALE_START = 0.5  # ... from half size up to full
BLINK_DURATION_S = 0.12
BLINK_MIN_GAP_S = 4.0
BLINK_MAX_GAP_S = 7.0
DIZZY_DURATION_S = 2.0
CELEBRATE_DURATION_S = 1.5
STUMBLE_FACE_S = 8.0
THINKING_STALL_S = 180.0
WORKING_STALL_S = 270.0
PET_TAP_MAX_DIST = 5    # a press+release moving <= this (px) is a pet tap, not a drag

# Shake-to-dizzy easter egg: enough rapid drag reversals within the window make the
# mascot dizzy (mirrors the Tk card).
SHAKE_MIN_DIST = 7      # a drag sample must move at least this (px) to count
SHAKE_WINDOW_S = 0.7    # reversals must fall within this window
SHAKE_REVERSALS = 4     # this many rapid reversals -> dizzy

_OVERLAY_CONFIG = OverlayConfig(
    dizzy_duration_s=DIZZY_DURATION_S,
    celebrate_duration_s=CELEBRATE_DURATION_S,
    blink_duration_s=BLINK_DURATION_S,
    sleep_after_idle_s=config.SLEEP_AFTER_IDLE_S,
    shake_after_s=config.SHAKE_AFTER_S,
    thinking_stall_s=THINKING_STALL_S,
    working_stall_s=WORKING_STALL_S,
)

# Attention shake: while an attention/permission prompt sits unanswered, the whole
# card jostles after the grace window, growing steadily more frantic the longer it's
# ignored (the same recipe + pure Shake seam the Tk card uses). No `_s` scale factor
# here — the Qt card authors its constants at 1x.
WAITING_SHAKE_RAMP_S = 60.0          # ramps to full aggression over this
WAITING_SHAKE_FREQ_MIN = 4.0         # sways/sec when gentle
WAITING_SHAKE_FREQ_MAX = 11.0        # sways/sec when frantic
WAITING_SHAKE_AMP_MAX = float(config.SHAKE_MAX_AMP_PX)   # configurable max sway (px)
WAITING_SHAKE_AMP_MIN = min(2.0, WAITING_SHAKE_AMP_MAX)  # gentle start, never > max

_SHAKE_CONFIG = shake.ShakeConfig(
    after_s=config.SHAKE_AFTER_S,
    ramp_s=WAITING_SHAKE_RAMP_S,
    amp_min=WAITING_SHAKE_AMP_MIN,
    amp_max=WAITING_SHAKE_AMP_MAX,
    freq_min=WAITING_SHAKE_FREQ_MIN,
    freq_max=WAITING_SHAKE_FREQ_MAX,
)

# Rising particles: pixel hearts from a pet, plus food/Z mood emotes while the pet
# is hungry/tired. The shared lifetime/position/fade math is the pure particles core;
# here we register the kinds (no Tk draw callback — the panel paints the cells the
# field returns) and paint them via the same pixel grids the Tk card uses.
_PANEL_FILL_RGB = (29, 31, 41)   # PANEL_FILL as RGB — the color a fading emote lerps to
HEART_PX = 2
HEART_RISE_PX = 34
HEART_LIFETIME_S = 0.85
MAX_HEARTS = 6
EMOTE_PX = 3
EMOTE_RISE_PX = 16
EMOTE_LIFETIME_S = 1.4
EMOTE_MIN_GAP_S = 3.0
EMOTE_MAX_GAP_S = 5.0
_ZZZ_FADE_RGB = (247, 243, 238)   # the "Z" starts near-white and fades to the panel
# Which mood emote (if any) to pop for an effective state.
_EMOTE_FOR_STATE = {"idle_hungry": "food", "idle_tired": "zzz", "sleeping": "zzz"}

_PARTICLE_KINDS = {
    "heart": particles.ParticleKind(
        name="heart", lifetime_s=HEART_LIFETIME_S, rise_px=HEART_RISE_PX,
        pixel_px=HEART_PX, tag="heart", max_count=MAX_HEARTS,
        fade_from=config.STATE_COLORS["happy"]),
    "food": particles.ParticleKind(
        name="food", lifetime_s=EMOTE_LIFETIME_S, rise_px=EMOTE_RISE_PX,
        pixel_px=EMOTE_PX, tag="emote", max_count=3, fade_from=None),
    "zzz": particles.ParticleKind(
        name="zzz", lifetime_s=EMOTE_LIFETIME_S, rise_px=EMOTE_RISE_PX,
        pixel_px=EMOTE_PX, tag="emote", max_count=3, fade_from=_ZZZ_FADE_RGB),
}


def _particle_cells(name: str, color: tuple[int, int, int] | None
                    ) -> tuple[list[str], dict[str, str]]:
    """The pixel grid + resolved char->color map for a particle kind. Hearts and Z's
    take the particle's live fade ``color``; food is a fixed little apple."""
    if name == "food":
        return sprite_pixel._FOOD, sprite_pixel._FOOD_COLORS
    hexed = _hex(color) if color is not None else CAPTION_FG
    if name == "zzz":
        return sprite_pixel._ZED, {"Z": hexed}
    return sprite_pixel._HEART, {"O": hexed}

# Caption per displayed face (mirrors the Tk STATE_CAPTIONS); unknown -> the raw.
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


def _hex(rgb: tuple[int, int, int]) -> str:
    # Clamp + round so a faded particle color (lerped floats) hexes cleanly too.
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _ease_out_cubic(t: float) -> float:
    """Decelerating ease for the evolution scale-up (fast start, gentle settle)."""
    return 1.0 - (1.0 - t) ** 3


def _anchor_xy(area: tuple[int, int, int, int], w: int, h: int,
               index: int) -> tuple[int, int]:
    """Bottom-right anchor within a work ``area`` (x, y, width, height), stacking
    extra sessions upward, clamped so a card can never land off-screen. Pure, so the
    placement math is unit-tested without a window."""
    ax, ay, aw, ah = area
    x = ax + aw - w - 20
    y = ay + ah - (h + 12) * (index + 1) - 20
    x = max(ax, min(x, ax + aw - w))
    y = max(ay, min(y, ay + ah - h))
    return x, y


def _paw_pixmap(px: int) -> QPixmap:
    """The pixel-art paw (shared with the Tk paw button) rasterized to a QPixmap.

    Reuses the pure paw grid + palette from ``ui_icons`` — the same coexistence
    pattern the sprite renderer uses for the creature grids; at the #63 cutover the
    pure icon data relocates alongside the sprite data."""
    from . import ui_icons

    return pixel_qt.grid_pixmap(ui_icons._ICONS["paw"], ui_icons.PALETTE, px)


class _CardPanel(QWidget):
    """The rounded panel: paints the panel, the (bobbing) creature, and the caption.

    A child of the translucent card so a ``QGraphicsDropShadowEffect`` applies to
    it (an effect on a translucent top-level is unreliable). Dumb by design — the
    card computes what to show and pushes it in via :meth:`show_art`."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(CARD_W, CARD_H)
        self._pixmap: QPixmap | None = None
        self._prev: QPixmap | None = None     # the fading-out face during a crossfade
        self._fade = 1.0                      # 0..1 — how much the new face is shown
        self._scale = 1.0                     # evolution scale-up (1.0 = settled)
        self._caption = ""
        self._bob = 0.0                       # sub-pixel float offset
        # The sub-agent badges: one shared mini-mascot pixmap, drawn ``_badge_count``
        # times in a centered row (all badges are identical, so a count is enough).
        self._badge: QPixmap | None = None
        self._badge_count = 0
        self._frame: tuple = ()               # last-shown art tuple (repaint guard)
        # Rising particles to paint this frame: (grid, char->color, cx, cy, px).
        self._particles: list[tuple[list[str], dict[str, str], float, float, int]] = []

    def show_art(self, pixmap: QPixmap | None, caption: str, bob: float, *,
                 prev: QPixmap | None = None, fade: float = 1.0, scale: float = 1.0,
                 badge: QPixmap | None = None, badge_count: int = 0) -> None:
        frame = (pixmap, caption, bob, prev, fade, scale, badge, badge_count)
        if frame == self._frame:          # nothing changed this tick — skip the repaint
            return
        self._frame = frame
        self._pixmap, self._caption, self._bob = pixmap, caption, bob
        self._prev, self._fade, self._scale = prev, fade, scale
        self._badge, self._badge_count = badge, badge_count
        self.update()

    def set_particles(self, cells: list[tuple[list[str], dict[str, str],
                                              float, float, int]]) -> None:
        """The rising particles (hearts / mood emotes) to paint on top this frame.
        Always repaints — particle positions change every tick."""
        self._particles = cells
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            panel = QRectF(0.5, 0.5, CARD_W - 1, CARD_H - 1)
            path = QPainterPath()
            path.addRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
            p.fillPath(path, QColor(PANEL_FILL))
            p.setPen(QColor(PANEL_EDGE))
            p.drawPath(path)

            self._paint_creature(p)

            p.setPen(QColor(CAPTION_FG))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(0, CAPTION_Y, CARD_W, 22),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       self._caption)

            self._paint_badges(p)
            self._paint_particles(p)
        finally:
            p.end()

    def _paint_creature(self, p: QPainter) -> None:
        """Blit the creature: crossfade the outgoing face under the incoming one, and
        scale for an evolution — as sub-pixel transforms over the crisp cached pixmaps
        (no SmoothPixmapTransform, so the pixels stay hard-edged)."""
        if self._pixmap is None:
            return
        if self._prev is not None and self._fade < 1.0:
            p.setOpacity(1.0 - self._fade)
            self._blit(p, self._prev)
            p.setOpacity(self._fade)
            self._blit(p, self._pixmap)
            p.setOpacity(1.0)
        else:
            self._blit(p, self._pixmap)

    def _blit(self, p: QPainter, pixmap: QPixmap) -> None:
        w, h = pixmap.width() * self._scale, pixmap.height() * self._scale
        x = (CARD_W - w) / 2
        y = CREATURE_CY - h / 2 + self._bob     # float y -> sub-pixel bob
        p.drawPixmap(QRectF(x, y, w, h), pixmap,
                     QRectF(0, 0, pixmap.width(), pixmap.height()))

    def _paint_badges(self, p: QPainter) -> None:
        """A centered row of identical sub-agent mini-mascots below the caption."""
        if self._badge is None or self._badge_count <= 0:
            return
        bw, bh = self._badge.width(), self._badge.height()
        center0 = CARD_W / 2 - (self._badge_count - 1) * BADGE_GAP / 2
        for i in range(self._badge_count):
            cx = center0 + i * BADGE_GAP
            p.drawPixmap(round(cx - bw / 2), BADGE_CY - bh // 2, self._badge)

    def _paint_particles(self, p: QPainter) -> None:
        """Paint each rising particle's pixel grid, centered at its (cx, cy), at
        sub-pixel (float) positions so the drift is smooth."""
        for grid, colors, cx, cy, px in self._particles:
            x0 = cx - len(grid[0]) * px / 2
            y0 = cy - len(grid) * px / 2
            for col, row, ch in grid_cells(grid):
                p.fillRect(QRectF(x0 + col * px, y0 + row * px, px, px),
                           QColor(colors[ch]))


class QtCard(QWidget):
    """A live, animated, draggable session card."""

    petted = Signal(str)          # session_id — emitted on a pet tap (manager awards coins)
    open_pet_requested = Signal()  # the paw button — the manager opens the Pet window

    def __init__(self, session_id: str, state: dict, index: int,
                 renderer: SpriteRenderer, *, pet_enabled: bool = False,
                 screen: QScreen | None = None) -> None:
        super().__init__()
        self.session_id = session_id
        self._renderer = renderer
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(CARD_W + 2 * SHADOW_PAD, CARD_H + 2 * SHADOW_PAD)

        self._panel = _CardPanel()
        # The panel fills the card body; make it click-through so drag / tap / hover
        # all reach this QtCard (the paw button, a mouse-opaque sibling, still clicks).
        self._panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._panel.setGraphicsEffect(shadow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SHADOW_PAD, SHADOW_PAD, SHADOW_PAD, SHADOW_PAD)
        layout.addWidget(self._panel)

        now = time.time()
        self._state = dict(state)
        self._raw = str(state.get("state", "idle"))
        self._overlay = Overlay(_OVERLAY_CONFIG, raw=self._raw, now=now)
        self._anim_t0 = now
        self._next_blink = now + random.uniform(BLINK_MIN_GAP_S, BLINK_MAX_GAP_S)
        self._face: str | None = None
        # The global pet dict, pushed by the manager each poll — projected to a look
        # (mood tints the idle face; stage/hat/flourish dress the sprite) via pet_view,
        # and read by the hover tooltip. None until the first push -> a bare baby with
        # a neutral "content" mood, matching the Tk card.
        self._pet_data: dict | None = None
        self._pixmap: QPixmap | None = None
        self._pixmap_key: tuple[object, ...] | None = None
        # Glow-up (#59) animation state: the fading-out face + when the crossfade
        # began, the evolution scale-up start, and the last stage (to detect a change).
        self._prev_pixmap: QPixmap | None = None
        self._fade_start = 0.0
        self._scale_start: float | None = None
        self._stage: str | None = None
        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None
        # Shake-to-dizzy bookkeeping: the last sampled drag point, the last move
        # vector, and the recent reversal timestamps.
        self._last_shake_pos: tuple[int, int] | None = None
        self._last_move: tuple[int, int] | None = None
        self._reversals: list[float] = []
        # Rising-particle field (hearts from a pet, food/Z mood emotes) + its emote
        # scheduler clock; ``_had_particles`` lets the last empty frame clear the panel.
        self._particles = particles.Particles(_PARTICLE_KINDS, panel_fill=_PANEL_FILL_RGB)
        self._next_emote = 0.0
        self._had_particles = False
        self._eff = self._raw
        # Satellite popups: the speech bubble (while notify present) and the pet hover
        # tooltip (pet-enabled only). Both follow the card and are dismissed on hide.
        self._bubble: QtBubble | None = None
        self._tooltip: QtStatsTooltip | None = None
        # Attention shake: the pure Shake seam owns the intensity ramp, the amplitude/
        # frequency derivation and the absolute-from-rest offset (it captures rest once
        # when a shake begins, then every frame moves to rest+offset — see shake.py for
        # the Windows drift bug that motivates). Its phase clock is aligned with the
        # animation clock so the sway is continuous. The last offset is tracked to skip
        # redundant moves.
        self._shake = shake.Shake(_SHAKE_CONFIG, t0=self._anim_t0)
        self._shake_offset: tuple[int, int] = (0, 0)

        # Simple hook-visualiser mode (pet disabled): the card shows the fixed life
        # stage picked in Settings, and there's no paw button (a read-only indicator).
        self._pet_enabled = pet_enabled

        # A small paw button (only when the pet is live) at the panel's top-left that
        # asks the manager to open the Pet window. As a child button it swallows its
        # own clicks, so pressing the paw neither drags nor pets the card.
        self._paw = self._build_paw() if pet_enabled else None

        self._place(index, screen)
        self._render(now)
        self._sync_bubble(self._state.get("notify"))

        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # --- state + animation ------------------------------------------------
    def set_state(self, state: dict) -> None:
        """Adopt a fresh hook state, celebrating a just-finished turn."""
        now = time.time()
        prev_raw = self._raw
        self._state = dict(state)
        raw = str(state.get("state", "idle"))
        if effective_state.should_celebrate(prev_raw, raw, bool(state.get("stumbled"))):
            self._overlay.note_celebrate(now)
        self._raw = raw
        self._overlay.note_raw(raw, now)
        self._render(now)
        self._sync_bubble(state.get("notify"))

    def set_pet(self, pet: dict) -> None:
        """Adopt the latest global pet (the manager pushes it every poll): it drives
        the idle-face mood + the sprite's stage/hat/flourish (via pet_view) and the
        hover tooltip. Cheap — an unchanged look re-renders no pixmap."""
        self._pet_data = pet
        if self._tooltip is not None:
            self._tooltip.set_pet(pet)
        self._render(time.time())

    def _effective_pet_view(self) -> PetView:
        """The look to draw, mirroring the Tk card's two edge cases: simple mode (pet
        off) shows the fixed life stage from Settings, and a pet-enabled card before
        the first push is a bare baby. Both are hatless with a neutral mood."""
        if not self._pet_enabled:
            return PetView(config.SIMPLE_STAGE, None, False, "content")
        if self._pet_data is None:
            return PetView("baby", None, False, "content")
        return pet_view(self._pet_data, now=time.time())

    def celebrate(self) -> None:
        """Play the happy hop + hearts — the host calls this when the pet is cared for
        (fed or played with in the Pet window), so care reads the same as an on-card pet."""
        now = time.time()
        self._overlay.note_celebrate(now)
        self._emit_hearts(now)
        self._render(now)

    def _tick(self) -> None:
        now = time.time()
        if self._raw == "idle" and now >= self._next_blink:
            self._overlay.note_blink(now)
            self._next_blink = (now + BLINK_DURATION_S
                                + random.uniform(BLINK_MIN_GAP_S, BLINK_MAX_GAP_S))
        self._render(now)
        self._apply_attention_shake(now)
        self._schedule_emote(now)
        self._update_particles(now)
        # Follow the card (including during the attention shake).
        if self._bubble is not None:
            self._reposition_bubble()
        if self._tooltip is not None:
            self._reposition_tooltip()

    def _render(self, now: float) -> None:
        view = self._effective_pet_view()
        eff = self._overlay.effective(self._raw, now, ts=self._state.get("ts"), mood=view.mood)
        self._eff = eff
        face = self._display_face(eff, now)
        self._face = face
        # The drawn sprite depends on the face AND the pet's look, so re-render the
        # pixmap when either changes (a re-dress or evolution, not just a new face).
        key = (face, view)
        if key != self._pixmap_key:
            self._pixmap_key = key
            self._adopt_pixmap(self._pixmap_for(face, view), view.stage, now)

        # Sub-pixel bob (float), the face crossfade, and the evolution scale-up.
        bob = 0.0 if (eff == "sleeping" or self._raw == "dead") else (
            BOB_AMPLITUDE * math.sin((now - self._anim_t0) * 2 * math.pi / BOB_PERIOD_S))
        fade = 1.0 if self._prev_pixmap is None else min(
            1.0, (now - self._fade_start) / CROSSFADE_S)
        if fade >= 1.0:
            self._prev_pixmap = None
        count = min(len(self._state.get("subagents") or []), MAX_BADGES)
        badge = self._badge_pixmap() if count else None
        self._panel.show_art(self._pixmap, _CAPTIONS.get(face, self._raw), bob,
                             prev=self._prev_pixmap, fade=fade, scale=self._scale_now(now),
                             badge=badge, badge_count=count)

    def _adopt_pixmap(self, pixmap: QPixmap, stage: str, now: float) -> None:
        """Swap in a new creature pixmap with the right transition: a stage change
        (evolution) scales up from small; any other face change crossfades; the very
        first render just appears."""
        if stage != self._stage and self._stage is not None:
            self._pixmap = pixmap
            self._prev_pixmap = None          # scale-up reads better than a crossfade here
            self._scale_start = now
        elif self._pixmap is not None:
            self._prev_pixmap = self._pixmap
            self._pixmap = pixmap
            self._fade_start = now
        else:
            self._pixmap = pixmap             # first render — no transition
        self._stage = stage

    def _scale_now(self, now: float) -> float:
        """The current evolution scale (1.0 once settled), eased from STAGE_SCALE_START."""
        if self._scale_start is None:
            return 1.0
        t = (now - self._scale_start) / STAGE_SCALE_S
        if t >= 1.0:
            self._scale_start = None
            return 1.0
        return STAGE_SCALE_START + (1.0 - STAGE_SCALE_START) * _ease_out_cubic(t)

    def _display_face(self, eff: str, now: float) -> str:
        ts = self._state.get("ts")
        stumbled_recent = (bool(self._state.get("stumbled"))
                           and ts is not None and (now - float(ts)) < STUMBLE_FACE_S)
        return effective_state.display_face(
            eff, tool=self._state.get("tool"),
            permission_mode=str(self._state.get("permission_mode", "")),
            stumbled_recent=stumbled_recent)

    def _badge_pixmap(self) -> QPixmap:
        """The shared sub-agent mini-mascot: a small ``working`` creature in the
        sub-agent accent (renderer-cached, so all badges are one pixmap)."""
        accent = _hex(config.SUBAGENT_COLOR)
        return self._renderer.creature(
            SpriteSpec(stage="baby", state="working", accent=accent), BADGE_MINI_PX)

    def _pixmap_for(self, face: str, view: PetView) -> QPixmap:
        if self._raw == "dead":
            return self._renderer.gravestone(CREATURE_PX)
        accent = _hex(config.STATE_COLORS.get(face, config.STATE_COLORS["idle"]))
        return self._renderer.creature(
            SpriteSpec(stage=view.stage, state=face, accent=accent,
                       hat=view.hat, flourish=view.flourish),
            CREATURE_PX)

    # --- paw button (opens the Pet window) -------------------------------
    def _build_paw(self) -> QPushButton:
        """A flat, pixel-art paw button anchored at the panel's top-left corner."""
        icon_px = PAW_PX * 12                      # the paw grid is 12 cells square
        button = QPushButton(self)
        button.setIcon(QIcon(_paw_pixmap(PAW_PX)))
        button.setIconSize(QSize(icon_px, icon_px))
        button.setFixedSize(icon_px + 8, icon_px + 8)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip("Open the Pet window")
        button.setStyleSheet(
            "QPushButton{background:transparent;border:none;border-radius:6px}"
            f"QPushButton:hover{{background:{PANEL_EDGE}}}")
        button.clicked.connect(lambda: self.open_pet_requested.emit())
        button.move(SHADOW_PAD + PAW_INSET, SHADOW_PAD + PAW_INSET)
        button.raise_()
        return button

    # --- drag + tap-to-pet ------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # Undo any active attention-shake first so the grab maps to the card's
            # true resting position (no jump as the shake is removed).
            self._reset_shake_offset()
            self._dismiss_tooltip()          # no hover tooltip while dragging
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_pos - self.frameGeometry().topLeft()
            self._last_shake_pos = None      # fresh shake-to-dizzy tracking per drag
            self._last_move = None
            self._reversals = []

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            point = event.globalPosition().toPoint()
            self.move(point - self._drag_offset)
            self._track_shake(point.x(), point.y())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            now = time.time()
            # A tap (no drag) pets the mascot. Gated like the Tk card: dead in simple
            # mode (a read-only indicator), and never while dizzy, or while the card is
            # waiting/dead (don't cheer over a "needs you" or a gravestone).
            if (self._pet_enabled and moved <= PET_TAP_MAX_DIST
                    and not self._overlay.is_dizzy(now)
                    and self._raw not in ("waiting", "dead")):
                self._overlay.note_celebrate(now)   # a happy hop
                self._emit_hearts(now)              # rising pixel hearts
                self.petted.emit(self.session_id)
                self._render(now)
            self._press_pos = None
            self._drag_offset = None

    # --- shake-to-dizzy ---------------------------------------------------
    def _track_shake(self, x: int, y: int) -> None:
        """Count rapid drag-direction reversals; enough within the window -> dizzy."""
        if self._last_shake_pos is None:
            self._last_shake_pos = (x, y)
            return
        dx = x - self._last_shake_pos[0]
        dy = y - self._last_shake_pos[1]
        if math.hypot(dx, dy) < SHAKE_MIN_DIST:
            return
        self._last_shake_pos = (x, y)
        if self._last_move is not None:
            dot = dx * self._last_move[0] + dy * self._last_move[1]
            if dot < 0:                       # direction flipped: one reversal
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
        self._render(now)

    # --- satellite popups (speech bubble + hover tooltip) -----------------
    def _panel_global(self) -> tuple[int, int, int, int]:
        """The visible panel's global rect — the card window is padded by SHADOW_PAD,
        so popups anchor to the panel, not the padded window."""
        return (self.x() + SHADOW_PAD, self.y() + SHADOW_PAD, CARD_W, CARD_H)

    def _card_bounds(self) -> tuple[int, int, int, int]:
        """The work area of the monitor the card sits on, so popups clamp to the same
        screen after the card is dragged across monitors (Windows); falls back to the
        card's Qt screen otherwise."""
        px, py, _pw, _ph = self._panel_global()
        area = osplatform.monitor_work_area_at(px, py)
        if area is not None:
            return area
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            return (g.x(), g.y(), g.width(), g.height())
        return (0, 0, 1920, 1080)

    def _sync_bubble(self, notify: dict | None) -> None:
        """Show / update / hide the speech bubble to match the session's notify."""
        if notify:
            message = notify.get("message") or "Claude needs your attention"
            if self._bubble is None:
                self._bubble = QtBubble(message)
                self._reposition_bubble()
                if self.isVisible():
                    self._bubble.show()
            else:
                self._bubble.set_message(message)
                self._reposition_bubble()
        elif self._bubble is not None:
            self._bubble.close()
            self._bubble = None

    def _reposition_bubble(self) -> None:
        if self._bubble is not None:
            px, py, pw, _ph = self._panel_global()
            self._bubble.place_above(px, py, pw, self._card_bounds())

    def _reposition_tooltip(self) -> None:
        if self._tooltip is not None:
            px, py, pw, ph = self._panel_global()
            self._tooltip.place_beside(px, py, pw, ph, self._card_bounds())

    def _dismiss_tooltip(self) -> None:
        if self._tooltip is not None:
            self._tooltip.close()
            self._tooltip = None

    def enterEvent(self, event) -> None:
        """Hover shows the pet-status tooltip. Suppressed in simple mode (it's pet
        status) and while dragging."""
        if (not self._pet_enabled or self._drag_offset is not None
                or self._tooltip is not None):
            return
        self._tooltip = QtStatsTooltip(self._pet_data)
        self._reposition_tooltip()
        self._tooltip.show()

    def leaveEvent(self, event) -> None:
        self._dismiss_tooltip()

    def hideEvent(self, event) -> None:
        """The tray hid the card: hide the bubble too and drop the tooltip."""
        if self._bubble is not None:
            self._bubble.hide()
        self._dismiss_tooltip()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        if self._bubble is not None:
            self._bubble.show()
        super().showEvent(event)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        if self._bubble is not None:
            self._bubble.close()
            self._bubble = None
        self._dismiss_tooltip()
        super().closeEvent(event)

    # --- rising particles (pet hearts + mood emotes) ----------------------
    def _emit_hearts(self, now: float) -> None:
        """A small staggered burst of hearts at the creature's upper-right (a pet)."""
        ox, oy = CARD_W / 2 + 20, CREATURE_CY - 14
        for _ in range(3):
            self._particles.emit("heart", (ox + random.uniform(-4, 6), oy), now,
                                 stagger_s=0.15, drift_range=(2.0, 12.0))

    def _schedule_emote(self, now: float) -> None:
        """Pop a mood emote (food when hungry, a drifting Z when tired/asleep) every
        few seconds while in that mood — the kind follows the effective state."""
        kind = _EMOTE_FOR_STATE.get(self._eff)
        if kind is None:
            self._next_emote = 0.0
            return
        if self._next_emote == 0.0:
            self._next_emote = now + random.uniform(EMOTE_MIN_GAP_S, EMOTE_MAX_GAP_S)
        elif now >= self._next_emote:
            origin = (CARD_W / 2 + 24 + random.uniform(-2, 6), CREATURE_CY - 20)
            self._particles.emit(kind, origin, now, drift_range=(2.0, 9.0))
            self._next_emote = now + random.uniform(EMOTE_MIN_GAP_S, EMOTE_MAX_GAP_S)

    def _update_particles(self, now: float) -> None:
        """Advance the field and hand the visible particles' cells to the panel. The
        last empty frame is pushed once so a finished burst clears."""
        cells = [
            (*_particle_cells(kind.name, color), x, y, kind.pixel_px)
            for kind, x, y, color in self._particles.advance(now)
        ]
        if cells or self._had_particles:
            self._panel.set_particles(cells)
            self._had_particles = bool(cells)

    # --- placement --------------------------------------------------------
    def _place(self, index: int, screen: QScreen | None) -> None:
        """Anchor to the bottom-right of the *home* monitor's work area (the one
        picked in Settings), stacking extra sessions upward. Enumerates monitors via
        Qt (:mod:`mascot.qt_screens`), the same index space the settings picker uses,
        so both honor the ``home_monitor`` setting consistently."""
        area = qt_screens.choose(config.HOME_MONITOR, qt_screens.work_areas())
        if area is None:
            screen = screen or QGuiApplication.primaryScreen()
            if screen is None:        # no screen (headless with no platform) — leave at 0,0
                return
            g = screen.availableGeometry()
            area = (g.x(), g.y(), g.width(), g.height())
        self.move(*_anchor_xy(area, self.width(), self.height(), index))

    # --- attention shake --------------------------------------------------
    def _apply_attention_shake(self, now: float) -> None:
        """Jostle the card while a prompt sits unanswered; the longer it's ignored,
        the wider and faster the shake — up to a frantic maximum. Delegates the math
        to the pure Shake seam; here we only gate it and push the geometry."""
        if self._drag_offset is not None:
            return  # the user is holding it; don't fight the drag
        elapsed = self._overlay.waiting_elapsed(now)
        if self._raw != "waiting" or elapsed is None or elapsed < config.SHAKE_AFTER_S:
            self._reset_shake_offset()   # not waiting, or still within the grace window
            return
        ox, oy = self._shake.offset(now, elapsed)
        self._set_shake_offset(ox, oy)

    def _set_shake_offset(self, ox: int, oy: int) -> None:
        """Apply the Shake seam's (ox, oy) as an absolute move to rest+(ox, oy). The
        seam holds the resting position (captured once when the shake begins), so the
        offset is always taken from a fixed anchor — no per-frame delta drift."""
        if (ox, oy) == self._shake_offset:
            return
        if not self._shake.is_shaking:      # starting to shake: remember where it rests
            self._shake.begin((self.x(), self.y()))
        rest = self._shake.rest_pos
        assert rest is not None             # begin() succeeded, so rest is captured
        self.move(rest[0] + ox, rest[1] + oy)
        self._shake_offset = (ox, oy)

    def _reset_shake_offset(self) -> None:
        """Settle the card back onto its captured resting position (zero shake)."""
        if self._shake_offset == (0, 0):
            return
        rest = self._shake.rest_pos
        if rest is not None:
            self.move(rest[0], rest[1])
        self._shake_offset = (0, 0)
        self._shake.end()
