"""Pure state-transition logic for the mascot.

`compute_next_state(current, event, payload)` returns a NEW state dict (never
mutates `current`) describing the mascot for one Claude session. It is kept free
of I/O and clocks so it can be unit-tested deterministically — emit.py is the
only thing that touches the filesystem and stamps `ts`.

Verified against real Phase 0 hook payloads (see docs/PLAN.md):
- The sub-agent tool is named "Agent" (not "Task").
- A real spawn is a top-level PreToolUse(Agent) with NO top-level `agent_id`.
- SubagentStop is noisy (internal agents), so it is a no-op here.
"""
from __future__ import annotations

from typing import Any

VALID_STATES = {"idle", "thinking", "working", "waiting", "sleeping"}
AGENT_TOOL = "Agent"


def default_state(session_id: str, cwd: str = "", model: str = "") -> dict[str, Any]:
    """A fresh mascot state for a session."""
    return {
        "session_id": session_id,
        "cwd": cwd,
        "model": model,
        "state": "idle",
        "tool": None,
        "subagents": [],  # list of {"id", "type", "description"}
        "notify": None,   # {"message", "type"} while Claude needs the user (e.g. permission)
    }


def _is_top_level_agent_spawn(payload: dict[str, Any]) -> bool:
    """True when this PreToolUse is the main thread spawning a sub-agent
    (not a tool running inside one). Nested calls carry a top-level agent_id."""
    return payload.get("tool_name") == AGENT_TOOL and not payload.get("agent_id")


def compute_next_state(
    current: dict[str, Any], event: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Return the next state. `current` is never mutated."""
    nxt = dict(current)
    nxt["subagents"] = list(current.get("subagents", []))  # copy for immutability

    # The notification bubble is transient: it appears on a Notification event and
    # is cleared by the next event that moves the session forward (prompt, tool,
    # stop, ...). SubagentStop is a no-op and preserves it.
    if event != "SubagentStop":
        nxt["notify"] = None

    # Keep identity/context fresh from whatever the payload carries.
    if payload.get("session_id"):
        nxt["session_id"] = payload["session_id"]
    if payload.get("cwd"):
        nxt["cwd"] = payload["cwd"]
    if payload.get("model"):
        nxt["model"] = payload["model"]

    if event == "SessionStart":
        nxt["state"] = "idle"
        nxt["tool"] = None
        nxt["subagents"] = []

    elif event == "UserPromptSubmit":
        nxt["state"] = "thinking"
        nxt["tool"] = None

    elif event == "PreToolUse":
        nxt["state"] = "working"
        tool_input = payload.get("tool_input") or {}
        if _is_top_level_agent_spawn(payload):
            nxt["subagents"].append(
                {
                    "id": payload.get("tool_use_id"),
                    "type": tool_input.get("subagent_type") or "agent",
                    "description": tool_input.get("description", ""),
                }
            )
        else:
            nxt["tool"] = payload.get("tool_name")

    elif event == "PostToolUse":
        if payload.get("tool_name") == AGENT_TOOL:
            tool_use_id = payload.get("tool_use_id")
            nxt["subagents"] = [
                s for s in nxt["subagents"] if s.get("id") != tool_use_id
            ]
        nxt["state"] = "working"

    elif event == "Notification":
        nxt["state"] = "waiting"
        nxt["notify"] = {
            "message": payload.get("message", ""),
            "type": payload.get("notification_type", ""),
        }

    elif event == "Stop":
        nxt["state"] = "idle"
        nxt["tool"] = None
        nxt["subagents"] = []

    # SubagentStop: intentionally a no-op (noisy; see module docstring).
    # SessionEnd: handled by emit.py (file deletion), not here.

    return nxt
