"""The Qt session card (issue #56, walking skeleton).

One frameless, per-pixel-translucent, always-on-top window per live Claude
session — the Qt replacement for the Tk ``MascotWindow``. Real ``WA_TranslucentBackground``
alpha means a rounded panel with a painted drop shadow on Windows **and** composited
Linux, with no chroma-key hack. The creature face is a pre-rendered pixmap from the
``SpriteRenderer`` seam, blitted in ``paintEvent``; a state change swaps the pixmap
and repaints — no per-change scene rebuild.

This skeleton shows the state face, caption, and the gravestone for a dead session,
and stacks bottom-right like the Tk cards. Drag, tap-to-pet, shake, sub-agent
badges, the pet's stage/hat/mood, the bubble and tooltip are later slices
(#57/#58) — the point here is a live, event-driven, translucent card.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPixmap,
    QScreen,
)
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from . import config
from .sprite_qt import SpriteRenderer, SpriteSpec

# Card geometry (mirrors the Tk card's authored "small" size; the scale setting is
# a later slice). The creature pixmap is centered in the upper zone, caption below.
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

# Raw state -> caption. Display-only faces (moods, per-tool, blink) are a later
# slice; the skeleton captions the raw hook states.
_CAPTIONS = {
    "idle": "idle",
    "thinking": "thinking…",
    "working": "working…",
    "waiting": "needs you!",
    "compacting": "tidying memories…",
    "dead": "out of usage",
}


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


class _CardPanel(QWidget):
    """The opaque-to-itself rounded panel: paints the panel, creature, caption.

    Kept a child of the translucent card so a ``QGraphicsDropShadowEffect`` can be
    applied to it (an effect on a translucent top-level is unreliable)."""

    def __init__(self, renderer: SpriteRenderer) -> None:
        super().__init__()
        self._renderer = renderer
        self.setFixedSize(CARD_W, CARD_H)
        self._pixmap: QPixmap | None = None
        self._caption = ""

    def set_state(self, state: dict) -> None:
        raw = str(state.get("state", "idle"))
        if raw == "dead":
            self._pixmap = self._renderer.gravestone(CREATURE_PX)
        else:
            accent = _hex(config.STATE_COLORS.get(raw, config.STATE_COLORS["idle"]))
            spec = SpriteSpec(stage="baby", state=raw, accent=accent)
            self._pixmap = self._renderer.creature(spec, CREATURE_PX)
        self._caption = _CAPTIONS.get(raw, raw)
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
                y = CREATURE_CY - self._pixmap.height() // 2
                p.drawPixmap(x, y, self._pixmap)

            p.setPen(QColor(CAPTION_FG))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            p.drawText(QRectF(0, CAPTION_Y, CARD_W, 22),
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       self._caption)
        finally:
            p.end()


class QtCard(QWidget):
    """A live session card: frameless, translucent, always-on-top."""

    def __init__(self, session_id: str, state: dict, index: int,
                 renderer: SpriteRenderer, *, screen: QScreen | None = None) -> None:
        super().__init__()
        self.session_id = session_id
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(CARD_W + 2 * SHADOW_PAD, CARD_H + 2 * SHADOW_PAD)

        self._panel = _CardPanel(renderer)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._panel.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SHADOW_PAD, SHADOW_PAD, SHADOW_PAD, SHADOW_PAD)
        layout.addWidget(self._panel)

        self.set_state(state)
        self._place(index, screen)

    def set_state(self, state: dict) -> None:
        """Swap the face pixmap for the new state (no scene rebuild)."""
        self._panel.set_state(state)

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
