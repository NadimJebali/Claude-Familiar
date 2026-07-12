"""The Compact theme window — one panel listing every session as a row (#75).

The Rust widget's shape: instead of one mascot card per session, a single
frameless always-on-top panel holds a slim row per live session —

    [dot] working - Edit      opus-4-8   x2   (ring)

an effort-colored activity dot, the state text (with the notify message inline
while Claude needs you — no popup bubbles in compact), the model, the live
sub-agent count, and a small context ring. Idle rows dim (the Rust widget's
trick); waiting rows wear the attention accent; **nothing jostles**. Row
backdrops keep the effort language at row scale via the pure ``effort`` math —
a static tint for the quiet levels, the purple shimmer for xhigh and the
rainbow cycle for max. The account-global usage bars (with the #69 stale
label) draw once at the bottom.

Each row's state text is its session's :class:`~mascot.presenter.SessionPresenter`
view rendered by :func:`~mascot.presenter.status_line` (#101) — the same decision
the Classic card's caption reads, so a row and a card can never disagree. The rows
therefore inherit the whole ladder now (the #52 pending-permission promotion, but
also the stall watchdog and dozing), not just the promotion they used to.

Every other row fact — the dim flag, the dot color, and the effort chrome (flat
tint + animated marker) — is a :class:`~mascot.presenter.SessionView` fact too, so
it is tested at that seam without painting; only :func:`~mascot.qt_card.model_label`
remains a local helper. The window itself paints directly (no child widgets) behind
a repaint-guard frame like the card's panel. A drag anywhere moves the panel; the tray's
show/hide and Quit cover it (wired in ``qt_app``). The pet layer is
orthogonal: PetService keeps earning and the tray "Pet…" window works — only
the card-side pet expressions have no home here.
"""
from __future__ import annotations

import math
import time
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPainterPath
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from . import config, effort, qt_screens, usage
from .presenter import _PANEL_FILL_RGB, SessionPresenter, bg_marker, status_line
from .qt_card import (
    PANEL_EDGE,
    PANEL_FILL,
    RAINBOW_WAVELENGTH_PX,
    RING_STROKE,
    RING_TRACK,
    RIPPLE_PERIOD_S,
    RIPPLE_WAVELENGTH_PX,
    USAGE_LABEL_FG,
    USAGE_PCT_FG,
    USAGE_TRACK,
    _anchor_xy,
    _hex,
    model_label,
)

# --- geometry -----------------------------------------------------------------
PANEL_W = 300
ROW_H = 34
PAD = 10                 # inner padding (panel edge -> content)
PANEL_RADIUS = 14
SHADOW_PAD = 18          # room for the drop shadow around the panel
ROW_RADIUS = 8
DOT_D = 10               # the activity dot's diameter
RING_D = 14              # the per-row context ring
ROW_EFFORT_PIXEL = 5     # the animated-effort cell at row scale (the card uses 10)
USAGE_BLOCK_H = 40       # the bottom bars block (two thin bars + labels)
BAR_H = 5

NOTIFY_MAX_CHARS = 34    # inline notify text budget before the ellipsis
ANIM_MS = 33             # ~30fps tick; the repaint guard skips unchanged frames

# _PANEL_FILL_RGB (the base the row effort wash lerps over) is imported from the
# presenter, which owns the effort-chrome decision (#103).
_TEXT_FG = "#e8e6ef"
_MUTED_FG = "#8b8fa3"
_EMPTY_TEXT = "no sessions"


# --- pure row content -----------------------------------------------------------
# Every per-row decision now comes from the session's SessionView (mascot.presenter):
# the state text (status_line, #101), the dot color and idle dimming (#102), and the
# effort chrome — the flat quiet tint (``effort_fill``) and the animated background
# marker (``effort_bg_kind``), with the waiting/dead-uncontested rule applied once for
# both themes (#103). The window builds each row from that view in :meth:`_row`; the
# painters below still own the pixel geometry (cell size, the ripple's origin dot).


# --- the panel (the child that actually paints) --------------------------------------
class _CompactPanel(QWidget):
    """The rounded panel that paints the rows — a CHILD of the translucent
    window so the ``QGraphicsDropShadowEffect`` applies reliably: an effect on
    a translucent TOP-LEVEL renders once into its cache and then ignores
    ``update()`` on real compositors (#88 — the frozen-rainbow bug). Same rule
    ``qt_card._CardPanel`` documents. Dumb by design — the window computes the
    frame and pushes it in via :meth:`show_frame`.

    The widget-size setting (#93) is one uniform scale ``k``, like the card's
    panel: rows stay authored at the small size and paint through a single
    ``p.scale(k, k)`` transform, the panel sized to match."""

    def __init__(self, parent: QWidget, k: float = 1.0) -> None:
        super().__init__(parent)
        self._k = k
        self._logical_h = 0                # the authored (pre-scale) panel height
        self._frame: tuple | None = None
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.setGraphicsEffect(shadow)

    def set_scaled_size(self, logical_h: int) -> None:
        """Size the panel to the authored height times the widget-size scale;
        the logical height is kept so paintEvent works in authored coordinates."""
        self._logical_h = logical_h
        self.setFixedSize(round(PANEL_W * self._k), round(logical_h * self._k))

    def show_frame(self, frame: tuple) -> None:
        """Adopt a computed frame; repaint only when it really changed."""
        if frame == self._frame:
            return
        self._frame = frame
        self.update()

    def paintEvent(self, _event) -> None:
        if self._frame is None:
            return
        rows, bars, stale = self._frame
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(self._k, self._k)      # the widget-size transform (#93)
            panel = QRectF(0.5, 0.5, PANEL_W - 1, self._logical_h - 1)
            path = QPainterPath()
            path.addRoundedRect(panel, PANEL_RADIUS, PANEL_RADIUS)
            p.fillPath(path, QColor(PANEL_FILL))
            p.setPen(QColor(PANEL_EDGE))
            p.drawPath(path)

            top = panel.y() + PAD
            if not rows:
                p.setPen(QColor(_MUTED_FG))
                p.setFont(QFont("Segoe UI", 9))
                p.drawText(QRectF(panel.x(), top, PANEL_W, ROW_H),
                           Qt.AlignmentFlag.AlignCenter, _EMPTY_TEXT)
                top += ROW_H
            for _sid, text, dot, dim, backdrop, bg, model, subs, ctx in rows:
                _paint_row(p, panel.x(), top, text, dot, dim, backdrop, bg,
                           model, subs, ctx)
                top += ROW_H
            _paint_usage(p, panel.x(), top, bars, stale)
        finally:
            p.end()


# --- the window --------------------------------------------------------------------
class CompactWindow(QWidget):
    """The single compact panel: a translucent top-level shell owning the
    state, anim timer, drag and placement; all painting happens on the
    :class:`_CompactPanel` child (rows painted straight onto it, no per-row
    widgets), sized to the session count."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.sessions: dict[str, dict[str, Any]] = {}
        # One presenter per session (#101): the row's state text is its
        # status_line, so a row reads the same decision a Classic card does.
        # Rows never hop/blink, so each presenter is built with celebrates=False
        # and is never sent a dizzy/blink note.
        self._presenters: dict[str, SessionPresenter] = {}
        self._usage: dict[str, Any] | None = None
        self._context: dict[str, float] = {}
        self._drag_offset: QPoint | None = None
        self._anim_t0 = time.time()

        # The widget-size scale (#93), snapshotted per window like the card's;
        # a live size change rebuilds the presentation (qt_app).
        self._k = float(config.UI_SCALE)
        self._panel = _CompactPanel(self, self._k)
        self._panel.move(SHADOW_PAD, SHADOW_PAD)

        self._resize_to(0)
        self._place()

        self._timer = QTimer(self)
        self._timer.setInterval(ANIM_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._tick()                          # seed the first frame

    # --- pushes from the app (the same feeds the cards get) --------------------
    def set_sessions(self, live: dict[str, dict[str, Any]]) -> None:
        """Adopt this poll's live snapshots; the panel grows/shrinks to fit."""
        count_changed = len(live) != len(self.sessions)
        self.sessions = dict(live)
        self._reconcile_presenters(live, time.time())
        if count_changed:
            self._resize_to(len(live))
        self._tick()

    def _presenter_for(self, sid: str, state: dict[str, Any],
                       now: float) -> SessionPresenter:
        """The session's presenter, created + usage-seeded on first sight (so a
        first tick already has the death override). The caller adopts the poll's
        state — a freshly created one holds only its raw until then."""
        presenter = self._presenters.get(sid)
        if presenter is None:
            presenter = SessionPresenter(
                raw=str(state.get("state", "idle")), now=now, celebrates=False)
            presenter.adopt_usage(self._usage)
            self._presenters[sid] = presenter
        return presenter

    def _reconcile_presenters(self, live: dict[str, dict[str, Any]],
                              now: float) -> None:
        """Keep exactly one presenter per live session: drop the gone, create the
        new, and adopt this poll's state onto each."""
        for sid in list(self._presenters):
            if sid not in live:
                del self._presenters[sid]
        for sid, state in live.items():
            self._presenter_for(sid, state, now).adopt_state(state, now)

    def set_usage(self, snapshot: dict[str, Any] | None) -> None:
        """Adopt the account-global usage snapshot for the bottom bars, and feed
        every presenter so the rows tombstone in step with the bars."""
        self._usage = snapshot
        for presenter in self._presenters.values():
            presenter.adopt_usage(snapshot)
        self._tick()

    def set_context(self, results: dict[str, float]) -> None:
        """Adopt the per-session context percentages for the row rings."""
        self._context = dict(results)
        self._tick()

    # --- geometry ----------------------------------------------------------------
    def _resize_to(self, rows: int) -> None:
        body_rows = max(1, rows)                 # an empty panel keeps one text row
        h = PAD + body_rows * ROW_H + USAGE_BLOCK_H + PAD
        self._panel.set_scaled_size(h)           # rounds once; the window follows it
        self.setFixedSize(self._panel.width() + 2 * SHADOW_PAD,
                          self._panel.height() + 2 * SHADOW_PAD)

    def _place(self) -> None:
        """Anchor to the bottom-right of the home monitor's work area (the same
        placement convention as the Classic cards, index 0)."""
        area = qt_screens.choose(config.HOME_MONITOR, qt_screens.work_areas())
        if area is None:
            screen = QGuiApplication.primaryScreen()
            if screen is None:
                return
            g = screen.availableGeometry()
            area = (g.x(), g.y(), g.width(), g.height())
        self.move(*_anchor_xy(area, self.width(), self.height(), 0))

    # --- animation: repaint only when the frame really changed --------------------
    def _session_view(self, sid: str, state: dict[str, Any], now: float):
        """The session's SessionView. The card feeds the presenter the global effort
        fallback (reading it touches settings, so it stays adapter-side); the view
        resolves the session's level over it and drives the dot + effort chrome.
        Robust against a usage/context push landing before the first set_sessions:
        a missing presenter is created on the spot."""
        return self._presenter_for(sid, state, now).view(
            now, effort_fallback=effort.settings_effort())

    def _tick(self) -> None:
        now = time.time()
        t = now - self._anim_t0
        # Every row fact — text, dot, dim, and the effort chrome — comes from the
        # session view now (#101-#103); account-level death (#91) is baked in through
        # the presenter's usage-death override, so no dead_until is threaded here.
        rows = tuple(self._row(sid, st, now, t) for sid, st in self.sessions.items())
        bars = tuple((b.label, b.pct, _hex(usage.bar_color(b.pct)))
                     for b in usage.usage_view(self._usage, now))
        self._panel.show_frame((rows, bars, usage.is_stale(self._usage, now)))

    def _row(self, sid: str, st: dict[str, Any], now: float, t: float) -> tuple:
        """One row's paint tuple, all from the session view: state text, dot color,
        dim, the effort backdrop (flat quiet tint) and animated marker, plus the
        model / sub-agent / ring trimmings. ``t`` is this panel's animation clock,
        supplied to the marker (the presenter owns the decision, not the phase)."""
        view = self._session_view(sid, st, now)
        return (sid, status_line(view, notify_max_chars=NOTIFY_MAX_CHARS),
                view.dot_color, view.dim,
                view.effort_fill,
                bg_marker(view.effort_bg_kind, t),
                model_label(st.get("model")),
                len(st.get("subagents") or []),
                self._context.get(sid))

    # --- drag anywhere ---------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self.frameGeometry().topLeft())

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


# --- pure painters (called by _CompactPanel with panel-local coordinates) ----------
def _paint_row(p: QPainter, px: float, top: float, text: str, dot: str,
               dim: bool, backdrop: str | None, bg: tuple, model: str, subs: int,
               ctx: float | None) -> None:
    row = QRectF(px + 6, top + 2, PANEL_W - 12, ROW_H - 4)
    if backdrop is not None:
        bpath = QPainterPath()
        bpath.addRoundedRect(row, ROW_RADIUS, ROW_RADIUS)
        p.fillPath(bpath, QColor(backdrop))
    if bg[0] != "solid":                 # max wash / xhigh rings, clipped to the row (#86)
        bpath = QPainterPath()
        bpath.addRoundedRect(row, ROW_RADIUS, ROW_RADIUS)
        p.save()
        p.setClipPath(bpath)
        _paint_row_bg(p, row, bg)
        p.restore()
    if dim:
        p.setOpacity(0.5)

    cy = row.y() + row.height() / 2
    p.setBrush(QColor(dot))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QRectF(row.x() + 8, cy - DOT_D / 2, DOT_D, DOT_D))
    p.setBrush(Qt.BrushStyle.NoBrush)

    right = row.right() - 8
    if ctx is not None:                       # the small per-row context ring
        ring = QRectF(right - RING_D, cy - RING_D / 2, RING_D, RING_D)
        pen = p.pen()
        pen.setStyle(Qt.PenStyle.SolidLine)
        pen.setWidth(RING_STROKE - 1)
        pen.setColor(QColor(RING_TRACK))
        p.setPen(pen)
        p.drawEllipse(ring)
        span = round(max(0.0, min(100.0, ctx)) / 100.0 * 360.0 * 16)
        if span > 0:
            pen.setColor(QColor(_hex(usage.bar_color(ctx))))
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, -span)
        right -= RING_D + 8

    p.setPen(QColor(_MUTED_FG))
    p.setFont(QFont("Segoe UI", 8))
    if subs:
        p.drawText(QRectF(right - 24, row.y(), 24, row.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"×{subs}")
        right -= 28
    if model:
        p.drawText(QRectF(right - 76, row.y(), 76, row.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   model)
        right -= 80

    p.setPen(QColor(_TEXT_FG))
    p.setFont(QFont("Segoe UI", 9))
    text_left = row.x() + 8 + DOT_D + 8
    p.drawText(QRectF(text_left, row.y(), max(0.0, right - text_left), row.height()),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
    if dim:
        p.setOpacity(1.0)


def _paint_row_bg(p: QPainter, row: QRectF, bg: tuple) -> None:
    """The animated effort backdrop at row scale (#86) — the card's pixel
    rainbow wash / ripple rings, in ROW_EFFORT_PIXEL cells; xhigh's rings
    radiate from the effort dot (the row's stand-in for the mascot)."""
    kind, t = bg[0], bg[1]
    x0, y0 = int(row.x()), int(row.y())
    if kind == "rainbow":
        for y in range(y0, int(row.bottom()) + 1, ROW_EFFORT_PIXEL):
            for x in range(x0, int(row.right()) + 1, ROW_EFFORT_PIXEL):
                f = (x - x0 + y - y0) / RAINBOW_WAVELENGTH_PX
                r, g, b = effort.rainbow_wash_color(_PANEL_FILL_RGB, t, f)
                p.fillRect(x, y, ROW_EFFORT_PIXEL, ROW_EFFORT_PIXEL,
                           QColor(r, g, b))
    elif kind == "ripple":
        half = ROW_EFFORT_PIXEL / 2
        dot_cx = row.x() + 8 + DOT_D / 2
        dot_cy = row.y() + row.height() / 2
        for y in range(y0, int(row.bottom()) + 1, ROW_EFFORT_PIXEL):
            for x in range(x0, int(row.right()) + 1, ROW_EFFORT_PIXEL):
                d = math.hypot(x + half - dot_cx, y + half - dot_cy)
                phase = d / RIPPLE_WAVELENGTH_PX - t / RIPPLE_PERIOD_S
                rgb = effort.ripple_color(_PANEL_FILL_RGB, phase)
                if rgb != _PANEL_FILL_RGB:   # gap cells stay bare -> base shows
                    p.fillRect(x, y, ROW_EFFORT_PIXEL, ROW_EFFORT_PIXEL,
                               QColor(*rgb))


def _paint_usage(p: QPainter, px: float, top: float,
                 bars: tuple, stale: bool) -> None:
    """The account-global 5h/7d bars, once, at the panel bottom — dimmed with a
    small "stale" caption when the snapshot has aged (#69)."""
    if not bars:
        return
    p.setFont(QFont("Segoe UI", 6))
    if stale:
        p.setOpacity(0.45)
    label_x, bar_x0 = px + 14, px + 40
    bar_x1, pct_x = px + PANEL_W - 60, px + PANEL_W - 14
    for i, (label, pct, color) in enumerate(bars):
        bar_top = top + 4 + i * (BAR_H + 6)
        row = QRectF(px, bar_top - 4, PANEL_W, BAR_H + 8)
        p.setPen(QColor(USAGE_LABEL_FG))
        p.drawText(QRectF(label_x - 14, row.y(), 28, row.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
        p.fillRect(QRectF(bar_x0, bar_top, bar_x1 - bar_x0, BAR_H),
                   QColor(USAGE_TRACK))
        frac = max(0.0, min(1.0, pct / 100.0))
        if frac > 0:
            p.fillRect(QRectF(bar_x0, bar_top, (bar_x1 - bar_x0) * frac, BAR_H),
                       QColor(color))
        p.setPen(QColor(USAGE_PCT_FG))
        p.drawText(QRectF(pct_x - 40, row.y(), 40, row.height()),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   f"{round(pct)}%")
    if stale:
        p.setOpacity(1.0)
        p.setPen(QColor(USAGE_LABEL_FG))
        block_h = len(bars) * (BAR_H + 6)
        p.drawText(QRectF(px, top + 2, PANEL_W, block_h),
                   Qt.AlignmentFlag.AlignCenter, "stale")
