"""Compact-theme window tests (PRD #67, #75): one panel, a row per session.

The row content (text, dot color, dimming, backdrop) is pure and tested
directly — including the pending-permission promotion the rows inherit from
the #52 heuristic. The window itself is exercised offscreen: sizing follows
the session count, painting smokes clean across every row flavor, and a drag
moves the panel.
"""
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mascot import config, effort, qt_compact


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _state(sid="s", st="idle", **over):
    base = {"session_id": sid, "state": st, "ts": time.time(),
            "subagents": [], "schema_version": 1}
    base.update(over)
    return base


# --- model_label ---------------------------------------------------------------
def test_model_label_strips_prefix_and_date():
    assert qt_compact.model_label("claude-opus-4-8") == "opus-4-8"
    assert qt_compact.model_label("claude-haiku-4-5-20251001") == "haiku-4-5"
    assert qt_compact.model_label("") == ""
    assert qt_compact.model_label("weird") == "weird"


# The row's state text (row_text) moved onto the presenter as status_line — its
# behaviour is covered at that seam in tests/test_session_view.py. What remains
# here is the row chrome the compact panel still decides from the raw dict.
def test_shadow_lives_on_a_child_panel_not_the_translucent_top_level(app):
    # #88: a QGraphicsDropShadowEffect on a translucent TOP-LEVEL renders once
    # into its cache and then ignores update() on real compositors — the frozen
    # first frame. Same rule qt_card._CardPanel documents; the effect (and the
    # painting) must live on a child.
    w = qt_compact.CompactWindow()
    assert w.graphicsEffect() is None
    assert w._panel.graphicsEffect() is not None
    w.close()


# The effort chrome (flat quiet tint + the rainbow/ripple markers) and its
# waiting/dead-uncontested rule now live on the SessionView — covered at that seam
# in tests/test_session_view.py. The window smoke test below still paints a max /
# xhigh / waiting / dead spread to prove the panel renders them clean.


# --- the window -------------------------------------------------------------------
def test_compact_geometry_follows_the_widget_size(app, monkeypatch):
    # #93: the compact panel scales with Settings' widget size like the card —
    # window + panel sized by UI_SCALE, painting through one uniform transform.
    monkeypatch.setattr(config, "UI_SCALE", 1.4)
    win = qt_compact.CompactWindow()
    win.set_sessions({"a": _state("a"), "b": _state("b", "working")})
    logical_h = qt_compact.PAD * 2 + 2 * qt_compact.ROW_H + qt_compact.USAGE_BLOCK_H
    assert win._panel.width() == round(qt_compact.PANEL_W * 1.4)
    assert win._panel.height() == round(logical_h * 1.4)
    assert win.width() == round(qt_compact.PANEL_W * 1.4) + 2 * qt_compact.SHADOW_PAD
    win.repaint()                                       # the paint smoke, at scale
    win.grab()
    win.close()


def test_window_height_follows_the_session_count(app):
    win = qt_compact.CompactWindow()
    win.set_sessions({})
    empty_h = win.height()
    win.set_sessions({"a": _state("a"), "b": _state("b", "working")})
    assert win.height() == empty_h + qt_compact.ROW_H     # empty row -> two rows
    # Outer size includes the drop-shadow margin, like the Classic card.
    assert win.width() == qt_compact.PANEL_W + 2 * qt_compact.SHADOW_PAD
    win.close()


def test_window_paints_every_row_flavor_clean(app, monkeypatch):
    monkeypatch.setattr(effort, "settings_effort", lambda *a, **k: "")
    now = time.time()
    win = qt_compact.CompactWindow()
    win.set_sessions({
        "a": _state("a", "working", tool="Edit", effort="max",
                    subagents=[{"id": "x", "type": "t", "description": ""}]),
        "b": _state("b", "idle", effort="xhigh"),
        "c": _state("c", "waiting", notify={"message": "Approve?", "type": "q"}),
        "d": _state("d", "dead"),
    })
    win.set_usage({"ts": now - 3600,                       # aged -> the stale label
                   "five_hour": {"used_percentage": 76, "resets_at": now + 999},
                   "seven_day": {"used_percentage": 93, "resets_at": now + 999}})
    win.set_context({"a": 64.0, "b": 30.0})
    win.repaint()                                          # the paint smoke
    win.grab()
    win.close()


def test_window_drag_moves_the_panel(app):
    win = qt_compact.CompactWindow()
    win.set_sessions({"a": _state("a")})
    win.move(300, 300)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(10, 10), QPointF(310, 310),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(10, 10), QPointF(360, 340),
                       Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    win.mousePressEvent(press)
    win.mouseMoveEvent(move)
    assert (win.x(), win.y()) == (350, 330)
    win.close()
