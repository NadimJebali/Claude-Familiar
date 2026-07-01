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
