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

from mascot import config, effort, pet_service, qt_app, qt_card, qt_ingest, qt_popups, usage
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


def _pet(**over):
    """A full, valid pet dict the card can project + a tooltip can read."""
    p = {
        "name": "Pixel", "born": 0.0, "last_seen": 0.0,
        "hunger": 60, "happiness": 60, "energy": 60,
        "coins": 100, "xp": 0, "coins_today": 0, "last_award_date": "",
        "inventory": {}, "cooldowns": {}, "wardrobe": [], "equipped": {},
        "days_active": 0,
    }
    p.update(over)
    return p


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
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    got: list[str] = []
    card.petted.connect(got.append)
    _tap(card)                              # press+release in place = a pet tap
    assert got == ["s"]
    assert card._face == "happy"            # petting plays the happy hop
    card.close()


def test_a_tap_in_simple_mode_is_dead(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=False)
    got: list[str] = []
    card.petted.connect(got.append)
    _tap(card)
    assert got == []                        # a read-only indicator — no pet, no hop
    assert card._face != "happy"
    card.close()


@pytest.mark.parametrize("raw", ["waiting", "dead"])
def test_no_petting_while_waiting_or_dead(app, raw):
    card = qt_card.QtCard("s", _state("s", raw), 0, QtPixmapRenderer(), pet_enabled=True)
    got: list[str] = []
    card.petted.connect(got.append)
    _tap(card)
    assert got == []                        # don't cheer over "needs you" / a gravestone
    card.close()


# --- QtCard: shake-to-dizzy easter egg ---------------------------------------
def test_vigorous_shaking_makes_the_card_dizzy(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    x = 100
    for _ in range(8):                       # a fast left/right zig-zag drag
        x += 20
        card._track_shake(x, 100)
        x -= 20
        card._track_shake(x, 100)
    assert card._overlay.is_dizzy(time.time())
    card.close()


def test_a_gentle_drag_does_not_make_the_card_dizzy(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    for x in range(100, 200, 10):            # a straight, one-direction drag
        card._track_shake(x, 100)
    assert not card._overlay.is_dizzy(time.time())
    card.close()


# --- QtCard: rising particles (pet hearts + mood emotes) ---------------------
def test_petting_emits_rising_hearts(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    _tap(card)
    assert card._particles.alive("heart", time.time())    # a heart burst spawned
    card.close()


def test_hearts_paint_then_clear_from_the_panel(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    t0 = time.time()
    card._emit_hearts(t0)
    card._update_particles(t0 + 0.2)                      # past the stagger -> visible
    assert card._panel._particles                        # cells handed to the panel
    card._update_particles(t0 + qt_card.HEART_LIFETIME_S + 1)   # all expired
    assert card._panel._particles == []                  # the last frame cleared them
    card.close()


def test_a_hungry_mood_pops_a_food_emote(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    card.set_pet(_pet(hunger=10, happiness=80, energy=80))  # effective face -> idle_hungry
    now = time.time()
    card._schedule_emote(now)                             # first call arms the timer
    card._schedule_emote(now + qt_card.EMOTE_MAX_GAP_S + 0.1)   # past the gap -> emit
    assert card._particles.alive("food", now + qt_card.EMOTE_MAX_GAP_S + 0.1)
    card.close()


def test_no_mood_emote_when_content(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    now = time.time()
    card._schedule_emote(now)
    card._schedule_emote(now + qt_card.EMOTE_MAX_GAP_S + 0.1)
    assert not card._particles.alive("food", now + 10)   # a content pet emits nothing
    assert not card._particles.alive("zzz", now + 10)
    card.close()


# --- popups: the speech bubble + hover tooltip (#58) -------------------------
def test_bubble_places_above_the_card_via_the_pure_core(app):
    bubble = qt_popups.QtBubble("resets at 3pm")
    bounds = (0, 0, 1920, 1080)
    bubble.place_above(500, 500, 158, bounds)
    expect = qt_popups.popup_place.above(500, 500, 158, bubble.width(), bubble.height(),
                                         bounds, qt_popups.BUBBLE_GAP)
    assert (bubble.x(), bubble.y()) == expect
    bubble.close()


def test_tooltip_shows_name_level_and_coins(app):
    tip = qt_popups.QtStatsTooltip(_pet(name="Rex", coins=42, xp=250))
    assert "Rex" in tip._name.text()
    assert "Lv 3" in tip._sub.text() and "42 coins" in tip._sub.text()   # 250 xp -> lv 3
    tip.close()


def test_notify_shows_a_bubble_and_clearing_it_removes_it(app):
    st = _state("s", "waiting")
    st["notify"] = {"message": "needs you!", "type": "question"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    assert card._bubble is not None and "needs you!" in card._bubble._message
    card.set_state(_state("s", "idle"))          # the notify cleared
    assert card._bubble is None
    card.close()


def test_hover_shows_the_pet_tooltip_and_leave_dismisses_it(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    card.set_pet(_pet(name="Pixel"))
    card.enterEvent(None)
    assert card._tooltip is not None and "Pixel" in card._tooltip._name.text()
    card.leaveEvent(None)
    assert card._tooltip is None
    card.close()


def test_no_tooltip_in_simple_mode(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=False)
    card.enterEvent(None)
    assert card._tooltip is None                 # a read-only indicator shows no status
    card.close()


def test_closing_the_card_cleans_up_its_bubble(app):
    st = _state("s", "waiting")
    st["notify"] = {"message": "x"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    assert card._bubble is not None
    card.close()
    assert card._bubble is None


# --- glow-up: crossfade, sub-pixel motion, evolution scale-up (#59) ----------
def test_a_face_change_crossfades_then_settles(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    card.set_state(_state("s", "idle"))          # working -> happy: a real face change
    assert card._prev_pixmap is not None         # the outgoing face is crossfading
    card._render(time.time() + qt_card.CROSSFADE_S + 0.1)
    assert card._prev_pixmap is None             # fade complete, settled
    card.close()


def test_the_bob_moves_sub_pixel(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    card._render(card._anim_t0 + qt_card.BOB_PERIOD_S * 0.13)   # a fractional phase
    bob = card._panel._bob
    assert isinstance(bob, float) and bob != round(bob)        # sub-pixel offset
    card.close()


def test_an_evolution_scales_the_creature_up(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    card.set_pet(_pet(xp=1000, born=time.time() - 4 * 86400))   # baby -> adult: a stage change
    now = time.time()
    assert card._scale_now(now) < 1.0                          # scaling up
    assert card._scale_now(now + qt_card.STAGE_SCALE_S + 0.1) == 1.0   # settled at full size
    card.close()


# --- QtCard: the pushed pet look (mood tint + stage/hat) ---------------------
# The manager only pushes a pet to a pet-enabled card, so these construct with
# pet_enabled=True (a simple-mode card ignores the push and shows the fixed stage).
def test_card_tints_the_idle_face_by_pet_mood(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer(), pet_enabled=True)
    card.set_pet(_pet(hunger=10, happiness=80, energy=80))   # most-depleted -> hungry
    assert card._face == "idle_hungry"      # a hungry mood droops the idle face
    card.close()


def test_card_dresses_the_sprite_in_the_pushed_stage_hat_and_flourish(app):
    rec = _RecordingRenderer()
    card = qt_card.QtCard("s", _state("s", "idle"), 0, rec, pet_enabled=True)
    now = time.time()
    # level 11 (xp 1000) + 4 days old -> adult stage + milestone flourish; crown worn.
    card.set_pet(_pet(xp=1000, born=now - 4 * 86400, equipped={"head": "crown"}))
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
    assert mgr.cards["s1"]._pet_data is not None   # the global pet was pushed


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
    monkeypatch.setattr(qt_card.qt_screens, "work_areas", lambda: [(1000, 0, 800, 600)])
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


# --- QtCard: effort-reactive panel + usage bars (main's effort/usage feature, ported) ---
def _usage_snapshot(five=76.0, week=93.0, *, future=True):
    """A usage snapshot with both windows; resets far in the future so neither
    window decays to 0 during the test (or already past, to test reset decay)."""
    reset = time.time() + 10_000 if future else time.time() - 1
    return {"five_hour": {"used_percentage": five, "resets_at": reset},
            "seven_day": {"used_percentage": week, "resets_at": reset}}


def test_card_draws_usage_bars_from_the_snapshot(app):
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    card.set_usage(_usage_snapshot(76.0, 93.0))
    bars = card._panel._bars
    assert [(label, round(pct)) for label, pct, _ in bars] == [("5h", 76), ("7d", 93)]
    # traffic-light colors: 76% -> warning amber, 93% -> alarm red.
    assert bars[0][2] == qt_card._hex(usage.WARN)
    assert bars[1][2] == qt_card._hex(usage.ALARM)
    card.close()


def test_card_without_usage_draws_no_bars(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    assert card._panel._bars == ()               # nothing pushed -> an empty row
    card.close()


def test_usage_window_past_its_reset_reads_zero(app):
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    card.set_usage(_usage_snapshot(80.0, 90.0, future=False))   # both already reset
    assert [round(pct) for _, pct, _ in card._panel._bars] == [0, 0]
    card.close()


def test_context_ring_absent_until_data_then_traffic_lit(app):
    # The ring gauge (#73): nothing before the first tailer result; then a
    # top-right arc colored by the usage thresholds (calm / amber / red).
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    assert card._panel._ring is None                  # no data -> no ring at all

    card.set_context(50.0)
    assert card._panel._ring == (50.0, qt_card._hex(usage.CALM))
    card.set_context(76.0)
    assert card._panel._ring == (76.0, qt_card._hex(usage.WARN))
    card.set_context(93.0)
    assert card._panel._ring == (93.0, qt_card._hex(usage.ALARM))

    card.set_context(None)                            # session's % unknown again
    assert card._panel._ring is None
    card.close()


def test_context_ring_shows_frozen_on_a_gravestone_and_paints(app):
    card = qt_card.QtCard("s", _state("s", "dead"), 0, QtPixmapRenderer())
    card.set_context(64.0)
    assert card._panel._ring is not None              # frozen at last value, not hidden
    card._panel.repaint()                             # smoke: the arc math paints clean
    card.close()


def test_stale_usage_flags_the_panel_and_fresh_clears_it(app):
    # The stale label (#69): an aged snapshot dims the bars + shows "stale"; a
    # fresh one shows plain bars. The flag rides the repaint-guard frame.
    card = qt_card.QtCard("s", _state("s", "idle"), 0, QtPixmapRenderer())
    card.set_usage({**_usage_snapshot(50.0, 60.0), "ts": time.time()})
    assert card._panel._stale is False
    card.set_usage({**_usage_snapshot(50.0, 60.0),
                    "ts": time.time() - usage.STALE_AFTER_S - 5})
    assert card._panel._stale is True
    card.close()


def test_effort_tints_the_panel(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    st = {**_state("s", "working"), "effort": "high"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    expected = qt_card._hex(effort.panel_fill("high", qt_card._PANEL_FILL_RGB, 0.0))
    assert card._panel._panel_fill == expected
    assert card._panel._panel_fill != qt_card.PANEL_FILL     # actually tinted
    card.close()


def test_no_effort_keeps_the_default_panel(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    card = qt_card.QtCard("s", _state("s", "working"), 0, QtPixmapRenderer())
    assert card._panel._panel_fill == qt_card.PANEL_FILL     # unknown effort -> default
    card.close()


def test_max_effort_paints_a_pixelated_rainbow_that_flows(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    st = {**_state("s", "working"), "effort": "max"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    kind, first_t = card._panel._panel_bg
    assert kind == "rainbow"                                 # a tiled rainbow wash, not a solid
    card._render(card._anim_t0 + effort.RAINBOW_PERIOD_S / 3)
    assert card._panel._panel_bg[1] != first_t               # the wash scrolled (t advanced)
    card.close()


def test_xhigh_effort_radiates_a_ripple(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    st = {**_state("s", "working"), "effort": "xhigh"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    assert card._panel._panel_bg[0] == "ripple"              # purple rings from the mascot
    assert card._panel._panel_fill == qt_card.PANEL_FILL     # rings ride over the dark base
    card.close()


def test_quiet_levels_use_a_solid_background(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    for level in ("low", "medium", "high"):
        card = qt_card.QtCard("s", {**_state("s", "working"), "effort": level}, 0,
                              QtPixmapRenderer())
        assert card._panel._panel_bg == ("solid",)           # a flat tint, no pixel field
        card.close()


def test_dead_suppresses_the_effort_tint(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    st = {**_state("s", "dead"), "effort": "max"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    assert card._panel._panel_fill == qt_card.PANEL_FILL     # a finished session stays sombre
    card.close()


def test_resolve_effort_prefers_state_over_settings(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "low")
    st = {**_state("s", "working"), "effort": "max"}
    card = qt_card.QtCard("s", st, 0, QtPixmapRenderer())
    assert card._effort_display == "max"          # the per-turn state level wins the fallback
    card.close()


def test_animated_effort_accents_the_border_but_waiting_keeps_default(app, monkeypatch):
    monkeypatch.setattr(qt_card.effort, "settings_effort", lambda *a, **k: "")
    working = qt_card.QtCard("s", {**_state("s", "working"), "effort": "xhigh"}, 0,
                             QtPixmapRenderer())
    assert working._panel._border != qt_card.PANEL_EDGE      # xhigh accents the border
    working.close()
    # A waiting card keeps the default edge — the attention state wins over the accent.
    waiting = qt_card.QtCard("s", {**_state("s", "waiting"), "effort": "xhigh"}, 0,
                             QtPixmapRenderer())
    assert waiting._panel._border == qt_card.PANEL_EDGE
    waiting.close()


def test_app_pushes_usage_to_every_card_each_poll(app, tmp_path, monkeypatch):
    snap = {"five_hour": {"used_percentage": 55.0, "resets_at": time.time() + 9999}}
    monkeypatch.setattr(qt_app.usage, "load_usage", lambda *a, **k: snap)
    mgr = qt_app.QtMascotApp(tmp_path, service=_svc(tmp_path))
    mgr._on_sessions({"s1": _state("s1", "working")})
    card = mgr.cards["s1"]
    assert card._usage == snap                                    # pushed to the card
    assert [label for label, *_ in card._panel._bars] == ["5h"]   # rendered as one bar
    mgr._on_sessions({})                                          # tidy up the card
