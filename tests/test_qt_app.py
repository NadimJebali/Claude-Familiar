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

from mascot import config, pet_service, qt_app, qt_card, qt_ingest
from mascot.pet_view import PetView
from mascot.sprite_qt import QtPixmapRenderer, SpriteSpec


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _svc(tmp_path):
    """A live PetService over a throwaway pet.json, so tests never touch the real
    pet and each run starts from a fresh default pet."""
    return pet_service.PetService(
        pet_service.PetStore(tmp_path / "pet.json"), now=time.time())


class _RecordingRenderer:
    """The real renderer, capturing every SpriteSpec it's asked to draw so a test
    can assert the card dressed the sprite in the pushed stage / hat / flourish."""

    def __init__(self):
        self._real = QtPixmapRenderer()
        self.specs: list[SpriteSpec] = []

    def creature(self, spec, px):
        self.specs.append(spec)
        return self._real.creature(spec, px)

    def gravestone(self, px):
        return self._real.gravestone(px)


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
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
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


# --- QtCard: the pushed pet look (mood tint + stage/hat) ---------------------
# The manager only pushes a pet to a pet-enabled card, so these construct with
# pet_enabled=True (a simple-mode card ignores the push and shows the fixed stage).
def test_card_tints_the_idle_face_by_pet_mood(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    card.set_pet(PetView(stage="baby", hat=None, flourish=False, mood="hungry"))
    assert card._face == "idle_hungry"      # a hungry mood droops the idle face
    card.close()


def test_card_dresses_the_sprite_in_the_pushed_stage_hat_and_flourish(app):
    rec = _RecordingRenderer()
    card = qt_card.QtCard("s", _state("s", "idle"), 0, rec, pet_enabled=True)
    card.set_pet(PetView(stage="adult", hat="crown", flourish=True, mood="content"))
    spec = rec.specs[-1]
    assert (spec.stage, spec.hat, spec.flourish) == ("adult", "crown", True)
    card.close()


def test_card_celebrate_plays_the_happy_hop(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    card.celebrate()
    assert card._face == "happy"
    card.close()


# --- QtMascotApp as a PetHost: pet flows to cards + petting awards ------------
def test_manager_is_a_pet_host_and_pushes_the_pet_to_cards(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    assert mgr.pet_enabled is True
    mgr._on_sessions({"s1": _state("s1", "idle")})
    assert mgr.cards["s1"]._pet_view is not None   # a pet look was projected + pushed


def test_petting_a_card_awards_a_trickle_through_the_service(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    mgr._on_sessions({"s1": _state("s1", "idle")})
    before = mgr.get_pet().get("xp", 0)
    mgr._on_petted("s1")                            # a card emitted `petted`
    assert mgr.get_pet().get("xp", 0) > before      # PET grants a small XP trickle


def test_notify_care_celebrates_every_card(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    mgr._on_sessions({"a": _state("a", "idle"), "b": _state("b", "idle")})
    mgr.notify_care()
    assert mgr.cards["a"]._face == "happy"
    assert mgr.cards["b"]._face == "happy"


def test_open_pet_opens_an_in_process_window_sharing_the_host(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    mgr.open_pet()
    assert mgr._pet_window is not None
    assert mgr._pet_window._host is mgr            # hosted in-process (shared live pet)
    mgr._pet_window.close()


def test_simple_mode_is_not_a_live_pet_host(app, tmp_path, monkeypatch):
    monkeypatch.setattr(qt_app.config, "TAMAGOTCHI_ENABLED", False)
    mgr = qt_app.QtMascotApp(tmp_path)              # no service, pet disabled
    assert mgr.pet_enabled is False
    mgr._on_petted("s1")                            # both are safe no-ops in simple mode
    mgr.open_pet()
    assert mgr._pet_window is None


# --- QtCard: the paw button -> open the Pet window ---------------------------
def test_card_shows_a_paw_button_only_when_pet_enabled(app):
    on = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    off = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=False)
    assert on._paw is not None      # the paw opens the Pet window when the pet is live
    assert off._paw is None         # simple mode is a read-only indicator, no paw
    on.close()
    off.close()


def test_paw_click_requests_opening_the_pet_window(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    opened: list[bool] = []
    card.open_pet_requested.connect(lambda: opened.append(True))
    card._paw.click()
    assert opened == [True]
    card.close()


def test_manager_wires_the_card_paw_to_open_the_pet_window(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    mgr._on_sessions({"s1": _state("s1", "idle")})
    mgr.cards["s1"].open_pet_requested.emit()       # as the paw button would
    assert mgr._pet_window is not None
    mgr._pet_window.close()


# --- QtCard: the attention-shake jostle while a prompt sits unanswered --------
def _shake_frames(card, base, n=6):
    """Drive several animation frames well past the grace window (varied phase, so
    at least one frame produces a non-zero offset and the shake anchors)."""
    for i in range(n):
        card._apply_attention_shake(base + i * 0.05)


def test_a_non_waiting_card_never_jostles(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    _shake_frames(card, time.time() + config.SHAKE_AFTER_S + 5)
    assert not card._shake.is_shaking
    assert card._shake_offset == (0, 0)
    card.close()


def test_waiting_within_the_grace_window_does_not_jostle_yet(app):
    card = qt_card.QtCard("s", _state("s", "waiting"), 0, QtPixmapRenderer())
    card._apply_attention_shake(time.time() + 1)     # 1s < the (>=5s) grace window
    assert not card._shake.is_shaking
    card.close()


def test_a_long_ignored_waiting_card_jostles(app):
    card = qt_card.QtCard("s", _state("s", "waiting"), 0, QtPixmapRenderer())
    _shake_frames(card, time.time() + config.SHAKE_AFTER_S + 5)
    assert card._shake.is_shaking                     # it has anchored and is jostling
    card.close()


def test_answering_the_prompt_settles_the_card_back_to_rest(app):
    card = qt_card.QtCard("s", _state("s", "waiting"), 0, QtPixmapRenderer())
    future = time.time() + config.SHAKE_AFTER_S + 5
    _shake_frames(card, future)
    card.set_state(_state("s", "idle"))               # the user answered
    card._apply_attention_shake(future + 1.0)
    assert not card._shake.is_shaking
    assert card._shake_offset == (0, 0)
    card.close()


def test_dragging_suppresses_the_jostle(app):
    card = qt_card.QtCard("s", _state("s", "waiting"), 0, QtPixmapRenderer())
    card._drag_offset = card.frameGeometry().topLeft()   # simulate an active drag
    _shake_frames(card, time.time() + config.SHAKE_AFTER_S + 5)
    assert not card._shake.is_shaking                    # don't fight the user's drag
    card.close()


# --- QtCard: sub-agent badges ------------------------------------------------
def _with_subs(sid, n):
    st = _state(sid, "working")
    st["subagents"] = [{"type": "task"} for _ in range(n)]
    return st


def test_card_shows_a_badge_per_subagent(app):
    card = qt_card.QtCard("s", _with_subs("s", 2), 0, QtPixmapRenderer())
    assert card._panel._badge_count == 2
    assert card._panel._badge is not None
    card.close()


def test_card_caps_badges_at_four(app):
    card = qt_card.QtCard("s", _with_subs("s", 9), 0, QtPixmapRenderer())
    assert card._panel._badge_count == 4       # capped, never a crowd
    card.close()


def test_card_without_subagents_shows_no_badges(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    assert card._panel._badge_count == 0
    assert card._panel._badge is None
    card.close()


def test_badges_appear_and_clear_as_subagents_come_and_go(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    card.set_state(_with_subs("s", 3))
    assert card._panel._badge_count == 3
    card.set_state(_state("s", "working"))     # the sub-agents finished
    assert card._panel._badge_count == 0
    card.close()


# --- QtCard: placement math (pure) + home-monitor anchoring ------------------
def test_anchor_places_bottom_right_and_stacks_upward():
    area = (0, 0, 800, 600)
    x0, y0 = qt_card._anchor_xy(area, 100, 200, 0)
    x1, y1 = qt_card._anchor_xy(area, 100, 200, 1)
    assert (x0, y0) == (800 - 100 - 20, 600 - (200 + 12) - 20)
    assert x1 == x0 and y1 == y0 - (200 + 12)   # a second card stacks straight up


def test_anchor_clamps_into_the_work_area():
    x, y = qt_card._anchor_xy((0, 0, 300, 150), 100, 200, 3)  # too tall to fit
    assert y == 0 and 0 <= x <= 200              # clamped, never off-screen


def test_card_anchors_to_the_chosen_home_monitor(app, monkeypatch):
    monkeypatch.setattr(qt_card.osplatform, "enumerate_work_areas",
                        lambda: [(1000, 0, 800, 600)])
    monkeypatch.setattr(qt_card.osplatform, "primary_work_area",
                        lambda: (1000, 0, 800, 600))
    monkeypatch.setattr(qt_card.config, "HOME_MONITOR", 0)
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    expect = qt_card._anchor_xy((1000, 0, 800, 600), card.width(), card.height(), 0)
    assert (card.x(), card.y()) == expect        # placed on the chosen monitor
    card.close()


# --- QtCard: simple hook-visualiser mode -------------------------------------
def test_simple_mode_card_uses_the_configured_simple_stage(app, monkeypatch):
    monkeypatch.setattr(qt_card.config, "SIMPLE_STAGE", "adult")
    rec = _RecordingRenderer()
    qt_card.QtCard("s", _state("s", "idle"), 0, rec, pet_enabled=False)
    assert rec.specs[-1].stage == "adult"        # no pet -> the fixed simple stage
    assert rec.specs[-1].hat is None


def test_pet_enabled_card_before_first_push_is_a_bare_baby(app):
    rec = _RecordingRenderer()
    qt_card.QtCard("s", _state("s", "idle"), 0, rec, pet_enabled=True)
    assert rec.specs[-1].stage == "baby"
