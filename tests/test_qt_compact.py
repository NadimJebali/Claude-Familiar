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
from mascot.qt_card import PERMISSION_WAIT_S, _hex


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


# --- row_text -------------------------------------------------------------------
def test_row_text_names_the_state_and_tool():
    now = time.time()
    assert qt_compact.row_text(_state(st="working", tool="Edit"), now) == "working · Edit"
    assert qt_compact.row_text(_state(st="working", tool=None), now) == "working…"
    assert qt_compact.row_text(_state(st="thinking"), now) == "thinking…"
    assert qt_compact.row_text(
        _state(st="thinking", permission_mode="plan"), now) == "planning…"
    assert qt_compact.row_text(_state(st="compacting"), now) == "tidying memories…"
    assert qt_compact.row_text(_state(st="dead"), now) == "out of usage"
    assert qt_compact.row_text(_state(st="idle"), now) == "idle"


def test_row_text_carries_the_working_file():
    # #85: the sticky-per-turn file joins the row — with the tool while one runs,
    # alone between tools (the file outlives each millisecond-fast PostToolUse).
    now = time.time()
    st = _state(st="working", tool="Edit", file=r"C:\repo\mascot\qt_app.py")
    assert qt_compact.row_text(st, now) == "working · Edit · qt_app.py"
    st["tool"] = None
    assert qt_compact.row_text(st, now) == "working · qt_app.py"


def test_row_bg_markers_follow_the_effort_level():
    # #86: the card's panel_bg split at row scale — the animated levels get a
    # marker for the pixel wash/ripple; everything else stays a solid panel.
    now = time.time()
    assert qt_compact.row_bg(_state(st="working", effort="max"), now, 1.234) == ("rainbow", 1.234)
    assert qt_compact.row_bg(_state(st="working", effort="xhigh"), now, 2.0) == ("ripple", 2.0)
    assert qt_compact.row_bg(_state(st="working", effort="high"), now, 2.0) == ("solid",)
    assert qt_compact.row_bg(_state(st="waiting", effort="max"), now, 2.0) == ("solid",)


def test_row_backdrop_cedes_animated_levels_to_row_bg():
    # #86: xhigh/max rows keep the plain base (the overlay owns them); the
    # static levels keep their flat tint.
    now = time.time()
    assert qt_compact.row_backdrop(_state(st="working", effort="max"), now, 1.0) is None
    assert qt_compact.row_backdrop(_state(st="working", effort="xhigh"), now, 1.0) is None
    assert qt_compact.row_backdrop(_state(st="working", effort="high"), now, 1.0) is not None


def test_row_text_waiting_carries_the_notify_inline_truncated():
    st = _state(st="waiting",
                notify={"message": "Allow this Bash command to run tests?" * 3,
                        "type": "permission"})
    text = qt_compact.row_text(st, time.time())
    assert text.startswith("needs you! · Allow this Bash command")
    assert len(text) <= len("needs you! · ") + qt_compact.NOTIFY_MAX_CHARS + 1  # +ellipsis


def test_row_text_promotes_a_long_pending_tool_to_needs_you():
    # The #52 heuristic, inherited by the rows: a main-thread tool with no closing
    # PostToolUse past the permission wait reads as "needs you!".
    ts = time.time() - PERMISSION_WAIT_S - 5
    st = _state(st="working", tool="Bash", ts=ts)
    assert qt_compact.row_text(st, time.time()) == "needs you!"
    fresh = _state(st="working", tool="Bash", ts=time.time())
    assert qt_compact.row_text(fresh, time.time()) == "working · Bash"


# --- row_dim + dot_color ----------------------------------------------------------
def test_row_dim_only_for_idle():
    now = time.time()
    assert qt_compact.row_dim(_state(st="idle"), now) is True
    for st in ("working", "thinking", "waiting", "dead", "compacting"):
        assert qt_compact.row_dim(_state(st=st), now) is False


def test_dot_color_waiting_and_dead_win_then_effort_then_state(monkeypatch):
    monkeypatch.setattr(effort, "settings_effort", lambda *a, **k: "")
    now = time.time()
    assert qt_compact.dot_color(_state(st="waiting"), now) == \
        _hex(config.STATE_COLORS["waiting"])
    assert qt_compact.dot_color(_state(st="dead"), now) == \
        _hex(config.STATE_COLORS["dead"])
    # A pending-promoted tool wears the waiting accent too.
    pending = _state(st="working", tool="Bash", ts=now - PERMISSION_WAIT_S - 5)
    assert qt_compact.dot_color(pending, now) == _hex(config.STATE_COLORS["waiting"])
    # Busy with an effort -> the effort tint; without -> the state accent.
    assert qt_compact.dot_color(_state(st="working", effort="high"), now) == \
        _hex(effort.TINTS["high"])
    assert qt_compact.dot_color(_state(st="working"), now) == \
        _hex(config.STATE_COLORS["working"])


# --- the window -------------------------------------------------------------------
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
