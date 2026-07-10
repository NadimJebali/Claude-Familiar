"""Tests for the versioned session-state contract (mascot/schema.py, issue #53).

The schema validator is the read-side of the state-file contract: hooks are the
sole writer, the widget (and a future VS Code extension) are readers. Same
synthetic-payload style as the pure-core tests; emit round-trips run under
tmp_path.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import emit
import state_logic

from mascot import schema


def _valid_state(**over):
    """A minimally-complete written state (post-emit shape) that must validate."""
    base = {
        "session_id": "sess1",
        "state": "idle",
        "ts": 1_000_000.0,
        "subagents": [],
        "schema_version": schema.SCHEMA_VERSION,
        "cwd": "C:\\proj",
        "model": "claude",
        "tool": None,
        "notify": None,
        "permission_mode": "",
        "stumbled": False,
        "owner_pid": 4321,
        "started": 999_999.0,
    }
    base.update(over)
    return base


# --- happy path --------------------------------------------------------------
def test_a_complete_state_validates_clean():
    assert schema.validate_session_state(_valid_state()) == []
    assert schema.is_valid_session_state(_valid_state()) is True


def test_only_the_required_keys_are_needed():
    minimal = {"session_id": "s", "state": "working", "ts": 1.0, "subagents": []}
    assert schema.validate_session_state(minimal) == []


def test_nullable_optionals_accept_none():
    assert schema.validate_session_state(
        _valid_state(tool=None, notify=None, owner_pid=None)) == []


def test_nullable_optionals_accept_their_value():
    assert schema.validate_session_state(
        _valid_state(tool="Bash", notify={"message": "hi", "type": ""},
                     owner_pid=1234)) == []


# --- required keys -----------------------------------------------------------
def test_missing_each_required_key_is_reported():
    for key in ("session_id", "state", "ts", "subagents"):
        payload = _valid_state()
        del payload[key]
        problems = schema.validate_session_state(payload)
        assert any(key in p for p in problems), f"{key} not reported: {problems}"
        assert schema.is_valid_session_state(payload) is False


def test_empty_session_id_is_rejected():
    problems = schema.validate_session_state(_valid_state(session_id=""))
    assert any("session_id" in p for p in problems)


def test_wrong_types_on_required_keys_are_reported():
    assert schema.validate_session_state(_valid_state(state=123))
    assert schema.validate_session_state(_valid_state(ts="soon"))
    assert schema.validate_session_state(_valid_state(subagents={}))
    assert schema.validate_session_state(_valid_state(session_id=5))


def test_ts_accepts_int_and_float():
    assert schema.validate_session_state(_valid_state(ts=5)) == []
    assert schema.validate_session_state(_valid_state(ts=5.5)) == []


def test_a_bool_is_not_a_valid_number():
    # bool is an int subclass; the versioning/heartbeat fields must reject it.
    assert schema.validate_session_state(_valid_state(ts=True))
    assert schema.validate_session_state(_valid_state(schema_version=True))


# --- optional keys -----------------------------------------------------------
def test_wrong_types_on_optional_keys_are_reported():
    assert schema.validate_session_state(_valid_state(stumbled="no"))
    assert schema.validate_session_state(_valid_state(notify="oops"))
    assert schema.validate_session_state(_valid_state(permission_mode=1))


# --- nested shapes a consumer navigates -------------------------------------
def test_notify_must_carry_a_string_message():
    assert schema.validate_session_state(_valid_state(notify={"message": 5}))
    assert schema.validate_session_state(_valid_state(notify={"type": "permission"}))
    assert schema.validate_session_state(
        _valid_state(notify={"message": "ok", "type": 1}))


def test_a_well_formed_notify_validates():
    assert schema.validate_session_state(
        _valid_state(notify={"message": "Claude needs you", "type": ""})) == []


def test_subagent_items_must_be_objects():
    assert schema.validate_session_state(_valid_state(subagents=[1, 2, 3]))
    assert schema.validate_session_state(
        _valid_state(subagents=[{"id": "a", "type": 9, "description": "d"}]))


def test_well_formed_subagents_validate():
    assert schema.validate_session_state(_valid_state(
        subagents=[{"id": "a1", "type": "reviewer", "description": "check"},
                   {"id": None, "type": "agent", "description": ""}])) == []


# --- forward / backward compatibility ---------------------------------------
def test_unknown_extra_fields_are_tolerated():
    assert schema.validate_session_state(
        _valid_state(some_future_field=42, another={"nested": True})) == []


def test_missing_schema_version_is_tolerated_as_legacy():
    legacy = _valid_state()
    del legacy["schema_version"]
    assert schema.validate_session_state(legacy) == []


def test_a_future_schema_version_is_not_rejected():
    assert schema.validate_session_state(
        _valid_state(schema_version=schema.SCHEMA_VERSION + 5)) == []


# --- non-dict payloads -------------------------------------------------------
def test_non_object_payloads_are_invalid_without_crashing():
    for bad in (None, [], "x", 7):
        problems = schema.validate_session_state(bad)
        assert problems  # exactly one structural complaint
        assert schema.is_valid_session_state(bad) is False


def test_transcript_path_is_an_optional_string_field():
    # #71: the optional transcript_path (non-breaking addition, like effort).
    assert schema.is_valid_session_state(
        _valid_state(transcript_path="C:/t/sess.jsonl"))
    assert schema.is_valid_session_state(_valid_state())          # absent is fine
    problems = schema.validate_session_state(_valid_state(transcript_path=7))
    assert problems and "transcript_path" in problems[0]


def test_file_is_an_optional_string_field():
    # #85: the sticky-per-turn working file (non-breaking, like transcript_path).
    assert schema.is_valid_session_state(_valid_state(file="C:/repo/a.py"))
    assert schema.is_valid_session_state(_valid_state())          # absent is fine
    problems = schema.validate_session_state(_valid_state(file=7))
    assert problems and "file" in problems[0]


# --- the writer and reader agree --------------------------------------------
def test_writer_and_reader_schema_versions_match():
    assert schema.SCHEMA_VERSION == state_logic.SCHEMA_VERSION


def test_writer_emits_no_field_the_schema_does_not_know(tmp_path):
    # Mirror of the state-enum guard, for the field SET: every key the writer can
    # stamp must be covered by the validator's maps (and so the doc), so adding a
    # field to the writer can't silently escape the contract.
    known = set(schema._REQUIRED) | set(schema._OPTIONAL)
    seen: set[str] = set()
    events = [
        ("SessionStart", {}),
        ("UserPromptSubmit", {"cwd": "/w", "model": "m", "permission_mode": "plan",
                              "transcript_path": "/t/s.jsonl"}),
        ("PreToolUse", {"tool_name": "Bash"}),
        ("PreToolUse", {"tool_name": "Agent", "tool_use_id": "a1",
                        "tool_input": {"subagent_type": "x", "description": "d"}}),
        ("Notification", {"message": "need you"}),
        ("StopFailure", {"error_type": "overloaded"}),
    ]
    for event, payload in events:
        state = emit.update_state(tmp_path, event,
                                  {"session_id": "s", **payload}, now=1.0)
        seen |= set(state)
    assert seen <= known, f"writer emits unknown keys: {seen - known}"


def test_every_state_the_writer_emits_is_a_known_state():
    seen = {state_logic.default_state("s")["state"]}
    events = [
        ("SessionStart", {}),
        ("UserPromptSubmit", {}),
        ("PreToolUse", {"tool_name": "Bash"}),
        ("PostToolUse", {"tool_name": "Bash"}),
        ("PreCompact", {}),
        ("Notification", {"message": "Claude needs permission to use Bash"}),
        ("Notification", {"message": "usage limit reached"}),
        ("Stop", {}),
        ("StopFailure", {"error_type": "rate_limit"}),
        ("StopFailure", {"error_type": "overloaded"}),
    ]
    for event, payload in events:
        nxt = state_logic.compute_next_state(state_logic.default_state("s"),
                                             event, {"session_id": "s", **payload})
        seen.add(nxt["state"])
    assert seen <= schema.KNOWN_STATES, f"unknown states emitted: {seen - schema.KNOWN_STATES}"


# --- the emitter stamps the version, and its output validates ---------------
def test_emit_stamps_schema_version_and_output_validates(tmp_path):
    state = emit.update_state(tmp_path, "UserPromptSubmit",
                              {"session_id": "s1", "cwd": "/w"}, now=1_000.0)
    assert state["schema_version"] == schema.SCHEMA_VERSION
    assert schema.is_valid_session_state(state)


def test_emitted_file_on_disk_validates(tmp_path):
    emit.update_state(tmp_path, "PreToolUse",
                      {"session_id": "s2", "tool_name": "Read"}, now=1_000.0)
    written = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert schema.is_valid_session_state(written)


def test_emit_upgrades_a_legacy_file_missing_the_version(tmp_path):
    # A pre-existing state file written before versioning: no schema_version.
    path = tmp_path / "s3.json"
    path.write_text(json.dumps(
        {"session_id": "s3", "state": "idle", "subagents": [], "ts": 1.0}),
        encoding="utf-8")
    state = emit.update_state(tmp_path, "Stop", {"session_id": "s3"}, now=2_000.0)
    assert state["schema_version"] == schema.SCHEMA_VERSION
