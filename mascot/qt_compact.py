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

Rows inherit the #52 pending-permission heuristic through the same pure core
the card uses (:func:`mascot.effective_state.promote_pending_tool`): a
main-thread tool stuck past the permission wait reads "needs you!".

The row content is decided by pure helpers (:func:`row_text`,
:func:`row_dim`, :func:`dot_color`, :func:`model_label`) so it is tested
without painting; the window itself paints directly (no child widgets) behind
a repaint-guard frame like the card's panel, animating only while an animated
effort level is on screen. A drag anywhere moves the panel; the tray's
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

from . import config, effective_state, effort, qt_screens, usage
from .qt_card import (
    PANEL_EDGE,
    PANEL_FILL,
    PERMISSION_WAIT_S,
    RAINBOW_WAVELENGTH_PX,
    RING_STROKE,
    RING_TRACK,
    RIPPLE_PERIOD_S,
    RIPPLE_WAVELENGTH_PX,
    USAGE_LABEL_FG,
    USAGE_PCT_FG,
    USAGE_TRACK,
    WORKING_STALL_S,
    _anchor_xy,
    _hex,
    file_basename,
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
_ROW_TINT_STRENGTH = 0.18   # quiet-level backdrop blend (the CLI's own 18%)
ANIM_MS = 33             # ~30fps tick; the repaint guard skips unchanged frames

_PANEL_FILL_RGB = (29, 31, 41)      # PANEL_FILL as RGB, for the effort blends
_TEXT_FG = "#e8e6ef"
_MUTED_FG = "#8b8fa3"
_EMPTY_TEXT = "no sessions"


# --- pure row content -----------------------------------------------------------
def _draw_raw(state: dict[str, Any], now: float) -> str:
    """The raw to display, with the #52 pending-permission promotion applied —
    the same pure core the Classic card runs each frame."""
    ts = state.get("ts")
    return effective_state.promote_pending_tool(
        str(state.get("state", "idle")), state.get("tool"),
        ts if isinstance(ts, (int, float)) else None, now,
        permission_wait_s=PERMISSION_WAIT_S, working_stall_s=WORKING_STALL_S)


def row_text(state: dict[str, Any], now: float,
             dead_until: float | None = None) -> str:
    """The row's state text. Waiting (real or promoted) carries the notify
    message inline, truncated — compact has no popup bubbles. An exhausted
    account (#91) overrides everything with the reset time."""
    if dead_until is not None:
        return "out of usage · resets " + time.strftime(
            "%H:%M", time.localtime(dead_until))
    raw = _draw_raw(state, now)
    if raw == "dead":
        return "out of usage"
    if raw == "waiting":
        notify = state.get("notify")
        message = notify.get("message", "") if isinstance(notify, dict) else ""
        if message:
            if len(message) > NOTIFY_MAX_CHARS:
                message = message[:NOTIFY_MAX_CHARS] + "…"
            return f"needs you! · {message}"
        return "needs you!"
    if raw == "compacting":
        return "tidying memories…"
    if raw in ("thinking", "working") and state.get("permission_mode") == "plan":
        return "planning…"
    if raw == "thinking":
        return "thinking…"
    if raw == "working":
        tool = state.get("tool")
        # The sticky-per-turn file (#85) rides along — with the tool while one
        # runs, alone between tools (it outlives each millisecond PostToolUse).
        parts = [p for p in (tool, file_basename(state.get("file"))) if p]
        return "working · " + " · ".join(parts) if parts else "working…"
    return str(raw)


def row_dim(state: dict[str, Any], now: float,
            dead_until: float | None = None) -> bool:
    """Idle rows dim (the Rust widget's trick); every active state reads full —
    and so does the tombstone (#91), which must not whisper."""
    if dead_until is not None:
        return False
    return _draw_raw(state, now) == "idle"


def dot_color(state: dict[str, Any], now: float,
              dead_until: float | None = None) -> str:
    """The activity dot: attention states win (waiting — real or promoted — and
    dead wear their accents), then the resolved effort tint, then the state
    accent (unknown states read as idle grey)."""
    if dead_until is not None:
        return _hex(config.STATE_COLORS["dead"])
    raw = _draw_raw(state, now)
    if raw in ("waiting", "dead"):
        return _hex(config.STATE_COLORS[raw])
    level = effort.resolve(state.get("effort", ""), effort.settings_effort())
    if level:
        return _hex(effort.TINTS[level])
    return _hex(config.STATE_COLORS.get(raw, config.STATE_COLORS["idle"]))


def row_backdrop(state: dict[str, Any], now: float, t: float,
                 dead_until: float | None = None) -> str | None:
    """The row's flat effort tint, or ``None`` for the plain panel: the pure
    ``effort.panel_fill`` static 18% tint for low/medium/high. The two animated
    levels (xhigh/max) return ``None`` here — :func:`row_bg` owns them with the
    card's pixel animations (#86). Waiting/dead stay uncontested."""
    if dead_until is not None or _draw_raw(state, now) in ("waiting", "dead"):
        return None
    level = effort.resolve(state.get("effort", ""), effort.settings_effort())
    if level in ("xhigh", "max"):
        return None
    rgb = effort.panel_fill(level, _PANEL_FILL_RGB, t)
    return None if rgb is None else _hex(rgb)


def row_bg(state: dict[str, Any], now: float, t: float,
           dead_until: float | None = None) -> tuple:
    """The row's animated-background marker — the card's ``panel_bg`` split at
    row scale (#86): ``("rainbow", t)`` for max, ``("ripple", t)`` for xhigh,
    ``("solid",)`` otherwise (waiting/dead stay uncontested, like the tint)."""
    if dead_until is not None or _draw_raw(state, now) in ("waiting", "dead"):
        return ("solid",)
    level = effort.resolve(state.get("effort", ""), effort.settings_effort())
    if level == "max":
        return ("rainbow", round(t, 3))
    if level == "xhigh":
        return ("ripple", round(t, 3))
    return ("solid",)


def _has_animated(sessions: dict[str, dict[str, Any]]) -> bool:
    """Whether any row wears an animated effort level (xhigh/max) — if not, the
    frame signature drops the clock and the panel repaints only on data changes."""
    fallback = effort.settings_effort()
    return any(effort.resolve(st.get("effort", ""), fallback) in ("xhigh", "max")
               for st in sessions.values())


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
        if count_changed:
            self._resize_to(len(live))
        self._tick()

    def set_usage(self, snapshot: dict[str, Any] | None) -> None:
        """Adopt the account-global usage snapshot for the bottom bars."""
        self._usage = snapshot
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
    def _tick(self) -> None:
        now = time.time()
        # Account-level death (#91): a full usage window tombstones every row.
        dead_until = usage.exhausted_until(self._usage, now)
        rows = tuple(
            (sid, row_text(st, now, dead_until), dot_color(st, now, dead_until),
             row_dim(st, now, dead_until),
             row_backdrop(st, now, now - self._anim_t0, dead_until),
             row_bg(st, now, now - self._anim_t0, dead_until),
             model_label(st.get("model")),
             len(st.get("subagents") or []),
             self._context.get(sid))
            for sid, st in self.sessions.items()
        )
        bars = tuple((b.label, b.pct, _hex(usage.bar_color(b.pct)))
                     for b in usage.usage_view(self._usage, now))
        self._panel.show_frame((rows, bars, usage.is_stale(self._usage, now)))

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
