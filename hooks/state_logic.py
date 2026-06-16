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

AGENT_TOOL = "Agent"

# Claude Code fires a Notification both for real permission/attention prompts
# ("Claude needs your permission to use Bash") AND as a plain idle reminder
# ("Claude is waiting for your input") after ~60s of inactivity. The idle nudge
# is not a request for the user, so it must not wake a dozing mascot into the
# attention-grabbing "waiting" state.
_IDLE_NOTIFICATION_HINTS = ("waiting for your input",)


def _is_idle_reminder(message: str) -> bool:
    """True for the periodic "Claude is waiting for your input" idle nudge."""
    msg = (message or "").lower()
    return any(hint in msg for hint in _IDLE_NOTIFICATION_HINTS)


# Claude Code fires a Notification when usage is exhausted (e.g. "Claude usage
# limit reached · your limit will reset at 3pm"). That puts the session out of
# commission, so the mascot becomes a gravestone ("dead") and keeps the bubble
# so the user can read the reset time. Note: a transient "rate limit" (429
# backoff) is recoverable and intentionally NOT matched here — only exhaustion
# that ends the session should tombstone the mascot.
_USAGE_LIMIT_HINTS = (
    "usage limit",
    "limit reached",
    "limit will reset",
    "reached your usage",
)


def _is_usage_limit(message: str) -> bool:
    """True when the notification reports an exhausted usage limit."""
    msg = (message or "").lower()
    return any(hint in msg for hint in _USAGE_LIMIT_HINTS)


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
        message = payload.get("message", "")
        if _is_usage_limit(message):
            # Out of usage — the session is done; show a gravestone and keep the
            # bubble so the reset-time message stays visible.
            nxt["state"] = "dead"
            nxt["notify"] = {
                "message": message,
                "type": payload.get("notification_type", ""),
            }
        elif _is_idle_reminder(message):
            # Just an idle nudge — leave the mascot as-is (dozing), no bubble.
            nxt["state"] = "idle"
            nxt["notify"] = None
        else:
            nxt["state"] = "waiting"
            nxt["notify"] = {
                "message": message,
                "type": payload.get("notification_type", ""),
            }

    elif event == "Stop":
        nxt["state"] = "idle"
        nxt["tool"] = None
        nxt["subagents"] = []

    # SubagentStop: intentionally a no-op (noisy; see module docstring).
    # SessionEnd: handled by emit.py (file deletion), not here.

    return nxt
