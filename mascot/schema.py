"""Versioned contract for the per-session state files.

Hooks (``hooks/emit.py`` + ``hooks/state_logic.py``) are the **sole writer** of
these files; the widget — and any future second consumer, e.g. a VS Code
extension — are **readers**. This module is the read-side of that contract:
``SCHEMA_VERSION`` is the format version this build understands, and
``validate_session_state`` reports whether a decoded payload conforms.

Pure and stdlib-only, so the validator is trivially unit-testable and adds no
weight to the hook path. The human-readable specification consumers rely on
lives in ``docs/state-file-schema.md``; keep the two in sync.

Validation is deliberately **structural, not semantic**: it checks that the keys
a reader depends on are present and well-typed, tolerates unknown keys (a newer
writer may add fields), and treats a missing ``schema_version`` as a legacy file
rather than an error. It never inspects liveness or state *meaning* — the
renderer already degrades gracefully on an unknown ``state`` value.
"""
from __future__ import annotations

from typing import Any

# The state-file format version this build reads. It must match the writer's
# stamp in ``hooks/state_logic.SCHEMA_VERSION`` — a test asserts they agree, so
# the two can never drift silently within a release.
SCHEMA_VERSION = 1

# The raw states the hook writer can stamp into a file. Display-only overlays
# (happy, dizzy, sleeping, waiting_angry, blink) are computed by the widget and
# never written here, so they are intentionally absent. A reader seeing a state
# outside this set must NOT reject the file — a newer writer may add one — but
# the set lets a consumer branch on the states it knows.
KNOWN_STATES = frozenset(
    {"idle", "thinking", "working", "waiting", "compacting", "dead"}
)

# key -> the type(s) it must have. ``type(None)`` marks a nullable field. Numbers
# accept int or float; bool is rejected wherever it is not explicitly listed
# (see ``_matches``), so the version/heartbeat fields can't be a stray boolean.
_REQUIRED: dict[str, tuple[type, ...]] = {
    "session_id": (str,),
    "state": (str,),
    "ts": (int, float),
    "subagents": (list,),
}
_OPTIONAL: dict[str, tuple[type, ...]] = {
    "schema_version": (int,),
    "cwd": (str,),
    "model": (str,),
    "effort": (str,),
    "transcript_path": (str,),
    "tool": (str, type(None)),
    "notify": (dict, type(None)),
    "permission_mode": (str,),
    "stumbled": (bool,),
    "owner_pid": (int, type(None)),
    "started": (int, float),
}


# Inner shapes a consumer reads off the top-level objects. Validated one level
# deep (still structural, not semantic) so a "valid" verdict actually guarantees
# `notify.message` and `subagents[i]["id"]` are the types the doc promises.
_NOTIFY_FIELDS: dict[str, tuple[type, ...]] = {"message": (str,), "type": (str,)}
_SUBAGENT_FIELDS: dict[str, tuple[type, ...]] = {
    "id": (str, type(None)),
    "type": (str,),
    "description": (str,),
}


def _matches(value: Any, allowed: tuple[type, ...]) -> bool:
    """Type check that treats ``bool`` distinctly from ``int``.

    ``isinstance(True, int)`` is True in Python, which would let a boolean pass
    for a numeric field. Accept a bool only where ``bool`` is explicitly allowed.
    """
    if isinstance(value, bool):
        return bool in allowed
    return isinstance(value, allowed)


def _names(allowed: tuple[type, ...]) -> str:
    return " or ".join(t.__name__ for t in allowed)


def _fields(prefix: str, obj: dict[str, Any], spec: dict[str, tuple[type, ...]],
            *, required: tuple[str, ...] = ()) -> list[str]:
    """Type-check named fields of a nested object; tolerate unknown ones."""
    problems: list[str] = []
    for key in required:
        if key not in obj:
            problems.append(f"{prefix} is missing required key {key!r}")
    for key, allowed in spec.items():
        if key in obj and not _matches(obj[key], allowed):
            problems.append(
                f"{prefix}.{key} must be {_names(allowed)}, "
                f"got {type(obj[key]).__name__}"
            )
    return problems


def validate_session_state(payload: Any) -> list[str]:
    """Return a list of problems with ``payload`` (an empty list means valid).

    Reports missing required keys, keys of the wrong type, and an empty
    ``session_id``. Unknown keys and a missing ``schema_version`` are tolerated.
    Never raises: a non-object payload yields a single structural complaint.
    """
    if not isinstance(payload, dict):
        return [f"payload must be a JSON object, got {type(payload).__name__}"]

    problems: list[str] = []
    for key, allowed in _REQUIRED.items():
        if key not in payload:
            problems.append(f"missing required key {key!r}")
        elif not _matches(payload[key], allowed):
            problems.append(
                f"key {key!r} must be {_names(allowed)}, "
                f"got {type(payload[key]).__name__}"
            )
    if isinstance(payload.get("session_id"), str) and not payload["session_id"]:
        problems.append("key 'session_id' must be a non-empty string")

    for key, allowed in _OPTIONAL.items():
        if key in payload and not _matches(payload[key], allowed):
            problems.append(
                f"key {key!r} must be {_names(allowed)}, "
                f"got {type(payload[key]).__name__}"
            )

    # One level deeper into the objects a consumer navigates. Only when the outer
    # type already checked out, so a wrong-typed `notify`/`subagents` isn't
    # reported twice.
    notify = payload.get("notify")
    if isinstance(notify, dict):
        problems += _fields("notify", notify, _NOTIFY_FIELDS, required=("message",))
    subagents = payload.get("subagents")
    if isinstance(subagents, list):
        for i, item in enumerate(subagents):
            if not isinstance(item, dict):
                problems.append(
                    f"subagents[{i}] must be object, got {type(item).__name__}")
            else:
                problems += _fields(f"subagents[{i}]", item, _SUBAGENT_FIELDS)
    return problems


def is_valid_session_state(payload: Any) -> bool:
    """True when ``payload`` conforms to the session-state contract."""
    return not validate_session_state(payload)
