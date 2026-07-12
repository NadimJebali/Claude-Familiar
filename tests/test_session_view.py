"""Tests for the session presenter — the one place that decides what a session
shows (issue #101).

The presenter owns the effective-state ladder (the overlay is its implementation
detail) and composes, in order, the pending-tool promotion, the usage-death
override, the raw clocks, the ladder, the display face, and the caption. Both
themes render their state text from the resulting ``SessionView``; the Classic
card reads ``view.caption`` and the Compact row builds ``status_line(view)``.

Pure and clock-injected: every case here runs with synthetic state dicts and an
explicit ``now`` — no QApplication, no widget. This is the seam the old
qt_compact ``row_text`` unit tests migrated onto.
"""
from __future__ import annotations

from mascot import config, effort, presenter, usage
from mascot.overlay import OverlayConfig

_hex = presenter._hex

# A known threshold set so the time-based ladder is deterministic regardless of
# the machine's settings.json (mirrors the effective_state suite's explicit args).
_CFG = OverlayConfig(
    dizzy_duration_s=2.0,
    celebrate_duration_s=1.5,
    blink_duration_s=0.12,
    sleep_after_idle_s=90.0,
    shake_after_s=30.0,
    permission_wait_s=45.0,
    thinking_stall_s=180.0,
    working_stall_s=270.0,
)

T0 = 1_000_000.0


def _state(st="idle", **over):
    base = {"session_id": "s", "state": st, "ts": T0,
            "subagents": [], "schema_version": 1}
    base.update(over)
    return base


def _present(st="idle", *, now=T0, celebrates=True, **over):
    """A presenter that has adopted one state at ``now`` (the common setup)."""
    p = presenter.SessionPresenter(_CFG, raw=st, now=now, celebrates=celebrates)
    p.adopt_state(_state(st, **over), now)
    return p


# --- caption: the canonical short word per face (what the Classic card shows) --
def test_caption_names_the_state():
    assert _present("idle").view(T0).caption == "idle"
    assert _present("thinking").view(T0).caption == "thinking…"
    assert _present("working").view(T0).caption == "working…"
    assert _present("compacting").view(T0).caption == "tidying memories…"
    assert _present("waiting").view(T0).caption == "needs you!"
    assert _present("dead").view(T0).caption == "out of usage"


def test_caption_for_working_is_stable_across_tools():
    # The per-tool face changes; the caption does not (the tool shows on the
    # dim info line / the compact status, not the caption).
    for tool in ("Read", "Edit", "Bash", "WebFetch"):
        assert _present("working", tool=tool).view(T0).caption == "working…"


def test_caption_is_planning_while_busy_in_plan_mode():
    assert _present("thinking", permission_mode="plan").view(T0).caption == "planning…"
    assert _present(
        "working", tool="Read", permission_mode="plan").view(T0).caption == "planning…"


# --- the display face -----------------------------------------------------------
def test_face_varies_working_by_tool():
    assert _present("working", tool="Read").view(T0).face == "working_read"
    assert _present("working", tool="Edit").view(T0).face == "working_edit"
    assert _present("working", tool="Bash").view(T0).face == "working_run"
    assert _present("working", tool=None).view(T0).face == "working"


def test_face_shows_stumble_over_the_idle_family():
    p = _present("idle", stumbled=True)
    assert p.view(T0).face == "stumble"
    # Past the stumble window it settles to the idle family again.
    assert p.view(T0 + presenter.STUMBLE_FACE_S + 1).face == "idle"


def test_idle_face_reflects_the_pet_mood():
    assert _present("idle").view(T0, mood="hungry").face == "idle_hungry"
    assert _present("idle").view(T0, mood="happy").face == "idle_happy"
    assert _present("idle").view(T0, mood="hungry").caption == "idle"   # caption unchanged


# --- composition order: the usage-death override outranks everything ------------
def test_usage_exhaustion_tombstones_and_carries_the_reset():
    reset = T0 + 3600
    p = _present("working", tool="Edit")
    p.adopt_usage({"ts": T0, "five_hour": {"used_percentage": 100.0,
                                            "resets_at": reset}})
    view = p.view(T0)
    assert view.is_dead is True
    assert view.draw_raw == "dead"
    assert view.reset_at == reset
    assert view.caption == "out of usage"


def test_a_passed_reset_auto_revives():
    p = _present("working")
    p.adopt_usage({"ts": T0, "five_hour": {"used_percentage": 100.0,
                                           "resets_at": T0 - 60}})
    view = p.view(T0)
    assert view.is_dead is False
    assert view.draw_raw == "working"


def test_hook_death_tombstones_without_a_reset_time():
    # A StopFailure-driven "dead" with no usage exhaustion: dead, but no reset.
    view = _present("dead").view(T0)
    assert view.is_dead is True
    assert view.reset_at is None
    assert view.caption == "out of usage"


# --- composition order: the pending-permission promotion ------------------------
def test_a_long_pending_tool_promotes_to_waiting():
    p = _present("working", tool="Bash", ts=T0 - _CFG.permission_wait_s - 5)
    view = p.view(T0)
    assert view.draw_raw == "waiting"
    assert view.face == "waiting"
    assert view.caption == "needs you!"


def test_a_fresh_tool_is_left_working():
    view = _present("working", tool="Bash", ts=T0).view(T0)
    assert view.draw_raw == "working"
    assert view.face == "working_run"


# --- composition order: the stall watchdog (the shipped Compact drift fix) ------
def test_a_wedged_working_turn_falls_back_to_idle():
    # A busy turn with no closing hook, gone stale past the working grace, must
    # read idle — not "working…" forever. Both themes inherit this now.
    p = _present("working", ts=T0)
    view = p.view(T0 + _CFG.working_stall_s + 1)
    assert view.effective == "idle"
    assert view.caption == "idle"


def test_a_wedged_thinking_turn_falls_back_to_idle():
    # thinking gets the shorter grace; past it, the same idle fallback.
    p = _present("thinking", ts=T0)
    assert p.view(T0 + _CFG.thinking_stall_s + 1).caption == "idle"


def test_a_wedged_compacting_turn_falls_back_to_idle():
    # compaction may emit no closing hook of its own, so it takes the thinking
    # grace and falls to idle the same way (rather than freezing on "tidying…").
    p = _present("compacting", ts=T0)
    assert p.view(T0 + _CFG.thinking_stall_s + 1).caption == "idle"


def test_a_long_idle_session_sleeps():
    p = _present("idle", now=T0)
    view = p.view(T0 + _CFG.sleep_after_idle_s + 1)
    assert view.effective == "sleeping"
    assert view.caption == "sleeping…"


# --- gestures: celebrate / dizzy / blink flow through the presenter -------------
def test_finishing_a_turn_celebrates_when_enabled():
    p = presenter.SessionPresenter(_CFG, raw="working", now=T0, celebrates=True)
    p.adopt_state(_state("idle"), T0)
    assert p.view(T0).effective == "happy"


def test_finishing_a_turn_does_not_celebrate_when_disabled():
    # The Compact rows construct with celebrates=False, so they stay still.
    p = presenter.SessionPresenter(_CFG, raw="working", now=T0, celebrates=False)
    p.adopt_state(_state("idle"), T0)
    assert p.view(T0).effective != "happy"


def test_note_dizzy_shows_the_dizzy_face_until_it_expires():
    p = _present("idle")
    p.note_dizzy(T0)
    assert p.is_dizzy(T0) is True
    assert p.view(T0).effective == "dizzy"
    assert p.view(T0 + _CFG.dizzy_duration_s + 0.1).effective != "dizzy"


def test_note_blink_shows_a_blink_while_idle():
    p = _present("idle")
    p.note_blink(T0)
    assert p.view(T0).face == "idle_blink"


def test_waiting_elapsed_tracks_the_attention_clock():
    p = _present("idle")
    assert p.waiting_elapsed(T0) is None
    p.adopt_state(_state("waiting"), T0)
    p.view(T0)                                   # note_raw starts the waiting clock
    assert p.waiting_elapsed(T0 + 5) == 5


# --- visual identity: accent, dot color, idle dimming (#102) --------------------
def test_accent_is_the_face_state_color():
    # The Classic sprite tint is the displayed face's accent — per-tool working
    # faces share the working green; plan mode is the scholarly teal.
    assert _present("working", tool="Edit").view(T0).accent == \
        _hex(config.STATE_COLORS["working_edit"])
    assert _present("idle").view(T0).accent == _hex(config.STATE_COLORS["idle"])
    assert _present("thinking", permission_mode="plan").view(T0).accent == \
        _hex(config.STATE_COLORS["planning"])


def test_effort_never_touches_the_sprite_accent():
    # Effort colors the Compact dot, never the creature — the face owns the accent.
    assert _present("working").view(T0, effort_fallback="max").accent == \
        _hex(config.STATE_COLORS["working"])


def test_dot_color_precedence_attention_then_effort_then_state():
    # Waiting / tombstoned accents win.
    assert _present("waiting").view(T0).dot_color == _hex(config.STATE_COLORS["waiting"])
    assert _present("dead").view(T0).dot_color == _hex(config.STATE_COLORS["dead"])
    # A pending-promoted tool wears the waiting accent too.
    pending = _present("working", tool="Bash", ts=T0 - _CFG.permission_wait_s - 5)
    assert pending.view(T0).dot_color == _hex(config.STATE_COLORS["waiting"])
    # Then the effort tint; without an effort, the state accent.
    assert _present("working").view(T0, effort_fallback="high").dot_color == \
        _hex(effort.TINTS["high"])
    assert _present("working").view(T0, effort_fallback="").dot_color == \
        _hex(config.STATE_COLORS["working"])
    # An unrecognized raw state reads as idle grey (a newer writer can't break it).
    assert _present("frobnicate").view(T0).dot_color == \
        _hex(config.STATE_COLORS["idle"])


def test_effort_is_resolved_from_the_session_over_the_fallback():
    # view() does the resolve pairing now: the session's own per-turn effort wins,
    # the account-wide fallback fills in when the session carries none.
    assert _present("working", effort="max").view(
        T0, effort_fallback="low").chrome_level == "max"
    assert _present("working").view(T0, effort_fallback="low").chrome_level == "low"


def test_dim_only_when_effectively_idle():
    assert _present("idle").view(T0).dim is True
    for st in ("working", "thinking", "waiting", "compacting"):
        assert _present(st).view(T0).dim is False
    # The tombstone must never whisper.
    assert _present("dead").view(T0).dim is False
    # A long-idle (dozing) session still dims.
    p = _present("idle", now=T0)
    assert p.view(T0 + _CFG.sleep_after_idle_s + 1).dim is True


# --- effort chrome (#103) -------------------------------------------------------
def test_chrome_level_is_the_resolved_effort_but_uncontested():
    assert _present("working").view(T0, effort_fallback="high").chrome_level == "high"
    # Waiting and tombstoned sessions stay uncontested — no effort decoration.
    assert _present("waiting").view(T0, effort_fallback="max").chrome_level == ""
    assert _present("dead").view(T0, effort_fallback="max").chrome_level == ""


def test_effort_fill_is_the_quiet_tint_only():
    for level in ("low", "medium", "high"):
        v = _present("working").view(T0, effort_fallback=level)
        assert v.effort_fill == _hex(
            effort.panel_fill(level, presenter._PANEL_FILL_RGB, 0.0))
    # Animated levels paint their own background, so they carry no flat tint.
    assert _present("working").view(T0, effort_fallback="max").effort_fill is None
    assert _present("working").view(T0, effort_fallback="xhigh").effort_fill is None
    # No effort, or a contested (waiting) session -> no tint.
    assert _present("working").view(T0, effort_fallback="").effort_fill is None
    assert _present("waiting").view(T0, effort_fallback="high").effort_fill is None


def test_effort_bg_kind_marks_the_animated_levels_uncontested():
    assert _present("working").view(T0, effort_fallback="max").effort_bg_kind == "rainbow"
    assert _present("working").view(T0, effort_fallback="xhigh").effort_bg_kind == "ripple"
    assert _present("working").view(T0, effort_fallback="high").effort_bg_kind == "solid"
    assert _present("waiting").view(T0, effort_fallback="max").effort_bg_kind == "solid"
    assert _present("dead").view(T0, effort_fallback="max").effort_bg_kind == "solid"


def test_bg_marker_carries_the_clock_only_when_animated():
    # A solid marker drops the clock so the repaint guard stays stable frame to
    # frame; the animated markers carry the (rounded) clock for the pixel phase.
    assert presenter.bg_marker("rainbow", 1.2345) == ("rainbow", 1.234)
    assert presenter.bg_marker("ripple", 2.0) == ("ripple", 2.0)
    assert presenter.bg_marker("solid", 9.9) == ("solid",)


# --- usage bars, staleness, context ring (#104) ---------------------------------
def test_usage_bars_derives_label_percent_and_traffic_light_color():
    # The one bars derivation both themes share (a card per-card, compact once).
    now = T0
    snap = {"ts": now, "five_hour": {"used_percentage": 76.0, "resets_at": now + 999},
            "seven_day": {"used_percentage": 93.0, "resets_at": now + 999}}
    bars = presenter.usage_bars(snap, now)
    assert bars == (("5h", 76.0, _hex(usage.bar_color(76.0))),
                    ("7d", 93.0, _hex(usage.bar_color(93.0))))
    assert presenter.usage_bars(None, now) == ()   # no snapshot -> no bars


def test_view_carries_the_bars_and_staleness():
    now = T0
    p = _present("working")
    p.adopt_usage({"ts": now, "five_hour": {"used_percentage": 40.0,
                                            "resets_at": now + 999}})
    view = p.view(now)
    assert view.bars == (("5h", 40.0, _hex(usage.bar_color(40.0))),)
    assert view.usage_stale is False
    # An aged snapshot reads stale.
    p.adopt_usage({"ts": now - 3600, "five_hour": {"used_percentage": 40.0,
                                                   "resets_at": now + 999}})
    assert p.view(now).usage_stale is True


def test_view_ring_is_the_per_session_context_gauge():
    p = _present("working")
    assert p.view(T0).ring is None            # absent until the first tailer result
    p.adopt_context(64.0)
    assert p.view(T0).ring == (64.0, _hex(usage.bar_color(64.0)))
    p.adopt_context(None)
    assert p.view(T0).ring is None


# --- info facts: model tag, dim info line, sub-agent count (#105) ---------------
def test_model_label_strips_prefix_and_date():
    assert presenter.model_label("claude-opus-4-8") == "opus-4-8"
    assert presenter.model_label("claude-haiku-4-5-20251001") == "haiku-4-5"
    assert presenter.model_label("") == ""
    assert presenter.model_label("weird") == "weird"


def test_view_model_tag_is_the_short_label():
    assert _present("working", model="claude-fable-5").view(T0).model_tag == "fable-5"


def test_info_line_joins_file_basename_and_model_tag():
    assert presenter.info_line(r"C:\repo\mascot\qt_app.py",
                               "claude-fable-5") == "qt_app.py · fable-5"
    assert presenter.info_line("", "claude-opus-4-8") == "opus-4-8"   # idle: model alone
    assert presenter.info_line("hooks/emit.py", None) == "emit.py"
    assert presenter.info_line(None, None) == ""


def test_view_info_is_file_model_or_the_reset_time():
    assert _present("working", file=r"C:\x\a.py",
                    model="claude-fable-5").view(T0).info == "a.py · fable-5"
    assert _present("idle", model="claude-opus-4-8").view(T0).info == "opus-4-8"
    # A tombstoned session's reset time replaces the file · model line.
    p = _present("working", file="C:/x/a.py", model="claude-fable-5")
    p.adopt_usage({"ts": T0, "five_hour": {"used_percentage": 100.0,
                                           "resets_at": T0 + 3600}})
    assert p.view(T0).info.startswith("resets ")


def test_subagent_count_is_the_raw_live_count():
    subs = [{"id": "a", "type": "t", "description": ""},
            {"id": "b", "type": "t", "description": ""}]
    assert _present("working", subagents=subs).view(T0).subagent_count == 2
    assert _present("working").view(T0).subagent_count == 0


# --- interaction gates + mood emotes (#106) -------------------------------------
def test_can_pet_gates_on_state_and_dizzy():
    assert _present("idle").can_pet(T0) is True
    assert _present("working").can_pet(T0) is True
    # Don't cheer over a "needs you" or a gravestone.
    assert _present("waiting").can_pet(T0) is False
    assert _present("dead").can_pet(T0) is False
    # A pending-promoted (waiting) session blocks petting too.
    pending = _present("working", tool="Bash", ts=T0 - _CFG.permission_wait_s - 5)
    assert pending.can_pet(T0) is False
    # Dizzy blocks it until it wears off.
    p = _present("idle")
    p.note_dizzy(T0)
    assert p.can_pet(T0) is False
    assert p.can_pet(T0 + _CFG.dizzy_duration_s + 0.1) is True


def test_emote_for_maps_moods_to_emotes():
    assert presenter.emote_for("idle_hungry") == "food"
    assert presenter.emote_for("idle_tired") == "zzz"
    assert presenter.emote_for("sleeping") == "zzz"
    assert presenter.emote_for("idle") is None
    assert presenter.emote_for("working") is None


# --- status_line: the Compact row's rich text (composed from the view) ----------
def _status(st="idle", *, now=T0, chars=34, mood="content", **over):
    return presenter.status_line(_present(st, now=now, **over).view(now, mood=mood),
                                 notify_max_chars=chars)


def test_status_line_names_the_state_and_tool():
    assert _status("working", tool="Edit") == "working · Edit"
    assert _status("working", tool=None) == "working…"
    assert _status("thinking") == "thinking…"
    assert _status("thinking", permission_mode="plan") == "planning…"
    assert _status("compacting") == "tidying memories…"
    assert _status("idle") == "idle"


def test_status_line_carries_the_working_file():
    assert _status("working", tool="Edit",
                   file=r"C:\repo\mascot\qt_app.py") == "working · Edit · qt_app.py"
    assert _status("working", tool=None,
                   file=r"C:\repo\mascot\qt_app.py") == "working · qt_app.py"


def test_status_line_waiting_carries_the_notify_inline_truncated():
    text = _status("waiting", notify={"message": "Allow this Bash command?" * 3,
                                       "type": "permission"})
    assert text.startswith("needs you! · Allow this Bash command")
    assert len(text) <= len("needs you! · ") + 34 + 1     # +ellipsis


def test_status_line_out_of_usage_with_and_without_a_reset():
    p = _present("working")
    p.adopt_usage({"ts": T0, "five_hour": {"used_percentage": 100.0,
                                           "resets_at": T0 + 3600}})
    assert presenter.status_line(p.view(T0), notify_max_chars=34).startswith(
        "out of usage · resets ")
    assert _status("dead") == "out of usage"     # hook death, no reset


def test_status_line_promotes_a_long_pending_tool():
    assert _status("working", tool="Bash",
                   ts=T0 - _CFG.permission_wait_s - 5) == "needs you!"
