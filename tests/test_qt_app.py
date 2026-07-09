"""Tests for the Qt walking skeleton — ingestion, manager reconcile, card (#56).

The renderer has its own suite (test_sprite_qt.py). Here we cover the testable
seams of the live widget: the off-UI-thread read + schema filter, the manager
turning snapshots into cards via the roster core, and the card constructing and
swapping state. All headless (QT_QPA_PLATFORM=offscreen); the translucency, drop
shadow and stacking are verified visually with `python demo.py --qt`.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QPointF, Qt, QThreadPool
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from mascot import qt_app, qt_card, qt_ingest
from mascot.sprite_qt import QtPixmapRenderer


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _state(sid: str, st: str = "idle") -> dict:
    return {"session_id": sid, "state": st, "ts": 1_000_000.0,
            "subagents": [], "schema_version": 1}


def _write(state_dir, sid: str, **over) -> None:
    st = _state(sid)
    st.update(over)
    (state_dir / f"{sid}.json").write_text(json.dumps(st), encoding="utf-8")


# --- read_live: liveness + schema filter (pure enough to test without a loop) --
def test_read_live_returns_valid_live_sessions(tmp_path):
    _write(tmp_path, "s1", ts=time.time())
    live = qt_ingest.read_live(tmp_path, time.time())
    assert "s1" in live


def test_read_live_drops_a_schema_invalid_file(tmp_path):
    now = time.time()
    _write(tmp_path, "ok", ts=now)
    # A live file (fresh ts, no owner) that violates the contract: no "state" key.
    (tmp_path / "bad.json").write_text(
        json.dumps({"session_id": "bad", "ts": now, "subagents": []}), encoding="utf-8")
    live = qt_ingest.read_live(tmp_path, now)
    assert "ok" in live
    assert "bad" not in live   # dropped by schema.is_valid_session_state


def test_read_live_drops_a_stale_ownerless_session(tmp_path):
    now = 1_000_000.0
    _write(tmp_path, "old", ts=now - 10_000)   # long stale, no owner -> not live
    assert qt_ingest.read_live(tmp_path, now) == {}


# --- SessionIngest: emits snapshots (sync and off-thread) ---------------------
def test_read_now_emits_and_returns_live(app, tmp_path):
    _write(tmp_path, "s1", ts=time.time())
    ingest = qt_ingest.SessionIngest(tmp_path)
    received: list[dict] = []
    ingest.sessions_changed.connect(received.append)
    snaps = ingest.read_now()
    assert "s1" in snaps
    assert received and "s1" in received[0]


def test_refresh_reads_off_thread_and_emits_on_this_thread(app, tmp_path):
    _write(tmp_path, "s1", ts=time.time())
    ingest = qt_ingest.SessionIngest(tmp_path)
    received: list[dict] = []
    ingest.sessions_changed.connect(received.append)
    ingest.refresh()
    QThreadPool.globalInstance().waitForDone(3000)   # let the worker finish
    app.processEvents()                              # deliver the queued signal
    assert received and "s1" in received[0]


# --- QtMascotApp: reconcile snapshots into cards -----------------------------
def test_manager_creates_updates_and_destroys_cards(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path)
    mgr._on_sessions({"s1": _state("s1", "working"), "s2": _state("s2", "idle")})
    assert set(mgr.cards) == {"s1", "s2"}

    mgr._on_sessions({"s1": _state("s1", "idle")})   # s2 vanished
    assert set(mgr.cards) == {"s1"}

    mgr._on_sessions({})                             # all gone
    assert mgr.cards == {}


# --- QtCard: constructs and swaps state without error ------------------------
def test_card_constructs_and_swaps_state(app):
    renderer = QtPixmapRenderer()
    card = qt_card.QtCard("s1", _state("s1", "working"), 0, renderer)
    assert card.session_id == "s1"
    card.set_state(_state("s1", "dead"))    # gravestone path
    card.set_state(_state("s1", "waiting"))
    card.close()


def test_finishing_a_turn_celebrates(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    card.set_state(_state("s", "idle"))     # active -> idle earns the happy hop
    assert card._face == "happy"
    card.close()


def _tap(card, x=5, y=5):
    pos = QPointF(x, y)
    press = QMouseEvent(QEvent.Type.MouseButtonPress, pos, pos,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    release = QMouseEvent(QEvent.Type.MouseButtonRelease, pos, pos,
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    card.mousePressEvent(press)
    card.mouseReleaseEvent(release)


def test_tap_emits_petted_and_hops(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    got: list[str] = []
    card.petted.connect(got.append)
    _tap(card)                              # press+release in place = a pet tap
    assert got == ["s"]
    assert card._face == "happy"            # petting plays the happy hop
    card.close()
