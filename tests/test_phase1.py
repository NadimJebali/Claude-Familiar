"""Phase 1 tests: pure state logic + emit file I/O.

Payloads mirror the real Phase 0 captures (docs/PLAN.md).
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

from state_logic import compute_next_state, default_state  # noqa: E402
import emit  # noqa: E402

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


def test_notification_sets_waiting():
    payload = {"session_id": SID, "notification_type": "idle_prompt"}
    out = compute_next_state(base(), "Notification", payload)
    assert out["state"] == "waiting"


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
