"""The Qt session card — animated and interactive (issues #56, #57).

One frameless, per-pixel-translucent, always-on-top window per live Claude
session. Real ``WA_TranslucentBackground`` alpha gives a rounded panel with a
painted drop shadow on Windows **and** composited Linux, with no chroma-key hack.

The displayed face is computed by reusing the pure cores the Tk card uses — so
the port inherits their tested behaviour rather than re-deriving it:
``Overlay`` + ``effective_state`` layer dozing, the idle blink, the celebrate
hop, dizzy, the waiting glare, per-tool working faces, plan-mode and the stumble
over the raw hook state. The face is a cached pixmap from the ``SpriteRenderer``
seam, swapped only when the face (or the pet's look) actually changes; a ~25fps
timer drives the idle bob. The card is draggable, and a quick tap (no drag) pets it
— a happy hop plus a ``petted`` signal the manager turns into the coin trickle.

The manager pushes the global pet's look via :meth:`QtCard.set_pet`: the mood tints
the idle face and the stage/hat/flourish dress the sprite (parity with the Tk card).
A paw button at the panel's top-left (shown only when the pet is live) asks the
manager to open the Pet window via the ``open_pet_requested`` signal.

Still on the parity list (later #57 work / #60): sub-agent badges, the attention-
shake jostle, and home-monitor placement.
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
    QImage,
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

from . import config, effective_state
from .overlay import Overlay, OverlayConfig
from .pet_view import PetView
from .sprite_qt import SpriteRenderer, SpriteSpec

# --- card geometry (mirrors the Tk card's authored "small" size) ------------
CARD_W = 158
CARD_H = 211
CREATURE_PX = 5
CREATURE_CY = 68        # vertical center of the creature zone
CAPTION_Y = 132
SHADOW_PAD = 18         # room around the panel so the drop shadow isn't clipped

PANEL_FILL = "#1d1f29"
PANEL_EDGE = "#2a2d3b"
PANEL_RADIUS = 20
CAPTION_FG = "#e8e6ef"

# The paw button (opens the Pet window) sits at the panel's top-left, mirroring the
# Tk card. Its icon is the same pixel-art paw, rasterized once to a QPixmap.
PAW_PX = 2              # pixel size of the paw icon (a 12x12 grid -> 24px)
PAW_INSET = 8          # offset from the panel's top-left corner

# --- animation / interaction constants (match the Tk card) ------------------
ANIM_MS = 40            # ~25fps
BOB_AMPLITUDE = 4
BOB_PERIOD_S = 2.0
BLINK_DURATION_S = 0.12
BLINK_MIN_GAP_S = 4.0
BLINK_MAX_GAP_S = 7.0
DIZZY_DURATION_S = 2.0
CELEBRATE_DURATION_S = 1.5
STUMBLE_FACE_S = 8.0
THINKING_STALL_S = 180.0
WORKING_STALL_S = 270.0
PET_TAP_MAX_DIST = 5    # a press+release moving <= this (px) is a pet tap, not a drag

_OVERLAY_CONFIG = OverlayConfig(
    dizzy_duration_s=DIZZY_DURATION_S,
    celebrate_duration_s=CELEBRATE_DURATION_S,
    blink_duration_s=BLINK_DURATION_S,
    sleep_after_idle_s=config.SLEEP_AFTER_IDLE_S,
    shake_after_s=config.SHAKE_AFTER_S,
    thinking_stall_s=THINKING_STALL_S,
    working_stall_s=WORKING_STALL_S,
)

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
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _paw_pixmap(px: int) -> QPixmap:
    """The pixel-art paw (shared with the Tk paw button) rasterized to a QPixmap.

    Reuses the pure paw grid + palette from ``ui_icons`` — the same coexistence
    pattern the sprite renderer uses for the creature grids; at the #63 cutover the
    pure icon data relocates alongside the sprite data."""
    from . import ui_icons
    from .pixel_grid import grid_cells

    grid = ui_icons._ICONS["paw"]
    img = QImage(len(grid[0]) * px, len(grid) * px,
                 QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    try:
        for col, row, ch in grid_cells(grid):
            p.fillRect(col * px, row * px, px, px, QColor(ui_icons.PALETTE[ch]))
    finally:
        p.end()
    return QPixmap.fromImage(img)


class _CardPanel(QWidget):
    """The rounded panel: paints the panel, the (bobbing) creature, and the caption.

    A child of the translucent card so a ``QGraphicsDropShadowEffect`` applies to
    it (an effect on a translucent top-level is unreliable). Dumb by design — the
    card computes what to show and pushes it in via :meth:`show_art`."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(CARD_W, CARD_H)
        self._pixmap: QPixmap | None = None
        self._caption = ""
        self._bob = 0

    def show_art(self, pixmap: QPixmap | None, caption: str, bob: int) -> None:
        if pixmap is self._pixmap and caption == self._caption and bob == self._bob:
            return
        self._pixmap, self._caption, self._bob = pixmap, caption, bob
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

            if self._pixmap is not None:
                x = (CARD_W - self._pixmap.width()) // 2
                y = CREATURE_CY - self._pixmap.height() // 2 + self._bob
                p.drawPixmap(x, y, self._pixmap)

            p.setPen(QColor(CAPTION_FG))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(0, CAPTION_Y, CARD_W, 22),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       self._caption)
        finally:
            p.end()


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
        # The global pet's look (mood tints the idle face; stage/hat/flourish dress
        # the sprite), pushed by the manager each poll. None until the first push —
        # a bare baby with a neutral "content" mood, matching the Tk card.
        self._pet_view: PetView | None = None
        self._pixmap: QPixmap | None = None
        self._pixmap_key: tuple[object, ...] | None = None
        self._drag_offset: QPoint | None = None
        self._press_pos: QPoint | None = None

        # A small paw button (only when the pet is live) at the panel's top-left that
        # asks the manager to open the Pet window. As a child button it swallows its
        # own clicks, so pressing the paw neither drags nor pets the card.
        self._paw = self._build_paw() if pet_enabled else None

        self._place(index, screen)
        self._render(now)

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

    def set_pet(self, view: PetView) -> None:
        """Adopt the latest global pet look (the manager pushes it every poll): the
        mood tints the idle face and the stage/hat/flourish dress the sprite. Cheap —
        an unchanged look re-renders no pixmap (the view is part of the cache key)."""
        self._pet_view = view
        self._render(time.time())

    def celebrate(self) -> None:
        """Play the happy hop — the host calls this when the pet is cared for (fed or
        played with in the Pet window), so care reads the same as an on-card pet."""
        now = time.time()
        self._overlay.note_celebrate(now)
        self._render(now)

    def _tick(self) -> None:
        now = time.time()
        if self._raw == "idle" and now >= self._next_blink:
            self._overlay.note_blink(now)
            self._next_blink = (now + BLINK_DURATION_S
                                + random.uniform(BLINK_MIN_GAP_S, BLINK_MAX_GAP_S))
        self._render(now)

    def _render(self, now: float) -> None:
        mood = self._pet_view.mood if self._pet_view is not None else "content"
        eff = self._overlay.effective(self._raw, now, ts=self._state.get("ts"), mood=mood)
        face = self._display_face(eff, now)
        self._face = face
        # The drawn sprite depends on the face AND the pet's look, so re-render the
        # pixmap when either changes (a re-dress or evolution, not just a new face).
        key = (face, self._pet_view)
        if key != self._pixmap_key:
            self._pixmap_key = key
            self._pixmap = self._pixmap_for(face)
        bob = 0 if (eff == "sleeping" or self._raw == "dead") else round(
            BOB_AMPLITUDE * math.sin((now - self._anim_t0) * 2 * math.pi / BOB_PERIOD_S))
        self._panel.show_art(self._pixmap, _CAPTIONS.get(face, self._raw), bob)

    def _display_face(self, eff: str, now: float) -> str:
        ts = self._state.get("ts")
        stumbled_recent = (bool(self._state.get("stumbled"))
                           and ts is not None and (now - float(ts)) < STUMBLE_FACE_S)
        return effective_state.display_face(
            eff, tool=self._state.get("tool"),
            permission_mode=str(self._state.get("permission_mode", "")),
            stumbled_recent=stumbled_recent)

    def _pixmap_for(self, face: str) -> QPixmap:
        if self._raw == "dead":
            return self._renderer.gravestone(CREATURE_PX)
        view = self._pet_view
        stage = view.stage if view is not None else "baby"
        hat = view.hat if view is not None else None
        flourish = view.flourish if view is not None else False
        accent = _hex(config.STATE_COLORS.get(face, config.STATE_COLORS["idle"]))
        return self._renderer.creature(
            SpriteSpec(stage=stage, state=face, accent=accent, hat=hat, flourish=flourish),
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
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_pos - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press_pos is not None:
            moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            now = time.time()
            if moved <= PET_TAP_MAX_DIST and not self._overlay.is_dizzy(now):
                self._overlay.note_celebrate(now)   # a happy hop
                self.petted.emit(self.session_id)
                self._render(now)
            self._press_pos = None
            self._drag_offset = None

    # --- placement --------------------------------------------------------
    def _place(self, index: int, screen: QScreen | None) -> None:
        """Anchor bottom-right of the work area, stacking extra sessions upward,
        clamped so a card can never land off-screen."""
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:            # no screen (headless with no platform) — leave at 0,0
            return
        area = screen.availableGeometry()
        w, h = self.width(), self.height()
        x = area.x() + area.width() - w - 20
        y = area.y() + area.height() - (h + 12) * (index + 1) - 20
        x = max(area.x(), min(x, area.x() + area.width() - w))
        y = max(area.y(), min(y, area.y() + area.height() - h))
        self.move(x, y)
