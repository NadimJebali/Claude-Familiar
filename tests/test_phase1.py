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
