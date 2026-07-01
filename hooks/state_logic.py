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
#
# The nudge is recognized by its notification type (which carries "idle", e.g.
# "idle_prompt") OR, when the payload omits a type, by the message text. Matching
# the type matters: the nudge often arrives with an empty message, and without the
# type check it fell through to "waiting" and left the mascot stuck shaking
# "needs you!" long after the user had already answered. A real permission prompt
# is typed "permission" (never "idle"), so it is unaffected.
_IDLE_NOTIFICATION_HINTS = ("waiting for your input",)


def _is_idle_reminder(payload: dict[str, Any]) -> bool:
    """True for the periodic idle nudge, matched by notification type or message."""
    ntype = (payload.get("notification_type") or payload.get("subtype") or "").lower()
    if "idle" in ntype:
        return True
    msg = (payload.get("message") or "").lower()
    return any(hint in msg for hint in _IDLE_NOTIFICATION_HINTS)


# Claude Code fires a Notification when usage is exhausted (e.g. "Claude usage
# limit reached · your limit will reset at 3pm", or "You have hit your session
# limit"). That puts the session out of commission, so the mascot becomes a
# gravestone ("dead") and keeps the bubble so the user can read the reset time.
# Note: a transient "rate limit" (429 backoff) is recoverable and intentionally
# NOT matched here — only exhaustion that ends the session should tombstone the
# mascot.
_USAGE_LIMIT_HINTS = (
    "usage limit",
    "session limit",
    "limit reached",
    "limit will reset",
    "reached your usage",
)


def _is_usage_limit(message: str) -> bool:
    """True when the notification reports an exhausted usage limit."""
    msg = (message or "").lower()
    return any(hint in msg for hint in _USAGE_LIMIT_HINTS)


# Claude Code is inconsistent about where the human-readable text lands (and which
# event carries it), so limit detection scans every plausible string field rather
# than just `message`. Verified payloads only ever had `message`/`notification_type`;
# the rest are defensive so a session-limit notice is caught wherever it shows up.
_TEXT_FIELDS = ("message", "reason", "title", "body", "notification_type", "subtype")


def _payload_text(payload: dict[str, Any]) -> str:
    """Joined, lowercased text from a payload's human-readable fields."""
    parts = [payload[k] for k in _TEXT_FIELDS if isinstance(payload.get(k), str)]
    return " ".join(parts).lower()


# StopFailure (fires when a turn ends on an API error) carries a structured
# `error_type` enum. These values mean the session can't continue -> gravestone;
# every other value (overloaded, server_error, model_not_found, invalid_request,
# max_output_tokens, unknown) is a transient/odd turn-death -> settle to idle.
# StopFailure carries no human text, so the death bubble uses a short fixed label
# (the "resets at <time>" detail still rides on a Notification/Stop, when one fires).
_DEATH_ERROR_TYPES = frozenset(
    {"rate_limit", "billing_error", "authentication_failed", "oauth_org_not_allowed"}
)
_DEATH_MESSAGES = {
    "rate_limit": "Out of usage",
    "billing_error": "Billing problem",
    "authentication_failed": "Auth failed",
    "oauth_org_not_allowed": "Org not allowed",
}


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
        "permission_mode": "",  # e.g. "plan" — drives the planning face while set
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
    if payload.get("permission_mode"):
        nxt["permission_mode"] = payload["permission_mode"]

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
            nxt["tool"] = None  # the sub-agent shows as its own badge, not the caption
            nxt["subagents"].append(
                {
                    "id": payload.get("tool_use_id"),
                    "type": tool_input.get("subagent_type") or "agent",
                    "description": tool_input.get("description", ""),
                }
            )
        elif not payload.get("agent_id"):
            # A main-thread tool: surface it in the caption. A tool running INSIDE a
            # sub-agent carries a top-level agent_id and isn't part of the visible
            # session, so it doesn't touch the caption.
            nxt["tool"] = payload.get("tool_name")

    elif event == "PostToolUse":
        if payload.get("tool_name") == AGENT_TOOL:
            tool_use_id = payload.get("tool_use_id")
            nxt["subagents"] = [
                s for s in nxt["subagents"] if s.get("id") != tool_use_id
            ]
        # A main-thread tool just finished; clear the caption tool (Claude is now
        # reasoning between tools). Nested sub-agent completions carry an agent_id
        # and leave the visible caption alone.
        if not payload.get("agent_id"):
            nxt["tool"] = None
        nxt["state"] = "working"

    elif event == "Notification":
        message = payload.get("message", "")
        if _is_usage_limit(_payload_text(payload)):
            # Out of usage — the session is done; show a gravestone and keep the
            # bubble so the reset-time message stays visible.
            nxt["state"] = "dead"
            nxt["notify"] = {
                "message": message,
                "type": payload.get("notification_type", ""),
            }
        elif _is_idle_reminder(payload):
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
        nxt["tool"] = None
        nxt["subagents"] = []
        # A turn can end on a usage/session limit. If the limit text rides on the
        # Stop payload, tombstone instead of going calmly idle.
        if _is_usage_limit(_payload_text(payload)):
            nxt["state"] = "dead"
            nxt["notify"] = {
                "message": payload.get("message") or payload.get("reason")
                           or "Session limit reached",
                "type": payload.get("notification_type", ""),
            }
        else:
            nxt["state"] = "idle"

    elif event == "StopFailure":
        # The structured terminating hook for an API-error turn death. error_type
        # is an enum; a usage/rate limit tombstones the mascot. The turn ended, so
        # clear the active tool + sub-agent badges (mirrors Stop).
        nxt["tool"] = None
        nxt["subagents"] = []
        error_type = payload.get("error_type", "")
        if error_type in _DEATH_ERROR_TYPES:
            nxt["state"] = "dead"
            nxt["notify"] = {
                "message": _DEATH_MESSAGES.get(error_type, "Session ended"),
                "type": error_type,
            }
        else:
            # Transient/odd API error: the turn ended, so settle to idle.
            nxt["state"] = "idle"

    # SubagentStop: intentionally a no-op (noisy; see module docstring).
    # SessionEnd: handled by emit.py (file deletion), not here.

    return nxt
