"""Phase 1 tests: pure state logic + emit file I/O.

Payloads mirror the real Phase 0 captures (docs/PLAN.md).
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from state_logic import compute_next_state, default_state  # noqa: E402
import emit  # noqa: E402
from mascot import popup_place  # noqa: E402
from mascot import effective_state  # noqa: E402

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
    dead = compute_next_state(base(), "StopFailure", {"session_id": SID, "error_type": "rate_limit"})
    assert dead["state"] == "dead"
    revived = compute_next_state(dead, "UserPromptSubmit", {"session_id": SID})
    assert revived["state"] == "thinking"
    assert revived["notify"] is None


def test_installer_includes_stopfailure_event():
    # The widget can't receive StopFailure unless the installer wires the hook.
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import install_hooks  # noqa: PLC0415
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


def test_compute_next_state_does_not_mutate_input():
    start = base()
    start["subagents"] = [{"id": "x", "type": "agent", "description": ""}]
    snapshot = json.dumps(start, sort_keys=True)
    compute_next_state(start, "PreToolUse",
                       {"session_id": SID, "tool_name": "Agent",
                        "tool_input": {}, "tool_use_id": "y"})
    assert json.dumps(start, sort_keys=True) == snapshot


# --- session stat counters ------------------------------------------------

def test_default_state_starts_counters_at_zero():
    s = default_state(SID)
    assert s["prompts"] == 0
    assert s["tools_run"] == 0
    assert s["subagents_spawned"] == 0


def test_prompt_submit_increments_prompt_count():
    out = compute_next_state(base(), "UserPromptSubmit", {"session_id": SID})
    assert out["prompts"] == 1


def test_regular_tool_increments_tools_run_only():
    payload = {"session_id": SID, "tool_name": "Bash", "tool_input": {}}
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["tools_run"] == 1
    assert out["subagents_spawned"] == 0


def test_agent_spawn_increments_subagents_spawned_only():
    payload = {"session_id": SID, "tool_name": "Agent", "tool_input": {}, "tool_use_id": "t1"}
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["subagents_spawned"] == 1
    assert out["tools_run"] == 0


def test_nested_tool_does_not_inflate_tools_run():
    # A tool running inside a sub-agent (top-level agent_id) is not the visible
    # session's work, so it must not bump the main-thread tool counter.
    payload = {"session_id": SID, "tool_name": "Read", "agent_id": "a1", "tool_input": {}}
    out = compute_next_state(base(), "PreToolUse", payload)
    assert out["tools_run"] == 0


def test_counters_accumulate_across_events():
    s = base()
    s = compute_next_state(s, "UserPromptSubmit", {"session_id": SID})
    s = compute_next_state(s, "PreToolUse", {"session_id": SID, "tool_name": "Bash", "tool_input": {}})
    s = compute_next_state(s, "PreToolUse", {"session_id": SID, "tool_name": "Read", "tool_input": {}})
    assert (s["prompts"], s["tools_run"], s["subagents_spawned"]) == (1, 2, 0)


def test_counters_upgrade_old_state_without_keys():
    # State files written before this feature lack the counter keys; the next
    # event must seed them via .get(default) rather than KeyError.
    legacy = {"session_id": SID, "state": "idle", "subagents": []}
    out = compute_next_state(legacy, "UserPromptSubmit", {"session_id": SID})
    assert out["prompts"] == 1


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


# --- cross-platform support (Linux port) ----------------------------------

def test_parse_proc_stat_handles_comm_with_spaces_and_parens():
    import proc as hooks_proc  # noqa: PLC0415  (hooks dir already on sys.path)
    # Real /proc/<pid>/stat: comm is parenthesized and may contain ')' and spaces.
    line = "4242 (claude) S 4200 4242 4200 0 -1 4194304 100 0"
    assert hooks_proc._parse_stat(line) == (4200, "claude")
    weird = "10 (weird ) name) S 7 10 7 0 -1 0 0"
    assert hooks_proc._parse_stat(weird) == (7, "weird ) name")


def test_linux_owner_matcher_accepts_claude_comm():
    import proc as hooks_proc  # noqa: PLC0415
    assert hooks_proc._is_owner_linux("claude")
    assert hooks_proc._is_owner_linux("claude-code")
    assert not hooks_proc._is_owner_linux("bash")


def test_pid_alive_true_for_self_and_safe_on_unknown():
    import os
    from mascot import proc as mascot_proc
    assert mascot_proc.pid_alive(os.getpid()) is True
    assert mascot_proc.pid_alive(None) is True          # unknown owner -> keep
    assert mascot_proc.pid_alive("not-an-int") is True  # unparseable -> keep


def test_png_icon_has_valid_signature_and_chunks():
    from mascot import icon
    data = icon._png_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IHDR" in data[:30] and data[-8:-4] == b"IEND"


# --- configurable attention shake -----------------------------------------

def test_settings_defaults_include_shake_controls():
    from mascot import settings as settings_mod
    assert "shake_after_s" in settings_mod.DEFAULTS
    assert "shake_max_amp_px" in settings_mod.DEFAULTS


def test_config_clamp_handles_bounds_and_bad_values():
    from mascot import config
    assert config._clamp("nope", 5, 120, 30) == 30   # unparseable -> default
    assert config._clamp(None, 5, 120, 30) == 30     # missing -> default
    assert config._clamp(1000, 5, 120, 30) == 120    # above max -> clamped
    assert config._clamp(1, 5, 120, 30) == 5         # below min -> clamped
    assert config._clamp(42, 5, 120, 30) == 42       # in range -> kept


def test_desktop_entry_contains_required_keys():
    from mascot import desktop_entry
    text = desktop_entry.build("Claude Familiar", '"/usr/bin/python3" -m mascot.control_panel',
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
    x, y = popup_place.beside(800, 500, 158, 196, 120, 40, _PRIMARY, gap=6)
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
    kw = dict(ts=now, dizzy_until=0.0, celebrate_until=0.0, waiting_since=None,
              idle_since=None, blink_until=0.0, sleep_after_idle_s=60.0,
              shake_after_s=30.0, thinking_stall_s=180.0, working_stall_s=240.0)
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


def test_effective_stalled_busy_never_sleeps_with_idle_since():
    # Footgun guard: a stalled busy state must resolve to idle and NEVER sleeping,
    # even if an idle_since timer happens to be set. The watchdog early-returns idle
    # rather than rewriting raw and falling through into the idle->sleeping overlay.
    assert _eff("working", now=1000.0, ts=700.0, working_stall_s=240.0,
                idle_since=800.0, sleep_after_idle_s=60.0) == "idle"
    assert _eff("thinking", now=1000.0, ts=700.0, thinking_stall_s=180.0,
                idle_since=800.0, sleep_after_idle_s=60.0) == "idle"
