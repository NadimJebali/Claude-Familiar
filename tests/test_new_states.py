"""Tests for the new-state additions to the pure state machine (feat/mascot-states):
permission_mode capture (planning face), the stumble flag, and PreCompact.
Same synthetic-payload style as tests/test_phase1.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
from state_logic import compute_next_state, default_state


def _state(**over):
    base = default_state("sess1", cwd="C:\\proj")
    base.update(over)
    return base


# --- permission_mode capture (drives the planning face) ---------------------
def test_permission_mode_is_captured_when_present():
    nxt = compute_next_state(_state(), "UserPromptSubmit",
                             {"session_id": "sess1", "permission_mode": "plan"})
    assert nxt["permission_mode"] == "plan"
    assert nxt["state"] == "thinking"


def test_permission_mode_persists_when_payload_omits_it():
    current = _state(permission_mode="plan")
    nxt = compute_next_state(current, "PreToolUse",
                             {"session_id": "sess1", "tool_name": "Read"})
    assert nxt["permission_mode"] == "plan"


def test_permission_mode_updates_when_it_changes():
    current = _state(permission_mode="plan")
    nxt = compute_next_state(current, "UserPromptSubmit",
                             {"session_id": "sess1", "permission_mode": "default"})
    assert nxt["permission_mode"] == "default"


def test_default_state_has_empty_permission_mode():
    assert default_state("s")["permission_mode"] == ""


# --- the stumble marker (non-fatal StopFailure) ------------------------------
def test_nonfatal_stopfailure_sets_stumbled_and_settles_idle():
    current = _state(state="working", tool="Bash")
    nxt = compute_next_state(current, "StopFailure",
                             {"session_id": "sess1", "error_type": "server_error"})
    assert nxt["state"] == "idle"
    assert nxt["stumbled"] is True
    assert nxt["tool"] is None


def test_death_stopfailure_tombstones_without_stumble():
    nxt = compute_next_state(_state(state="thinking"), "StopFailure",
                             {"session_id": "sess1", "error_type": "billing_error"})
    assert nxt["state"] == "dead"
    assert nxt["stumbled"] is False


def test_usage_and_session_limit_error_types_tombstone():
    # Kept in sync with notifier._LIMIT_TYPES — a limit death must tombstone,
    # never settle quietly to idle (the gravestone-never-appears report).
    for error_type in ("usage_limit", "session_limit", "rate_limit"):
        nxt = compute_next_state(_state(state="thinking"), "StopFailure",
                                 {"session_id": "sess1", "error_type": error_type})
        assert nxt["state"] == "dead", error_type
        assert nxt["notify"]["message"] == "Out of usage"


def test_stumbled_clears_on_the_next_forward_event():
    stumbled = _state(state="idle", stumbled=True)
    nxt = compute_next_state(stumbled, "UserPromptSubmit", {"session_id": "sess1"})
    assert nxt["stumbled"] is False
    assert nxt["state"] == "thinking"


def test_subagent_stop_preserves_the_stumble_marker():
    stumbled = _state(state="idle", stumbled=True)
    nxt = compute_next_state(stumbled, "SubagentStop", {"session_id": "sess1"})
    assert nxt["stumbled"] is True


# --- AskUserQuestion -> waiting (#52: how "needs you" surfaces in VS Code) ---
def test_ask_user_question_tool_makes_the_mascot_wait():
    # In the VS Code extension a "needs you" arrives as the AskUserQuestion tool
    # call, not a Notification hook. Its PreToolUse must shake for attention
    # (waiting) and show the question — not display a working face.
    nxt = compute_next_state(_state(state="thinking"), "PreToolUse", {
        "session_id": "sess1",
        "tool_name": "AskUserQuestion",
        "tool_input": {"questions": [{"question": "Which database?", "header": "DB"}]},
    })
    assert nxt["state"] == "waiting"
    assert nxt["tool"] is None
    assert nxt["notify"]["message"] == "Which database?"


def test_ask_user_question_falls_back_to_a_generic_prompt():
    nxt = compute_next_state(_state(), "PreToolUse",
                             {"session_id": "sess1", "tool_name": "AskUserQuestion"})
    assert nxt["state"] == "waiting"
    assert nxt["notify"]["message"]  # some non-empty prompt for the bubble/toast


def test_answering_the_question_resumes_and_clears_the_bubble():
    waiting = _state(state="waiting",
                     notify={"message": "Which database?", "type": "question"})
    nxt = compute_next_state(waiting, "PostToolUse",
                             {"session_id": "sess1", "tool_name": "AskUserQuestion"})
    assert nxt["state"] == "working"
    assert nxt["notify"] is None


def test_ask_user_question_inside_a_subagent_does_not_hijack_the_card():
    # A nested call carries a top-level agent_id — it isn't the visible session
    # asking the user, so it must not flip the whole card to waiting.
    nxt = compute_next_state(_state(state="working", tool="Bash"), "PreToolUse",
                             {"session_id": "sess1", "tool_name": "AskUserQuestion",
                              "agent_id": "a1"})
    assert nxt["state"] == "working"


def test_a_normal_tool_still_shows_working():
    # Non-regression: only AskUserQuestion is special-cased.
    nxt = compute_next_state(_state(), "PreToolUse",
                             {"session_id": "sess1", "tool_name": "Read"})
    assert nxt["state"] == "working"
    assert nxt["tool"] == "Read"


# --- PreCompact -> compacting ------------------------------------------------
def test_precompact_enters_compacting_and_clears_the_tool():
    working = _state(state="working", tool="Edit",
                     subagents=[{"id": "t1", "type": "reviewer", "description": ""}])
    nxt = compute_next_state(working, "PreCompact", {"session_id": "sess1"})
    assert nxt["state"] == "compacting"
    assert nxt["tool"] is None
    # Compaction happens mid-turn: the sub-agent badges survive it.
    assert nxt["subagents"] == working["subagents"]


def test_compacting_is_left_by_the_next_forward_event():
    compacting = _state(state="compacting")
    nxt = compute_next_state(compacting, "PreToolUse",
                             {"session_id": "sess1", "tool_name": "Bash"})
    assert nxt["state"] == "working"
    assert nxt["tool"] == "Bash"


def test_compacting_watchdog_falls_back_to_idle_when_stale():
    from mascot import effective_state as es

    kwargs = {"ts": 1000.0, "dizzy_until": 0.0, "celebrate_until": 0.0,
              "waiting_since": None, "idle_since": None, "blink_until": 0.0,
              "sleep_after_idle_s": 90.0, "shake_after_s": 30.0,
              "thinking_stall_s": 180.0, "working_stall_s": 270.0}
    # Fresh compaction: displayed as-is. Stale past the thinking grace: idle.
    assert es.compute("compacting", 1010.0, **kwargs) == "compacting"
    assert es.compute("compacting", 1000.0 + 181.0, **kwargs) == "idle"
