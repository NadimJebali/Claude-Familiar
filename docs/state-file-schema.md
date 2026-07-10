# Session state-file schema

This document specifies the per-session JSON files the mascot writes, so a second
consumer (e.g. a VS Code extension) can rely on them as a **public contract**
without reverse-engineering the widget.

- **Location:** `~/.claude/mascot/state/<session_id>.json` — one file per live
  Claude Code session. The stem is the `session_id` with any character outside
  `[A-Za-z0-9._-]` replaced by `_`.
- **Sole writer:** the hooks (`hooks/emit.py`, driven by `hooks/state_logic.py`).
  Claude Code invokes `emit.py` on each lifecycle event; it applies the event and
  rewrites the file with an atomic temp-then-`os.replace`. **No other process
  writes these files** — the widget is display-only. (The pet lives in a separate
  file, `~/.claude/mascot/pet.json`, and is not covered here.)
- **Deletion:** the `SessionEnd` hook deletes the file. A widget also stops
  showing a session once its `owner_pid` is confirmed dead (see below).

## Version marker

Every file carries `schema_version` (integer), the version of the format the
writer produced. The current version is **1**.

- A reader declares the version it understands (`mascot/schema.SCHEMA_VERSION`).
- **Missing `schema_version`** means a legacy file written before versioning;
  treat it as version 0 and read it leniently rather than rejecting it.
- The version is bumped only on a **breaking** change to the shape. Adding a new
  optional field is **not** breaking, so readers must tolerate unknown keys and
  must not assume the newest version.

## Fields

| Key | Type | Req | Meaning |
|-----|------|-----|---------|
| `session_id` | string (non-empty) | ✓ | Claude Code session id; matches the file stem. |
| `state` | string | ✓ | Raw mascot state (enum below). Tolerate unknown values. |
| `ts` | number | ✓ | Heartbeat: Unix epoch seconds of the last hook event. Ticks **only** on events, so an idle-but-live session still goes stale — staleness is a backstop, not proof of death. |
| `subagents` | array | ✓ | Active sub-agent badges; each item `{id, type, description}`. Empty when none. |
| `schema_version` | integer | – | Format version (see above). Absent on legacy files. |
| `tool` | string \| null | – | Active main-thread tool name while `working`; null otherwise. |
| `notify` | object \| null | – | Present while Claude needs the user or reports a usage limit: `{message, type}`. Null otherwise. |
| `permission_mode` | string | – | e.g. `"plan"` (drives the planning face); `""` when unset. |
| `stumbled` | boolean | – | A turn just ended on a transient API error (brief embarrassed face). |
| `cwd` | string | – | Working directory the session was launched from. |
| `model` | string | – | Model id reported by the hook payload. |
| `effort` | string | – | Per-turn reasoning effort from `CLAUDE_EFFORT` (`low`/`medium`/`high`/`xhigh`/`max`); drives the effort-reactive card background + statusline footer. Only written when the env var is present. |
| `file` | string | – | The file this turn is working on (from a main-thread tool's `file_path`/`notebook_path`), **sticky per turn**: survives `PostToolUse`, replaced by the next file-touching tool, cleared at turn end (`Stop`/`StopFailure`) and `SessionStart`. `""` when no file is in play. |
| `transcript_path` | string | – | Absolute path of the session's transcript JSONL (from the hook payload); lets a reader tail the transcript, e.g. for the context-window gauge. Non-empty-only: an event that omits it never erases the recorded value. `""` in a fresh state until the first payload carries one. |
| `owner_pid` | integer \| null | – | PID of the owning `claude` process, stamped once. Null when it could not be determined; a reader then falls back to the `ts` staleness timeout instead of liveness. |
| `started` | number | – | Unix epoch seconds when the session's file was first written. |

"Req" marks the keys a reader may assume are always present in a version-1 file.
Everything else is optional and may be absent (older writers, legacy files).

### `state` enum

`idle`, `thinking`, `working`, `waiting`, `compacting`, `dead`.

These are the **raw** states the writer stamps. The widget layers display-only
overlays on top (happy, dizzy, sleeping, blink, an angry variant of `waiting`) —
those are computed by the reader and are **never** written here. A reader that
does not recognise a `state` value should degrade gracefully (fall back to an
idle-like face), not reject the file.

## Validation

`mascot/schema.py` provides the reference reader-side check:

- `validate_session_state(payload) -> list[str]` — the problems with a decoded
  payload (empty list means valid). Structural only: required keys present and
  well-typed, `session_id` non-empty, optional keys well-typed when present.
- `is_valid_session_state(payload) -> bool` — convenience boolean.

Structural checks reach **one level** into the objects a consumer navigates: a
`notify` object must carry a string `message` (and a string `type` if present),
and every `subagents` item must be an object with the field types above. It
tolerates unknown fields and a missing `schema_version`, and never raises. A
non-object payload yields a single complaint. It does **not** check liveness or
the meaning of `state`; those are the widget's concern.
