"""Phase 1 tests: pure state logic + emit file I/O.

Payloads mirror the real Phase 0 captures (docs/PLAN.md).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import emit
from state_logic import compute_next_state, default_state

from mascot import (
    effective_state,
    popup_place,
)

SID = "4a6ff882-6153-4b83-bd9a-1017fdd10aee"


def base():
    return default_state(SID, cwd="C:\\Users\\Vinny", model="claude-opus-4-8")


# --- state_logic ----------------------------------------------------------

def test_default_state_is_idle_with_no_subagents():
    s = default_state(SID)
    assert s["state"] == "idle"
    assert s["subagents"] == []


def test_user_prompt_submit_sets_thinking():
    out = compute_next_state(base(), "UserPromptSubmit", {"session_id": SID})
    assert out["state"] == "thinking"


def test_regular_tool_sets_working_and_records_tool():
    payload = {"session_id": SID, "tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["state"] == "working"
    assert out["tool"] == "Bash"


def test_agent_spawn_pushes_subagent_keyed_by_tool_use_id():
    payload = {
        "session_id": SID,
        "tool_name": "Agent",
        "tool_input": {"description": "Test agent", "subagent_type": "code-reviewer"},
        "tool_use_id": "toolu_ABC",
    }
    out = compute_next_state(base(), "PreToolUse", payload)
    assert len(out["subagents"]) == 1
    assert out["subagents"][0] == {
        "id": "toolu_ABC",
        "type": "code-reviewer",
        "description": "Test agent",
    }


def test_nested_tool_inside_agent_does_not_push_subagent():
    # A tool running INSIDE a sub-agent carries a top-level agent_id.
    payload = {
        "session_id": SID,
        "tool_name": "Read",
        "agent_id": "a5140c7be1c5f0f1f",
        "agent_type": "general-purpose",
        "tool_input": {"file_path": "x"},
    }
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["subagents"] == []
    assert out["state"] == "working"


def test_post_tool_use_agent_pops_matching_subagent():
    start = base()
    start["subagents"] = [{"id": "toolu_ABC", "type": "agent", "description": ""}]
    payload = {"session_id": SID, "tool_name": "Agent", "tool_use_id": "toolu_ABC"}
    out = compute_next_state(start, "PostToolUse", payload)
    assert out["subagents"] == []


def test_idle_prompt_notification_type_stays_idle():
    # Claude Code's ~60s idle nudge can arrive as type "idle_prompt" with no
    # message; it must NOT wake the mascot into the shaking "waiting" state — only
    # a real attention/permission prompt should. (Regression: empty-message idle
    # nudges used to fall through to "waiting" and leave the mascot stuck.)
    payload = {"session_id": SID, "notification_type": "idle_prompt"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "idle"
    assert out["notify"] is None


def test_permission_notification_type_sets_waiting():
    # A real attention prompt (typed, non-idle) still raises "waiting".
    payload = {"session_id": SID, "message": "Approve edit?", "notification_type": "permission"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "waiting"
    assert out["notify"]["message"] == "Approve edit?"


def test_notification_captures_permission_message():
    payload = {
        "session_id": SID,
        "message": "Claude needs your permission to use Bash",
        "notification_type": "permission",
    }
    out = compute_next_state(base(), "Notification", payload)
    assert out["notify"] == {
        "message": "Claude needs your permission to use Bash",
        "type": "permission",
    }


def test_idle_reminder_notification_does_not_wake_to_waiting():
    # Claude Code's ~60s "waiting for your input" nudge must not flip a dozing
    # mascot into the attention-grabbing waiting state.
    payload = {"session_id": SID, "message": "Claude is waiting for your input"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "idle"
    assert out["notify"] is None


def test_permission_notification_still_waits():
    payload = {"session_id": SID, "message": "Claude needs your permission to use Bash"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "waiting"
    assert out["notify"]["message"] == "Claude needs your permission to use Bash"


def test_usage_limit_notification_goes_dead_and_keeps_bubble():
    payload = {
        "session_id": SID,
        "message": "Claude usage limit reached",
        "notification_type": "usage_limit",
    }
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "dead"
    assert out["notify"] == {
        "message": "Claude usage limit reached",
        "type": "usage_limit",
    }


def test_usage_limit_reset_message_goes_dead_and_keeps_bubble():
    payload = {"session_id": SID, "message": "Your limit will reset at 3pm"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "dead"
    assert out["notify"]["message"] == "Your limit will reset at 3pm"


def test_session_limit_notification_goes_dead():
    # "You have hit your session limit" ends the session just like a usage limit.
    payload = {
        "session_id": SID,
        "message": "You have hit your session limit",
        "notification_type": "usage_limit",
    }
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "dead"
    assert out["notify"]["message"] == "You have hit your session limit"


def test_usage_limit_revives_on_next_prompt():
    dead = compute_next_state(
        base(), "Notification", {"session_id": SID, "message": "Claude usage limit reached"}
    )
    assert dead["state"] == "dead"
    # Once usage resets and the user submits again, the gravestone comes back to life.
    revived = compute_next_state(dead, "UserPromptSubmit", {"session_id": SID})
    assert revived["state"] == "thinking"


def test_transient_rate_limit_does_not_go_dead():
    # A recoverable 429 backoff is an attention notification, not session death.
    payload = {"session_id": SID, "message": "API rate limit hit, retrying"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "waiting"
    assert out["state"] != "dead"


def test_stop_with_session_limit_text_tombstones():
    # Real-world: "You've hit your session limit · resets 8:50pm". If the limit
    # text rides on a Stop event, the mascot must die — not go calmly idle.
    payload = {"session_id": SID, "message": "You've hit your session limit · resets 8:50pm"}
    out = compute_next_state(base(), "Stop", payload)
    assert out["state"] == "dead"
    assert "session limit" in out["notify"]["message"].lower()


def test_usage_limit_detected_in_non_message_field():
    # The limit text may land on `reason` rather than `message`; still detect it.
    payload = {"session_id": SID, "reason": "You have reached your usage limit"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "dead"


# --- StopFailure (API-error turn death) -----------------------------------

def test_stopfailure_rate_limit_goes_dead_with_bubble():
    # The structured terminating hook: a usage/rate limit ends the turn with
    # error_type "rate_limit" -> the mascot tombstones and shows a bubble.
    payload = {"session_id": SID, "error_type": "rate_limit"}
    out = compute_next_state(base(), "StopFailure", payload)
    assert out["state"] == "dead"
    assert out["notify"] is not None


def test_stopfailure_overloaded_goes_idle_not_dead():
    # A transient server overload ends the turn (-> idle) but is NOT session death.
    start = base()
    start["state"] = "working"
    payload = {"session_id": SID, "error_type": "overloaded"}
    out = compute_next_state(start, "StopFailure", payload)
    assert out["state"] == "idle"


def test_stopfailure_session_blocking_errors_go_dead():
    # Auth/billing/org-block failures also stop the session cold -> gravestone.
    for et in ("billing_error", "authentication_failed", "oauth_org_not_allowed"):
        out = compute_next_state(base(), "StopFailure", {"session_id": SID, "error_type": et})
        assert out["state"] == "dead", et


def test_stopfailure_other_transient_errors_go_idle():
    # The remaining non-death error_types settle to idle (the turn ended), never dead.
    for et in ("server_error", "model_not_found", "invalid_request",
               "max_output_tokens", "unknown"):
        start = base()
        start["state"] = "working"
        out = compute_next_state(start, "StopFailure", {"session_id": SID, "error_type": et})
        assert out["state"] == "idle", et


def test_stopfailure_missing_error_type_goes_idle():
    # A StopFailure with no error_type must not crash or tombstone — settle to idle.
    start = base()
    start["state"] = "thinking"
    out = compute_next_state(start, "StopFailure", {"session_id": SID})
    assert out["state"] == "idle"


def test_stopfailure_clears_tool_and_subagents():
    # The turn ended, so a StopFailure clears the active tool + sub-agent badges
    # (mirrors Stop) — no stale 'Bash…' caption or lingering badges on the card.
    start = base()
    start["state"] = "working"
    start["tool"] = "Bash"
    start["subagents"] = [{"id": "x", "type": "agent", "description": ""}]
    out = compute_next_state(start, "StopFailure", {"session_id": SID, "error_type": "overloaded"})
    assert out["tool"] is None
    assert out["subagents"] == []


def test_stopfailure_death_revives_on_next_prompt():
    # A StopFailure gravestone comes back to life on the next prompt; bubble cleared.
    dead = compute_next_state(
        base(), "StopFailure", {"session_id": SID, "error_type": "rate_limit"})
    assert dead["state"] == "dead"
    revived = compute_next_state(dead, "UserPromptSubmit", {"session_id": SID})
    assert revived["state"] == "thinking"
    assert revived["notify"] is None


def test_installer_includes_stopfailure_event():
    # The widget can't receive StopFailure unless the installer wires the hook.
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import install_hooks
    assert "StopFailure" in install_hooks.EVENTS


def test_notify_is_cleared_by_next_forward_event():
    waiting = compute_next_state(
        base(), "Notification",
        {"session_id": SID, "message": "Approve?", "notification_type": "permission"},
    )
    assert waiting["notify"] is not None
    # Submitting a prompt (or any forward event) dismisses the bubble.
    out = compute_next_state(waiting, "UserPromptSubmit", {"session_id": SID})
    assert out["notify"] is None


def test_subagent_stop_preserves_notify():
    waiting = compute_next_state(
        base(), "Notification",
        {"session_id": SID, "message": "Approve?", "notification_type": "permission"},
    )
    out = compute_next_state(waiting, "SubagentStop", {"session_id": SID})
    assert out["notify"] == waiting["notify"]


def test_stop_returns_idle_and_clears_subagents():
    start = base()
    start["subagents"] = [{"id": "x", "type": "agent", "description": ""}]
    out = compute_next_state(start, "Stop", {"session_id": SID})
    assert out["state"] == "idle"
    assert out["subagents"] == []


def test_transcript_path_is_stamped_from_the_payload():
    # #71: hook payloads carry the session's transcript JSONL path; recording it
    # lets the widget tail the transcript for the context gauge (no path-guessing).
    out = compute_next_state(
        base(), "UserPromptSubmit",
        {"session_id": SID, "transcript_path": "C:/t/sess.jsonl"})
    assert out["transcript_path"] == "C:/t/sess.jsonl"


def test_transcript_path_survives_a_payload_without_one():
    with_path = compute_next_state(
        base(), "UserPromptSubmit",
        {"session_id": SID, "transcript_path": "C:/t/sess.jsonl"})
    # A later event that omits the field (or carries it empty) must not erase it.
    out = compute_next_state(with_path, "PreToolUse",
                             {"session_id": SID, "tool_name": "Bash"})
    assert out["transcript_path"] == "C:/t/sess.jsonl"
    out = compute_next_state(out, "Stop", {"session_id": SID, "transcript_path": ""})
    assert out["transcript_path"] == "C:/t/sess.jsonl"


def test_default_state_documents_transcript_path():
    assert default_state(SID)["transcript_path"] == ""


def test_compute_next_state_does_not_mutate_input():
    start = base()
    start["subagents"] = [{"id": "x", "type": "agent", "description": ""}]
    snapshot = json.dumps(start, sort_keys=True)
    compute_next_state(start, "PreToolUse",
                       {"session_id": SID, "tool_name": "Agent",
                        "tool_input": {}, "tool_use_id": "y"})
    assert json.dumps(start, sort_keys=True) == snapshot


# --- emit (file I/O) ------------------------------------------------------

def test_update_state_writes_file_with_heartbeat(tmp_path):
    payload = {"session_id": SID, "cwd": "C:\\x", "tool_name": "Bash", "tool_input": {}}
    out = emit.update_state(tmp_path, "PreToolUse", payload, now=123.0)
    assert out["ts"] == 123.0
    written = json.loads((tmp_path / f"{SID}.json").read_text(encoding="utf-8"))
    assert written["state"] == "working"


def test_stopfailure_round_trips_to_dead_state_file(tmp_path):
    # End-to-end: a StopFailure(rate_limit) hits emit and lands a 'dead' state file.
    out = emit.update_state(
        tmp_path, "StopFailure", {"session_id": SID, "error_type": "rate_limit"}, now=5.0
    )
    assert out["state"] == "dead"
    written = json.loads((tmp_path / f"{SID}.json").read_text(encoding="utf-8"))
    assert written["state"] == "dead"


def test_session_end_deletes_file(tmp_path):
    emit.update_state(tmp_path, "SessionStart", {"session_id": SID}, now=1.0)
    assert (tmp_path / f"{SID}.json").exists()
    emit.update_state(tmp_path, "SessionEnd", {"session_id": SID}, now=2.0)
    assert not (tmp_path / f"{SID}.json").exists()


def test_missing_session_id_is_noop(tmp_path):
    assert emit.update_state(tmp_path, "Stop", {}, now=1.0) is None
    assert list(tmp_path.iterdir()) == []


# --- process detection / liveness (psutil) --------------------------------

def test_owner_name_matcher_accepts_claude_across_platforms():
    import proc as hooks_proc
    # "claude.exe" (Windows), "claude" (Linux comm) and "claude-code" all match,
    # case-insensitively; anything else does not.
    assert hooks_proc._is_owner_name("claude")
    assert hooks_proc._is_owner_name("claude.exe")
    assert hooks_proc._is_owner_name("Claude")
    assert hooks_proc._is_owner_name("claude-code")
    assert not hooks_proc._is_owner_name("bash")
    assert not hooks_proc._is_owner_name("")


def test_find_owner_pid_is_none_or_a_pid_and_never_crashes():
    # Best-effort: with no Claude ancestor (the test runner) it returns None; if one
    # exists it's a positive PID. Either way it must not raise.
    import proc as hooks_proc
    result = hooks_proc.find_owner_pid()
    assert result is None or (isinstance(result, int) and result > 0)


def test_pid_alive_true_for_self_and_safe_on_unknown():
    import os

    from mascot import proc as mascot_proc
    assert mascot_proc.pid_alive(os.getpid()) is True
    assert mascot_proc.pid_alive(None) is True          # unknown owner -> keep
    assert mascot_proc.pid_alive("not-an-int") is True  # unparseable -> keep


def test_live_owner_keeps_card_even_when_heartbeat_is_stale():
    # Sleep is energy recovery now, not death: a quiet-but-live session must keep
    # its card. A live, trackable owner PID overrides the staleness timeout.
    import os

    from mascot import state_store
    state = {"session_id": SID, "owner_pid": os.getpid(), "ts": 0.0}
    assert state_store.is_session_live(state, now=10_000.0, timeout=300.0) is True


def test_ownerless_session_falls_back_to_staleness_backstop():
    # With no trackable owner PID (unknown platform / lookup failed), an abandoned
    # file is still pruned once its heartbeat goes stale — the backstop survives.
    from mascot import state_store
    fresh = {"session_id": SID, "owner_pid": None, "ts": 9_900.0}
    stale = {"session_id": SID, "owner_pid": None, "ts": 0.0}
    assert state_store.is_session_live(fresh, now=10_000.0, timeout=300.0) is True
    assert state_store.is_session_live(stale, now=10_000.0, timeout=300.0) is False


def test_png_icon_has_valid_signature_and_chunks():
    from mascot import icon
    data = icon._png_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in data[:30] and data[-8:-4] == b"IEND"


# --- evolution: per-stage body composes the shared faces (#12) -------------

def test_grid_for_composes_a_valid_16x16_for_every_stage_and_face():
    from mascot import sprite_pixel as sp
    for stage in ("egg", "baby", "teen", "adult"):
        for face in sp._FACES:
            grid = sp.grid_for(stage, face)
            assert len(grid) == sp.GRID_H, (stage, face)
            assert all(len(row) == sp.GRID_W for row in grid), (stage, face)


def test_grid_for_egg_is_faceless_and_state_independent():
    from mascot import sprite_pixel as sp
    assert sp.grid_for("egg", "idle") == sp.grid_for("egg", "working")


def test_grid_for_reuses_the_shared_face_rows_at_each_stage():
    # Evolution reuses the per-state faces over a per-stage body: the middle 5 rows
    # are exactly the shared face for any non-egg stage.
    from mascot import sprite_pixel as sp
    for stage in ("baby", "teen", "adult"):
        assert sp.grid_for(stage, "happy")[6:11] == sp._FACES["happy"], stage


def test_grid_for_unknown_stage_falls_back_to_baby():
    from mascot import sprite_pixel as sp
    assert sp.grid_for("mystery", "idle") == sp.grid_for("baby", "idle")


def test_every_shop_item_has_valid_pixel_art():
    # Every catalog item is showcased with its own 12x12 art in the Pet window.
    from mascot import item_art, shop
    for it in shop.CATALOG:
        assert item_art.has_art(it["id"]), it["id"]
    for item_id, grid in item_art._ITEMS.items():
        assert len(grid) == item_art.GRID, item_id
        assert all(len(row) == item_art.GRID for row in grid), item_id


# --- configurable attention shake -----------------------------------------

def test_settings_defaults_include_shake_controls():
    from mascot import settings as settings_mod
    assert "shake_after_s" in settings_mod.DEFAULTS
    assert "shake_max_amp_px" in settings_mod.DEFAULTS


def test_settings_defaults_include_home_monitor():
    from mascot import settings as settings_mod
    assert settings_mod.DEFAULTS.get("home_monitor") == -1


def test_settings_default_to_quiet():
    # PRD #67 (#68): a fresh install is a simple hook visualiser — no pet layer,
    # no OS toasts. Both stay one toggle away (the Settings panel; the tray's
    # checkable Notifications row for toasts).
    from mascot import settings as settings_mod
    assert settings_mod.DEFAULTS["tamagotchi_enabled"] is False
    assert settings_mod.DEFAULTS["native_notifications"] is False


def test_config_clamp_handles_bounds_and_bad_values():
    from mascot import config
    assert config._clamp("nope", 5, 120, 30) == 30   # unparseable -> default
    assert config._clamp(None, 5, 120, 30) == 30     # missing -> default
    assert config._clamp(1000, 5, 120, 30) == 120    # above max -> clamped
    assert config._clamp(1, 5, 120, 30) == 5         # below min -> clamped
    assert config._clamp(42, 5, 120, 30) == 42       # in range -> kept


def test_desktop_entry_contains_required_keys():
    from mascot import desktop_entry
    text = desktop_entry.build("Claude Familiar", '"/usr/bin/python3" -m mascot.qt_control_panel',
                               icon="/x/icon.png", path="/x", comment="hi")
    assert text.startswith("[Desktop Entry]")
    for key in ("Type=Application", "Name=Claude Familiar", "Exec=", "Icon=/x/icon.png",
                "Path=/x", "Terminal=false"):
        assert key in text


# --- multi-monitor popup placement ----------------------------------------
# bounds = (x, y, width, height) work area of the monitor the card sits on.
_PRIMARY = (0, 0, 1920, 1080)
_RIGHT = (1920, 0, 1920, 1080)        # second monitor to the right of primary
_LEFT = (-1920, 0, 1920, 1080)        # second monitor to the left of primary


def test_tooltip_beside_prefers_left_within_primary():
    # Card mid-primary: tooltip sits just to its left, fully on-screen.
    x, _ = popup_place.beside(800, 500, 158, 196, 120, 40, _PRIMARY, gap=6)
    assert x == 800 - 120 - 6
    assert _PRIMARY[0] <= x <= _PRIMARY[0] + _PRIMARY[2] - 120


def test_tooltip_follows_card_onto_right_monitor():
    # Card dragged onto the right monitor: the tooltip must stay on THAT monitor,
    # not get clamped back onto the primary (the bug being fixed).
    x, _ = popup_place.beside(2000, 500, 158, 196, 120, 40, _RIGHT, gap=6)
    assert x >= _RIGHT[0]                       # on the right monitor, not primary
    assert x <= _RIGHT[0] + _RIGHT[2] - 120


def test_tooltip_follows_card_onto_left_monitor_negative_coords():
    # Left monitor uses negative virtual-desktop coordinates; the tooltip must
    # clamp into that monitor's range, not snap to x=0 on the primary.
    x, _ = popup_place.beside(-1800, 500, 158, 196, 120, 40, _LEFT, gap=6)
    assert _LEFT[0] <= x <= _LEFT[0] + _LEFT[2] - 120
    assert x < 0                                # stayed on the left monitor


def test_bubble_above_centers_over_card_and_clamps_to_monitor():
    x, y = popup_place.above(2000, 400, 158, 196, 80, _RIGHT, gap=6)
    assert _RIGHT[0] <= x <= _RIGHT[0] + _RIGHT[2] - 196
    assert y == 400 - 80 - 6                    # sits above the card


def test_bubble_above_drops_below_card_when_no_room_at_monitor_top():
    # Card hard against the monitor's top edge: the bubble can't go above, so it
    # hugs the card top instead of rendering off-screen.
    _, y = popup_place.above(800, 0, 158, 196, 80, _PRIMARY, gap=6)
    assert y == 0


# --- caption tool field (surfaced as 'Bash…' while a tool runs) ------------

def test_nested_tool_does_not_set_caption_tool():
    # A tool inside a sub-agent (top-level agent_id) isn't the visible session's
    # work, so it must not become the main caption tool.
    payload = {"session_id": SID, "tool_name": "Read", "agent_id": "a1", "tool_input": {}}
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["tool"] is None


def test_agent_spawn_clears_caption_tool():
    start = base()
    start["tool"] = "Bash"
    payload = {"session_id": SID, "tool_name": "Agent", "tool_input": {}, "tool_use_id": "t1"}
    out = compute_next_state(start, "PreToolUse", payload)
    assert out["tool"] is None


def test_post_tool_use_clears_caption_tool():
    # A finished main-thread tool clears the caption tool (Claude reasons between
    # tools), so 'Bash…' doesn't linger after Bash returns.
    start = base()
    start["tool"] = "Bash"
    out = compute_next_state(start, "PostToolUse", {"session_id": SID, "tool_name": "Bash"})
    assert out["tool"] is None


def test_nested_post_tool_use_keeps_caption_tool():
    # A sub-agent's internal tool finishing must not wipe the main caption tool.
    start = base()
    start["tool"] = "Bash"
    out = compute_next_state(
        start, "PostToolUse", {"session_id": SID, "tool_name": "Read", "agent_id": "a1"})
    assert out["tool"] == "Bash"


# --- effective state (pure watchdog / overlay logic) ----------------------

def _eff(raw, now=100.0, **over):
    kw = {"ts": now, "dizzy_until": 0.0, "celebrate_until": 0.0, "waiting_since": None,
          "idle_since": None, "blink_until": 0.0, "sleep_after_idle_s": 60.0,
          "shake_after_s": 30.0, "thinking_stall_s": 180.0, "working_stall_s": 240.0}
    kw.update(over)
    return effective_state.compute(raw, now, **kw)


def test_effective_dizzy_outranks_everything():
    assert _eff("working", now=100.0, dizzy_until=200.0) == "dizzy"


def test_effective_happy_on_recent_celebrate():
    assert _eff("idle", now=100.0, celebrate_until=200.0) == "happy"


def test_effective_waiting_turns_angry_after_shake_threshold():
    assert _eff("waiting", now=100.0, waiting_since=60.0, shake_after_s=30.0) == "waiting_angry"
    assert _eff("waiting", now=100.0, waiting_since=80.0, shake_after_s=30.0) == "waiting"


def test_effective_thinking_stall_falls_to_idle():
    assert _eff("thinking", now=1000.0, ts=800.0, thinking_stall_s=180.0) == "idle"


def test_effective_working_stall_falls_to_idle():
    # The regression at the heart of the limit-freeze fix: a stale `working`
    # (no closing hook) must fall back to idle, not stay frozen.
    assert _eff("working", now=1000.0, ts=700.0, working_stall_s=240.0) == "idle"


def test_effective_working_protected_before_stall():
    # A long-running tool (still under the grace window) keeps showing working.
    assert _eff("working", now=1000.0, ts=800.0, working_stall_s=240.0) == "working"


def test_effective_idle_dozes_to_sleeping():
    assert _eff("idle", now=1000.0, idle_since=880.0, sleep_after_idle_s=60.0) == "sleeping"


def test_effective_idle_blink_window():
    assert _eff("idle", now=1000.0, idle_since=995.0, blink_until=1001.0) == "idle_blink"


def test_effective_fresh_working_passes_through():
    assert _eff("working", now=1000.0, ts=1000.0) == "working"


def test_effective_idle_face_reflects_pet_mood():
    # While genuinely idle (and not dozing/blinking), the idle face is tinted by the
    # pet's mood — droopy/sad/sleepy when low, sparkly when well-cared-for.
    assert _eff("idle", now=100.0, mood="hungry") == "idle_hungry"
    assert _eff("idle", now=100.0, mood="sad") == "idle_sad"
    assert _eff("idle", now=100.0, mood="tired") == "idle_tired"
    assert _eff("idle", now=100.0, mood="happy") == "idle_happy"
    assert _eff("idle", now=100.0, mood="content") == "idle"


def test_effective_default_mood_is_plain_idle():
    # No mood supplied -> plain idle face (back-compat with callers that don't pass one).
    assert _eff("idle", now=100.0) == "idle"


def test_effective_claude_states_always_override_mood():
    # The contract: Claude-activity states win over pet mood on the face, so the
    # mascot never lies about what Claude is doing.
    assert _eff("working", now=100.0, mood="hungry") == "working"
    assert _eff("thinking", now=100.0, mood="sad") == "thinking"
    assert _eff("waiting", now=100.0, mood="happy") == "waiting"
    assert _eff("dead", now=100.0, mood="hungry") == "dead"


def test_effective_sleeping_and_blink_outrank_mood():
    # Dozing / blinking are part of the idle rhythm and outrank the mood tint.
    assert _eff("idle", now=1000.0, idle_since=880.0, sleep_after_idle_s=60.0,
                mood="hungry") == "sleeping"
    assert _eff("idle", now=1000.0, idle_since=995.0, blink_until=1001.0,
                mood="hungry") == "idle_blink"


def test_effective_stalled_busy_never_sleeps_with_idle_since():
    # Footgun guard: a stalled busy state must resolve to idle and NEVER sleeping,
    # even if an idle_since timer happens to be set. The watchdog early-returns idle
    # rather than rewriting raw and falling through into the idle->sleeping overlay.
    assert _eff("working", now=1000.0, ts=700.0, working_stall_s=240.0,
                idle_since=800.0, sleep_after_idle_s=60.0) == "idle"
    assert _eff("thinking", now=1000.0, ts=700.0, thinking_stall_s=180.0,
                idle_since=800.0, sleep_after_idle_s=60.0) == "idle"


# --- home-monitor work-area selection (pure) ------------------------------
# monitors = list of (x, y, w, h) work areas in enumeration order.
_MON = [(0, 0, 1920, 1040), (1920, 0, 2560, 1400)]   # primary + a second display
_PRIMARY_WA = (0, 0, 1920, 1040)


def test_choose_work_area_valid_index_returns_that_monitor():
    from mascot import osplatform
    assert osplatform.choose_work_area(1, _MON, _PRIMARY_WA) == (1920, 0, 2560, 1400)


def test_choose_work_area_auto_default_returns_primary():
    # The default home_monitor (-1, "auto") anchors to the primary work area.
    from mascot import osplatform
    assert osplatform.choose_work_area(-1, _MON, _PRIMARY_WA) == _PRIMARY_WA


def test_choose_work_area_out_of_range_index_falls_back_to_primary():
    # A stale/unplugged index (>= monitor count) falls back to primary, not a crash.
    from mascot import osplatform
    assert osplatform.choose_work_area(5, _MON, _PRIMARY_WA) == _PRIMARY_WA


def test_choose_work_area_non_int_setting_falls_back_to_primary():
    # A hand-edited/garbage setting must not crash — fall back to primary.
    from mascot import osplatform
    assert osplatform.choose_work_area("nope", _MON, _PRIMARY_WA) == _PRIMARY_WA
    assert osplatform.choose_work_area(None, _MON, _PRIMARY_WA) == _PRIMARY_WA


def test_choose_work_area_empty_monitors_returns_primary():
    # No enumerated monitors (off Windows / lookup failed) -> primary (may be None).
    from mascot import osplatform
    assert osplatform.choose_work_area(0, [], _PRIMARY_WA) == _PRIMARY_WA
    assert osplatform.choose_work_area(-1, [], None) is None


# --- Tamagotchi pet engine (pure core) ------------------------------------
# Behavioral tests for the clock-free / I/O-free pet core. They assert STRUCTURE
# (direction, clamping, monotonicity, immutability) rather than the exact decay
# rates / coin amounts, which the PRD calls a tuning pass — so balancing later
# never breaks the contract. One hour of elapsed time is the convenient unit.
_HOUR = 3600.0
_DAY = 86400.0


def _pet(**over):
    """A fresh, valid pet dict for synthetic-input tests (full stats by default)."""
    p = {
        "name": "", "born": 0.0, "last_seen": 0.0,
        "hunger": 100, "happiness": 100, "energy": 100,
        "coins": 0, "xp": 0, "coins_today": 0, "last_award_date": "",
        "inventory": {}, "cooldowns": {},
    }
    p.update(over)
    return p


def test_decay_lowers_hunger_and_happiness_over_time():
    from mascot import pet_logic
    out = pet_logic.decay(_pet(), _HOUR, working=True)
    assert out["hunger"] < 100
    assert out["happiness"] < 100


def test_decay_is_monotonic_more_elapsed_lowers_more():
    from mascot import pet_logic
    short = pet_logic.decay(_pet(), 600.0, working=True)
    long = pet_logic.decay(_pet(), _HOUR, working=True)
    assert long["hunger"] < short["hunger"]
    assert long["happiness"] < short["happiness"]


def test_energy_drains_while_working_refills_while_idle():
    # The pet's rhythm mirrors the user's: energy drops while Claude works and
    # recovers while idle/asleep.
    from mascot import pet_logic
    working = pet_logic.decay(_pet(energy=50), _HOUR, working=True)
    idle = pet_logic.decay(_pet(energy=50), _HOUR, working=False)
    assert working["energy"] < 50
    assert idle["energy"] > 50


def test_decay_clamps_at_zero_never_negative():
    # Soft-needs tone: stats bottom out at 0, never go negative (no punishment).
    from mascot import pet_logic
    out = pet_logic.decay(_pet(hunger=1, happiness=1, energy=1), 100 * _HOUR, working=True)
    assert out["hunger"] == 0
    assert out["happiness"] == 0
    assert out["energy"] == 0


def test_energy_refill_clamps_at_max():
    from mascot import pet_logic
    out = pet_logic.decay(_pet(energy=95), 100 * _HOUR, working=False)
    assert out["energy"] == pet_logic.MAX_STAT


def test_decay_zero_elapsed_is_noop():
    from mascot import pet_logic
    out = pet_logic.decay(_pet(hunger=50, happiness=50, energy=50), 0.0, working=True)
    assert (out["hunger"], out["happiness"], out["energy"]) == (50, 50, 50)


def test_decay_negative_elapsed_is_safe_noop():
    # A clock skew (now < last_seen) must not ADD hunger or crash.
    from mascot import pet_logic
    out = pet_logic.decay(_pet(hunger=50, energy=50), -123.0, working=True)
    assert out["hunger"] == 50
    assert out["energy"] == 50


def test_decay_does_not_mutate_input():
    from mascot import pet_logic
    pet = _pet(hunger=50)
    pet_logic.decay(pet, _HOUR, working=True)
    assert pet["hunger"] == 50


def test_apply_effects_adds_positive_deltas():
    from mascot import pet_logic
    out = pet_logic.apply_effects(_pet(hunger=50), {"hunger": 30})
    assert out["hunger"] == 80


def test_apply_effects_supports_negative_deltas():
    # A trade-off item (energy drink): +energy but -happiness.
    from mascot import pet_logic
    out = pet_logic.apply_effects(_pet(energy=40, happiness=60), {"energy": 30, "happiness": -20})
    assert out["energy"] == 70
    assert out["happiness"] == 40


def test_apply_effects_clamps_to_max():
    from mascot import pet_logic
    out = pet_logic.apply_effects(_pet(hunger=90), {"hunger": 50})
    assert out["hunger"] == pet_logic.MAX_STAT


def test_apply_effects_clamps_to_zero_negative_safe():
    from mascot import pet_logic
    out = pet_logic.apply_effects(_pet(happiness=10), {"happiness": -50})
    assert out["happiness"] == 0


def test_apply_effects_ignores_non_need_stats():
    # Effects only touch the three needs — a shop item can never grant coins/XP/
    # power (PRD: coins buy only care/cosmetic goods, never advantage).
    from mascot import pet_logic
    out = pet_logic.apply_effects(_pet(coins=0, xp=0), {"coins": 999, "xp": 999, "bogus": 5})
    assert out["coins"] == 0
    assert out["xp"] == 0


def test_apply_effects_does_not_mutate_input():
    from mascot import pet_logic
    pet = _pet(hunger=50)
    pet_logic.apply_effects(pet, {"hunger": 10})
    assert pet["hunger"] == 50


def test_award_adds_coins_and_xp():
    from mascot import pet_logic
    out = pet_logic.award(_pet(), coins=5, xp=10, today="2026-06-17")
    assert out["coins"] == 5
    assert out["xp"] == 10


def test_award_xp_is_not_capped():
    # XP fuels long-term leveling and is intentionally uncapped; only COINS are
    # capped (PRD: a daily coin cap so it never pays to over-use Claude). Age-gated
    # evolution is what stops XP-grinding, not an XP cap.
    from mascot import pet_logic
    out = pet_logic.award(_pet(), coins=0, xp=100_000, today="2026-06-17")
    assert out["xp"] == 100_000


def test_award_coins_capped_per_day():
    from mascot import pet_logic
    cap = pet_logic.DAILY_COIN_CAP
    out = pet_logic.award(_pet(), coins=cap + 50, xp=0, today="2026-06-17")
    assert out["coins"] == cap
    assert out["coins_today"] == cap


def test_award_coins_accumulate_up_to_cap_across_calls():
    from mascot import pet_logic
    cap = pet_logic.DAILY_COIN_CAP
    p = pet_logic.award(_pet(), coins=cap - 1, xp=0, today="2026-06-17")
    p = pet_logic.award(p, coins=10, xp=0, today="2026-06-17")  # only 1 more fits
    assert p["coins"] == cap
    assert p["coins_today"] == cap


def test_award_cap_resets_on_new_day():
    from mascot import pet_logic
    cap = pet_logic.DAILY_COIN_CAP
    maxed = pet_logic.award(_pet(), coins=cap, xp=0, today="2026-06-17")
    assert maxed["coins"] == cap
    # A new day refreshes the daily allowance; the lifetime coin total keeps growing.
    nextday = pet_logic.award(maxed, coins=5, xp=0, today="2026-06-18")
    assert nextday["coins"] == cap + 5
    assert nextday["coins_today"] == 5
    assert nextday["last_award_date"] == "2026-06-18"


def test_award_does_not_mutate_input():
    from mascot import pet_logic
    pet = _pet()
    pet_logic.award(pet, coins=5, xp=5, today="2026-06-17")
    assert pet["coins"] == 0 and pet["xp"] == 0


def _sess(state="idle", subagents=None):
    """A minimal session-state slice (the fields the transition mapper reads)."""
    return {"state": state, "subagents": subagents or []}


def _sub(sid):
    return {"id": sid, "type": "agent", "description": ""}


def test_transition_working_to_idle_is_a_completed_turn():
    from mascot import pet_logic
    assert pet_logic.events_for_transition(_sess("working"), _sess("idle")) == ["turn_completed"]


def test_transition_thinking_to_idle_is_a_completed_turn():
    from mascot import pet_logic
    assert pet_logic.events_for_transition(_sess("thinking"), _sess("idle")) == ["turn_completed"]


def test_transition_waiting_to_idle_is_not_a_completed_turn():
    # Answering a permission prompt isn't a finished turn — no reward (mirrors the
    # happy-celebrate trigger, which also excludes waiting->idle and dead).
    from mascot import pet_logic
    out = pet_logic.events_for_transition(_sess("waiting"), _sess("idle"))
    assert "turn_completed" not in out


def test_transition_revive_from_dead_is_not_a_completed_turn():
    from mascot import pet_logic
    assert pet_logic.events_for_transition(_sess("dead"), _sess("thinking")) == []


def test_transition_vanished_subagent_badge_is_a_finished_subagent():
    from mascot import pet_logic
    out = pet_logic.events_for_transition(_sess("working", [_sub("a")]), _sess("working", []))
    assert out == ["subagent_finished"]


def test_transition_counts_each_vanished_subagent():
    from mascot import pet_logic
    prev = _sess("working", [_sub("a"), _sub("b"), _sub("c")])
    nxt = _sess("working", [_sub("b")])  # a and c finished
    assert pet_logic.events_for_transition(prev, nxt).count("subagent_finished") == 2


def test_transition_new_subagent_appearing_is_not_rewarded():
    from mascot import pet_logic
    assert pet_logic.events_for_transition(
        _sess("working", []), _sess("working", [_sub("a")])) == []


def test_transition_turn_end_clearing_badges_awards_turn_and_each_subagent():
    # A Stop ends the turn AND clears badges in one transition: the completed turn
    # plus every sub-agent that was still listed both count.
    from mascot import pet_logic
    out = pet_logic.events_for_transition(
        _sess("working", [_sub("a"), _sub("b")]), _sess("idle", []))
    assert "turn_completed" in out
    assert out.count("subagent_finished") == 2


def test_started_prompt_detects_entering_thinking():
    from mascot import pet_logic
    assert pet_logic.started_prompt(_sess("idle"), _sess("thinking")) is True
    assert pet_logic.started_prompt(_sess("waiting"), _sess("thinking")) is True
    assert pet_logic.started_prompt(_sess("dead"), _sess("thinking")) is True


def test_started_prompt_false_when_already_thinking_or_not_thinking():
    from mascot import pet_logic
    assert pet_logic.started_prompt(_sess("thinking"), _sess("thinking")) is False
    assert pet_logic.started_prompt(_sess("working"), _sess("idle")) is False
    assert pet_logic.started_prompt(_sess("thinking"), _sess("working")) is False


def test_apply_events_rewards_a_completed_turn():
    from mascot import pet_logic
    out = pet_logic.apply_events(_pet(), ["turn_completed"], today="2026-06-17")
    coins, xp = pet_logic.EVENT_REWARDS["turn_completed"]
    assert out["coins"] == coins
    assert out["xp"] == xp
    assert coins > 0  # a finished turn is worth something


def test_apply_events_stacks_multiple_events():
    from mascot import pet_logic
    events = ["turn_completed", "subagent_finished"]
    out = pet_logic.apply_events(_pet(), events, today="2026-06-17")
    assert out["coins"] == sum(pet_logic.EVENT_REWARDS[e][0] for e in events)
    assert out["xp"] == sum(pet_logic.EVENT_REWARDS[e][1] for e in events)


def test_apply_events_ignores_unknown_event():
    from mascot import pet_logic
    out = pet_logic.apply_events(_pet(), ["nonsense"], today="2026-06-17")
    assert out["coins"] == 0 and out["xp"] == 0


def test_apply_events_empty_is_a_noop():
    from mascot import pet_logic
    out = pet_logic.apply_events(_pet(coins=7, xp=3), [], today="2026-06-17")
    assert out["coins"] == 7 and out["xp"] == 3


def test_apply_events_still_respects_the_daily_coin_cap():
    # All earning funnels through award(), so a flood of events can't beat the cap.
    from mascot import pet_logic
    out = pet_logic.apply_events(_pet(), ["turn_completed"] * 10_000, today="2026-06-17")
    assert out["coins"] == pet_logic.DAILY_COIN_CAP


def test_apply_events_does_not_mutate_input():
    from mascot import pet_logic
    pet = _pet()
    pet_logic.apply_events(pet, ["turn_completed"], today="2026-06-17")
    assert pet["coins"] == 0


# --- pet tick: the pure per-poll seam (#25) -------------------------------
# Behavioral tests for tick(pet, prev_states, next_states, *, elapsed, working,
# today) -> (pet, awarded). They assert the SEQUENCING and replay guarantees the
# manager relies on, not the manager's I/O. prev_states is the manager's last-seen
# snapshot; next_states is this poll's states.


def test_tick_decays_then_awards_in_one_poll():
    # A poll both ages the needs (decay) and pays out a finished turn (award): a
    # working->idle session over an hour of elapsed time lowers hunger AND adds coins.
    from mascot import pet_logic
    prev = {"s1": _sess("working")}
    nxt = {"s1": _sess("idle")}
    out, awarded = pet_logic.tick(
        _pet(), prev, nxt, elapsed=_HOUR, working=False, today="2026-06-17")
    coins, _ = pet_logic.EVENT_REWARDS[pet_logic.TURN_COMPLETED]
    assert out["hunger"] < 100          # decay ran
    assert out["coins"] == coins        # the completed turn paid out
    assert awarded is True


def test_tick_with_no_transition_only_decays_and_reports_no_award():
    from mascot import pet_logic
    # Same session, same state -> no earnable event, but decay still happens.
    out, awarded = pet_logic.tick(
        _pet(), {"s1": _sess("idle")}, {"s1": _sess("idle")},
        elapsed=_HOUR, working=True, today="2026-06-17")
    assert out["coins"] == 0
    assert out["hunger"] < 100
    assert awarded is False


def test_tick_first_prompt_fires_once_per_calendar_day():
    from mascot import pet_logic
    bonus = pet_logic.EVENT_REWARDS[pet_logic.FIRST_PROMPT_OF_DAY][0]
    # First idle->thinking of the day pays the streak bonus and stamps the date.
    first, awarded = pet_logic.tick(
        _pet(), {"s1": _sess("idle")}, {"s1": _sess("thinking")},
        elapsed=0.0, working=True, today="2026-06-17")
    assert awarded is True
    assert first["coins"] == bonus
    assert first["last_prompt_date"] == "2026-06-17"
    # A second idle->thinking the SAME day must NOT pay the bonus again.
    second, _ = pet_logic.tick(
        first, {"s2": _sess("idle")}, {"s2": _sess("thinking")},
        elapsed=0.0, working=True, today="2026-06-17")
    assert second["coins"] == bonus     # unchanged: no second streak bonus


def test_tick_first_prompt_pays_again_on_a_new_day():
    from mascot import pet_logic
    bonus = pet_logic.EVENT_REWARDS[pet_logic.FIRST_PROMPT_OF_DAY][0]
    day1, _ = pet_logic.tick(
        _pet(), {"s1": _sess("idle")}, {"s1": _sess("thinking")},
        elapsed=0.0, working=True, today="2026-06-17")
    day2, awarded = pet_logic.tick(
        day1, {"s1": _sess("idle")}, {"s1": _sess("thinking")},
        elapsed=0.0, working=True, today="2026-06-18")
    assert awarded is True
    assert day2["coins"] == 2 * bonus
    assert day2["last_prompt_date"] == "2026-06-18"


def test_tick_replay_guard_a_closed_session_cannot_fire_a_stale_transition():
    # A session present in prev_states but GONE this poll (its card closed) must
    # not replay its old working->idle as a fresh completed turn.
    from mascot import pet_logic
    out, awarded = pet_logic.tick(
        _pet(), {"gone": _sess("working")}, {},
        elapsed=0.0, working=False, today="2026-06-17")
    assert out["coins"] == 0
    assert awarded is False


def test_tick_does_not_double_award_when_prev_equals_next():
    # The manager feeds last-seen as prev; once a transition is recorded, replaying
    # the SAME state pair yields no further award (no double-pay across polls).
    from mascot import pet_logic
    settled = {"s1": _sess("idle")}
    out, awarded = pet_logic.tick(
        _pet(), settled, settled, elapsed=0.0, working=False, today="2026-06-17")
    assert out["coins"] == 0
    assert awarded is False


def test_tick_working_aggregate_controls_energy_direction():
    # The manager's working flag is documented at the seam: energy drains when
    # working is True and refills when False, all else equal.
    from mascot import pet_logic
    busy, _ = pet_logic.tick(
        _pet(energy=50), {"s1": _sess("idle")}, {"s1": _sess("idle")},
        elapsed=_HOUR, working=True, today="2026-06-17")
    rested, _ = pet_logic.tick(
        _pet(energy=50), {"s1": _sess("idle")}, {"s1": _sess("idle")},
        elapsed=_HOUR, working=False, today="2026-06-17")
    assert busy["energy"] < 50
    assert rested["energy"] > 50


def test_tick_does_not_mutate_input_pet_or_states():
    from mascot import pet_logic
    pet = _pet(hunger=50)
    prev = {"s1": _sess("working")}
    nxt = {"s1": _sess("idle")}
    pet_snapshot = json.dumps(pet, sort_keys=True)
    prev_snapshot = json.dumps(prev, sort_keys=True)
    nxt_snapshot = json.dumps(nxt, sort_keys=True)
    pet_logic.tick(pet, prev, nxt, elapsed=_HOUR, working=True, today="2026-06-17")
    assert json.dumps(pet, sort_keys=True) == pet_snapshot
    assert json.dumps(prev, sort_keys=True) == prev_snapshot
    assert json.dumps(nxt, sort_keys=True) == nxt_snapshot


def test_mood_all_needs_high_is_happy():
    from mascot import pet_logic
    assert pet_logic.mood(_pet(hunger=100, happiness=100, energy=100)) == "happy"


def test_mood_low_hunger_is_hungry():
    from mascot import pet_logic
    assert pet_logic.mood(_pet(hunger=5, happiness=80, energy=80)) == "hungry"


def test_mood_low_energy_is_tired():
    from mascot import pet_logic
    assert pet_logic.mood(_pet(hunger=80, happiness=80, energy=5)) == "tired"


def test_mood_low_happiness_is_sad():
    from mascot import pet_logic
    assert pet_logic.mood(_pet(hunger=80, happiness=5, energy=80)) == "sad"


def test_mood_moderate_needs_is_content():
    # Nothing depleted, nothing maxed -> a neutral, content mood.
    from mascot import pet_logic
    assert pet_logic.mood(_pet(hunger=50, happiness=50, energy=50)) == "content"


def test_mood_single_most_depleted_need_wins():
    from mascot import pet_logic
    # Several needs low, but the single lowest (happiness) defines the mood.
    assert pet_logic.mood(_pet(hunger=20, happiness=5, energy=20)) == "sad"


def test_mood_ties_break_deterministically_hunger_first():
    from mascot import pet_logic
    # Equal-low hunger and energy -> hunger wins (deterministic tie-break).
    assert pet_logic.mood(_pet(hunger=10, happiness=80, energy=10)) == "hungry"


def test_level_starts_at_one_for_a_new_pet():
    from mascot import pet_logic
    assert pet_logic.level_for_xp(0) == 1


def test_level_is_monotonic_non_decreasing_in_xp():
    from mascot import pet_logic
    levels = [pet_logic.level_for_xp(x) for x in range(0, 2000, 50)]
    assert levels == sorted(levels)
    assert levels[-1] > levels[0]   # and it does climb


def test_first_levelup_at_the_xp_threshold():
    # The first level-up (egg hatches here) happens at exactly one level's worth
    # of XP — locked via the constant so the curve can be tuned freely.
    from mascot import pet_logic
    n = pet_logic.XP_PER_LEVEL
    assert pet_logic.level_for_xp(n - 1) == 1
    assert pet_logic.level_for_xp(n) == 2


def test_stage_level_one_is_an_egg_regardless_of_age():
    # The pet starts as an egg and stays one until the first level-up — even if it
    # has been around a long while.
    from mascot import pet_logic
    assert pet_logic.stage_for(1, 100 * _DAY) == "egg"


def test_stage_hatches_to_baby_on_first_levelup():
    from mascot import pet_logic
    assert pet_logic.stage_for(2, 0.0) == "baby"


def test_stage_reaches_teen_then_adult_with_enough_level_and_age():
    from mascot import pet_logic
    assert pet_logic.stage_for(5, 2 * _DAY) == "teen"
    assert pet_logic.stage_for(20, 10 * _DAY) == "adult"


def test_stage_is_age_gated_a_young_high_level_pet_is_not_yet_adult():
    # Evolution honors real elapsed time: a level-20 pet only hours old can't be an
    # adult yet — the age gate is what stops XP-grinding from skipping stages.
    from mascot import pet_logic
    young = pet_logic.stage_for(20, 0.0)
    assert young != "adult"
    assert young in ("baby", "teen")


# --- Tamagotchi persistence wrapper (pet_store, file I/O) ------------------

def test_default_pet_is_full_and_fresh():
    from mascot import pet_logic, pet_store
    pet = pet_store.default_pet(now=1000.0)
    assert pet["hunger"] == pet_logic.MAX_STAT
    assert pet["happiness"] == pet_logic.MAX_STAT
    assert pet["energy"] == pet_logic.MAX_STAT
    assert pet["coins"] == 0 and pet["xp"] == 0
    assert pet["born"] == 1000.0 and pet["last_seen"] == 1000.0


def test_pet_round_trips_through_save_then_load(tmp_path):
    from mascot import pet_store
    path = tmp_path / "pet.json"
    pet = pet_store.default_pet(now=1000.0)
    pet["name"], pet["coins"], pet["xp"] = "Mochi", 42, 350
    pet_store.save(path, pet, now=1000.0)
    loaded = pet_store.load(path, now=1000.0)  # same instant -> no decay
    assert loaded["name"] == "Mochi"
    assert loaded["coins"] == 42
    assert loaded["xp"] == 350


def test_load_missing_file_yields_a_fresh_default_pet(tmp_path):
    from mascot import pet_logic, pet_store
    loaded = pet_store.load(tmp_path / "nope.json", now=1000.0)
    assert loaded["coins"] == 0
    assert loaded["hunger"] == pet_logic.MAX_STAT
    assert loaded["born"] == 1000.0


def test_load_corrupt_file_yields_a_fresh_default_pet(tmp_path):
    from mascot import pet_logic, pet_store
    path = tmp_path / "pet.json"
    path.write_text("{ this is not valid json", encoding="utf-8")
    loaded = pet_store.load(path, now=1000.0)
    assert loaded["coins"] == 0
    assert loaded["hunger"] == pet_logic.MAX_STAT


def test_load_applies_decay_for_real_elapsed_time(tmp_path):
    # decay-on-load: a pet saved an hour ago resumes hungrier, via last_seen.
    from mascot import pet_store
    path = tmp_path / "pet.json"
    pet_store.save(path, pet_store.default_pet(now=0.0), now=0.0)
    loaded = pet_store.load(path, now=_HOUR, working=False)
    assert loaded["hunger"] < 100
    assert loaded["happiness"] < 100


def test_load_restamps_last_seen_to_now(tmp_path):
    from mascot import pet_store
    path = tmp_path / "pet.json"
    pet_store.save(path, pet_store.default_pet(now=0.0), now=0.0)
    loaded = pet_store.load(path, now=_HOUR)
    assert loaded["last_seen"] == _HOUR


def test_load_fills_missing_keys_for_forward_compat(tmp_path):
    # An old / hand-edited pet.json missing newer fields upgrades cleanly.
    from mascot import pet_store
    path = tmp_path / "pet.json"
    path.write_text(json.dumps({"coins": 5, "last_seen": 0.0}), encoding="utf-8")
    loaded = pet_store.load(path, now=0.0)
    assert loaded["coins"] == 5            # preserved
    assert "hunger" in loaded              # filled from defaults
    assert "inventory" in loaded


def test_load_preserves_born_across_restarts(tmp_path):
    # Age must survive restarts: born is not reset to "now" on reload.
    from mascot import pet_store
    path = tmp_path / "pet.json"
    pet_store.save(path, pet_store.default_pet(now=100.0), now=100.0)
    loaded = pet_store.load(path, now=5000.0)
    assert loaded["born"] == 100.0


def test_save_stamps_last_seen_and_round_trips_on_disk(tmp_path):
    from mascot import pet_store
    path = tmp_path / "pet.json"
    pet_store.save(path, pet_store.default_pet(now=0.0), now=555.0)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["last_seen"] == 555.0
    assert written["hunger"] == 100


# --- Tamagotchi shop (pure: catalog + buy / feed / play) -------------------

def test_catalog_has_food_and_toys_with_unique_ids():
    from mascot import shop
    ids = [it["id"] for it in shop.CATALOG]
    assert len(ids) == len(set(ids))                       # no dup ids
    types = {it["type"] for it in shop.CATALOG}
    assert shop.FOOD in types and shop.TOY in types
    for it in shop.CATALOG:                                # every row is well-formed
        assert it["price"] > 0 and it["min_level"] >= 1 and isinstance(it["effects"], dict)


def test_item_by_id_finds_and_misses():
    from mascot import shop
    assert shop.item_by_id(shop.CATALOG[0]["id"]) is shop.CATALOG[0]
    assert shop.item_by_id("nope") is None


def test_is_unlocked_gates_by_level():
    from mascot import shop
    gated = {"id": "x", "name": "X", "price": 1, "type": shop.FOOD, "effects": {}, "min_level": 3}
    assert shop.is_unlocked(gated, level=2) is False
    assert shop.is_unlocked(gated, level=3) is True


def test_can_buy_rejects_when_too_few_coins():
    from mascot import shop
    item = {"id": "x", "name": "X", "price": 50, "type": shop.FOOD, "effects": {}, "min_level": 1}
    ok, _ = shop.can_buy(_pet(coins=10), item, level=1)
    assert ok is False


def test_can_buy_rejects_when_locked_by_level():
    from mascot import shop
    item = {"id": "x", "name": "X", "price": 1, "type": shop.FOOD, "effects": {}, "min_level": 5}
    ok, _ = shop.can_buy(_pet(coins=999), item, level=1)
    assert ok is False


def test_can_buy_rejects_a_toy_already_owned():
    # Toys are reusable (play on a cooldown), so they're a one-time purchase.
    from mascot import shop
    toy = {"id": "ball", "name": "Ball", "price": 20, "type": shop.TOY,
           "effects": {"happiness": 20}, "cooldown_s": 300, "min_level": 1}
    assert shop.can_buy(_pet(coins=999, inventory={"ball": 1}), toy, level=1)[0] is False
    assert shop.can_buy(_pet(coins=999, inventory={}), toy, level=1)[0] is True


def test_can_buy_allows_stacking_food():
    # Food is consumable, so you can always buy more.
    from mascot import shop
    food = {"id": "snack", "name": "Snack", "price": 10, "type": shop.FOOD,
            "effects": {"hunger": 25}, "min_level": 1}
    assert shop.can_buy(_pet(coins=999, inventory={"snack": 3}), food, level=1)[0] is True


def test_buy_spends_coins_and_adds_to_inventory():
    from mascot import shop
    item = {"id": "snack", "name": "Snack", "price": 30, "type": shop.FOOD,
            "effects": {}, "min_level": 1}
    out = shop.buy(_pet(coins=100), item)
    assert out["coins"] == 70
    assert out["inventory"]["snack"] == 1


def test_buy_does_not_mutate_input():
    from mascot import shop
    item = {"id": "snack", "name": "Snack", "price": 30, "type": shop.FOOD,
            "effects": {}, "min_level": 1}
    pet = _pet(coins=100)
    shop.buy(pet, item)
    assert pet["coins"] == 100 and pet["inventory"] == {}


_SNACK = {"id": "snack", "name": "Snack", "price": 10, "type": "food",
          "effects": {"hunger": 30}, "min_level": 1}


def test_can_feed_requires_food_and_ownership():
    from mascot import shop
    assert shop.can_feed(_pet(inventory={}), _SNACK)[0] is False           # none owned
    assert shop.can_feed(_pet(inventory={"snack": 1}), _SNACK)[0] is True
    toy = {"id": "ball", "name": "Ball", "price": 1, "type": "toy", "effects": {}, "min_level": 1}
    assert shop.can_feed(_pet(inventory={"ball": 1}), toy)[0] is False     # not food


def test_feed_applies_effects_consumes_one_and_grants_xp():
    from mascot import shop
    pet = _pet(hunger=40, xp=0, inventory={"snack": 2})
    out = shop.feed(pet, _SNACK)
    assert out["hunger"] == 70                       # +30 effect
    assert out["inventory"]["snack"] == 1            # one consumed
    assert out["xp"] == shop.CARE_XP                 # caring earns XP


def test_feed_last_item_clears_it_from_inventory():
    from mascot import shop
    out = shop.feed(_pet(inventory={"snack": 1}), _SNACK)
    assert "snack" not in out["inventory"]


def test_feed_trade_off_item_clamps_negative_effect():
    from mascot import shop
    drink = {"id": "energy_drink", "name": "Energy Drink", "price": 30, "type": "food",
             "effects": {"energy": 40, "happiness": -15}, "min_level": 2}
    out = shop.feed(_pet(energy=50, happiness=10, inventory={"energy_drink": 1}), drink)
    assert out["energy"] == 90
    assert out["happiness"] == 0                      # 10 - 15 clamped to 0


def test_feed_does_not_mutate_input():
    from mascot import shop
    pet = _pet(hunger=40, inventory={"snack": 2})
    shop.feed(pet, _SNACK)
    assert pet["hunger"] == 40 and pet["inventory"]["snack"] == 2


_BALL = {"id": "ball", "name": "Ball", "price": 20, "type": "toy",
         "effects": {"happiness": 20}, "cooldown_s": 300, "min_level": 1}


def test_can_play_requires_toy_and_ownership():
    from mascot import shop
    assert shop.can_play(_pet(inventory={}), _BALL, now=0.0)[0] is False        # none owned
    assert shop.can_play(_pet(inventory={"ball": 1}), _BALL, now=0.0)[0] is True
    assert shop.can_play(_pet(inventory={"snack": 1}), _SNACK, now=0.0)[0] is False  # not a toy


def test_play_applies_happiness_sets_cooldown_keeps_toy_and_grants_xp():
    from mascot import shop
    pet = _pet(happiness=40, xp=0, inventory={"ball": 1})
    out = shop.play(pet, _BALL, now=1000.0)
    assert out["happiness"] == 60                    # +20 effect
    assert out["inventory"]["ball"] == 1             # toys are reusable, not consumed
    assert out["cooldowns"]["ball"] == 1000.0        # cooldown stamped
    assert out["xp"] == shop.CARE_XP


def test_can_play_rejected_during_cooldown_then_allowed_after():
    from mascot import shop
    played = shop.play(_pet(happiness=40, inventory={"ball": 1}), _BALL, now=1000.0)
    # still resting a moment later...
    assert shop.can_play(played, _BALL, now=1100.0)[0] is False
    # ...and ready again once the cooldown elapses.
    assert shop.can_play(played, _BALL, now=1000.0 + _BALL["cooldown_s"])[0] is True


def test_cooldown_remaining_counts_down_to_zero():
    from mascot import shop
    played = shop.play(_pet(inventory={"ball": 1}), _BALL, now=1000.0)
    assert shop.cooldown_remaining(played, _BALL, now=1000.0) == _BALL["cooldown_s"]
    assert shop.cooldown_remaining(played, _BALL, now=1000.0 + _BALL["cooldown_s"]) == 0.0


def test_play_does_not_mutate_input():
    from mascot import shop
    pet = _pet(happiness=40, inventory={"ball": 1})
    shop.play(pet, _BALL, now=1000.0)
    assert pet["happiness"] == 40 and pet["cooldowns"] == {}


# --- effective-state overlay (the stateful seam over the pure core, #26) ---
# The overlay OWNS the five expiry timers + thresholds; its `effective(now, mood)`
# read must return EXACTLY what bare `compute` returns for the same timers. These
# tests pin that equivalence across the whole priority ladder, plus the intent
# writes and the two narrow timer reads the card relies on (tap gate, shake).

_OVER_CFG = {"dizzy_duration_s": 2.0, "celebrate_duration_s": 1.5, "blink_duration_s": 0.12,
             "sleep_after_idle_s": 60.0, "shake_after_s": 30.0,
             "thinking_stall_s": 180.0, "working_stall_s": 240.0}


def _overlay(raw="idle", now=0.0):
    from mascot import overlay as overlay_mod
    return overlay_mod.Overlay(overlay_mod.OverlayConfig(**_OVER_CFG), raw=raw, now=now)


def test_overlay_matches_bare_compute_across_the_full_ladder():
    # Each row drives the overlay with intent writes to set up one rung of the
    # ladder, then asserts effective() == the rung's expected displayed state.
    o_dizzy = _overlay()
    o_dizzy.note_dizzy(100.0)
    assert o_dizzy.effective("working", 100.5, ts=100.5) == "dizzy"

    o_happy = _overlay()
    o_happy.note_celebrate(100.0)
    assert o_happy.effective("idle", 100.5, ts=100.5) == "happy"

    o_wait = _overlay("waiting", now=0.0)
    o_wait.note_raw("waiting", 0.0)
    assert o_wait.effective("waiting", 100.0, ts=100.0) == "waiting_angry"   # 100 >= shake 30

    # stall watchdog: a stale busy state falls to idle (ts far behind now).
    assert _overlay().effective("working", 1000.0, ts=700.0) == "idle"       # 300 > 240

    # sleeping: idle long enough to doze.
    o_sleep = _overlay("idle", now=0.0)
    o_sleep.note_raw("idle", 0.0)
    assert o_sleep.effective("idle", 100.0, ts=100.0) == "sleeping"          # 100 >= 60

    # blink: a brief idle blink window (idle, but not long enough to doze).
    o_blink = _overlay("idle", now=95.0)
    o_blink.note_raw("idle", 95.0)
    o_blink.note_blink(99.95)
    assert o_blink.effective("idle", 100.0, ts=100.0) == "idle_blink"        # within 0.12

    # mood-idle: a quiet idle tints the face by mood.
    o_mood = _overlay("idle", now=100.0)
    o_mood.note_raw("idle", 100.0)
    assert o_mood.effective("idle", 100.0, ts=100.0, mood="hungry") == "idle_hungry"

    # raw pass-through: a fresh busy state shows as-is.
    assert _overlay().effective("working", 100.0, ts=100.0) == "working"


def test_overlay_effective_equals_compute_for_identical_timers():
    # The overlay is a thin home over the pure core: after the same intent writes,
    # effective() agrees with compute() called directly with the equivalent timers.
    from mascot import effective_state
    o = _overlay("waiting", now=10.0)
    o.note_dizzy(50.0)          # dizzy_until = 52.0
    o.note_celebrate(40.0)      # celebrate_until = 41.5
    o.note_raw("waiting", 10.0)  # waiting_since stays 10.0
    bare = effective_state.compute(
        "waiting", 100.0, ts=100.0, dizzy_until=52.0, celebrate_until=41.5,
        waiting_since=10.0, idle_since=None, blink_until=0.0, sleep_after_idle_s=60.0,
        shake_after_s=30.0, thinking_stall_s=180.0, working_stall_s=240.0, mood="content")
    assert o.effective("waiting", 100.0, ts=100.0) == bare


def test_overlay_note_raw_clears_idle_clock_on_leaving_idle():
    # Leaving idle clears the doze clock, so a brief busy blip can't doze off later.
    o = _overlay("idle", now=0.0)
    o.note_raw("idle", 0.0)
    o.note_raw("working", 5.0)   # left idle
    o.note_raw("idle", 6.0)      # re-entered idle: clock restarts at 6.0, not 0.0
    assert o.effective("idle", 50.0, ts=50.0) == "idle"          # only 44s idle < 60
    assert o.effective("idle", 70.0, ts=70.0) == "sleeping"      # 64s >= 60


def test_overlay_is_dizzy_gates_only_while_dizzy():
    # The tap gate: petting is suppressed only while the dizzy overlay is active.
    o = _overlay()
    assert o.is_dizzy(100.0) is False
    o.note_dizzy(100.0)
    assert o.is_dizzy(101.0) is True       # within the 2.0s window
    assert o.is_dizzy(103.0) is False      # expired


def test_overlay_waiting_elapsed_tracks_unanswered_prompt():
    # The shake reads elapsed-since-waiting; None when nothing is waiting.
    o = _overlay()
    assert o.waiting_elapsed(100.0) is None
    o.note_raw("waiting", 100.0)
    assert o.waiting_elapsed(140.0) == 40.0
    o.note_raw("idle", 150.0)              # prompt answered
    assert o.waiting_elapsed(160.0) is None
