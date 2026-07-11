"""Per-session context % from the session transcript (PRD #67, #72).

Claude Code appends every turn to a session JSONL under ``~/.claude/projects``;
the state file records its path (``transcript_path``, #71). Tailing that file is
the one context source that works everywhere — the VS Code extension runs no
statusline, but the transcript is always written. The approach (and the tail
cap) follows the Rust widget's TranscriptReader.

Shapes verified against a live transcript: an assistant turn is a line with
``type == "assistant"`` and ``message.usage`` carrying ``input_tokens`` +
``cache_read_input_tokens`` + ``cache_creation_input_tokens`` — their sum is
what the context window currently holds. Sub-agent turns ride the **same file**
flagged ``isSidechain``; they reflect the sub-agent's context, not the
session's, so they are skipped.

The pure pieces are bytes-in/values-out: :func:`consume` parses only complete
lines (a partially-written tail line is left for the next poll — its byte count
simply isn't consumed), :func:`context_tokens` sums tolerantly, and
:func:`context_pct` scales against the divisor the session has earned (#84) or
the one the ``context_window`` setting pins (#95) — see the mode notes at
:data:`CONTEXT_WINDOW_TOKENS`; an overflowing session clamps to 100%.

:class:`TranscriptTailer` owns the per-session byte offsets: the first sight of
a file starts at most :data:`FIRST_READ_TAIL_CAP` bytes from its end (the
latest turn lives at the end; never re-read a huge history), subsequent polls
read only new bytes, a shrunk/rotated file re-anchors, and any I/O failure just
keeps the last known value. It does file I/O, so the widget runs its ``poll``
off the UI thread (see ``qt_app``); it is deliberately Qt-free and testable on
tmp files.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import config

# The default divisor for the gauge — the standard Claude Code window. Claude
# Code doesn't expose the session's real window ANYWHERE (bare transcript model
# strings, windowless hook payloads — verified live, #95), so in "auto" mode the
# evidence decides (#84): once a session's observed tokens exceed this, the
# window must be 1M and the divisor snaps there, sticking for that session (a
# post-compaction token drop doesn't flip it back). Honest limit: a [1m] session
# below 200k still reads against 200k until it crosses — which is why the
# ``context_window`` setting (#95) can pin the mode to "200k"/"1m" outright;
# the tailer reads ``config.CONTEXT_WINDOW_MODE`` every poll, so a panel Save
# corrects the gauge live.
CONTEXT_WINDOW_TOKENS = 200_000
WINDOW_1M_TOKENS = 1_000_000

# First sight of a transcript reads at most this many bytes from the tail —
# the latest message lives at the end, so a long history costs nothing.
FIRST_READ_TAIL_CAP = 512 * 1024

_USAGE_FIELDS = ("input_tokens", "cache_read_input_tokens",
                 "cache_creation_input_tokens")


def context_tokens(usage: Any) -> int:
    """The tokens the context window currently holds, from an assistant turn's
    ``usage`` block — the input-side sum; missing/garbage fields count 0."""
    if not isinstance(usage, dict):
        return 0
    total = 0
    for key in _USAGE_FIELDS:
        value = usage.get(key)
        if not isinstance(value, bool) and isinstance(value, (int, float)):
            total += int(value)
    return total


def window_for(tokens: int, prev_window: int) -> int:
    """The divisor a session has earned: 1M once its tokens prove it (or once
    proven before — sticky), else the 200k default."""
    if prev_window == WINDOW_1M_TOKENS or tokens > CONTEXT_WINDOW_TOKENS:
        return WINDOW_1M_TOKENS
    return CONTEXT_WINDOW_TOKENS


def context_pct(tokens: int, window: int = CONTEXT_WINDOW_TOKENS) -> float:
    """The gauge percentage: 0..100 of ``window`` (clamped)."""
    return max(0.0, min(100.0, tokens / window * 100.0))


def consume(chunk: bytes) -> tuple[dict[str, Any] | None, int]:
    """Parse the complete lines of ``chunk``; return ``(last_usage, consumed)``.

    ``last_usage`` is the newest main-thread assistant ``usage`` block found
    (``None`` when the chunk holds none — e.g. only user/tool lines), and
    ``consumed`` is how many bytes were used: everything up to and including
    the final newline. A partially-written tail line is *not* consumed, so the
    caller re-reads it once the writer finishes it.
    """
    end = chunk.rfind(b"\n")
    if end < 0:
        return None, 0
    consumed = end + 1
    usage: dict[str, Any] | None = None
    for raw in chunk[:consumed].splitlines():
        try:
            rec = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(rec, dict) or rec.get("type") != "assistant":
            continue
        if rec.get("isSidechain"):      # a sub-agent's turn: not this session's context
            continue
        message = rec.get("message")
        candidate = message.get("usage") if isinstance(message, dict) else None
        if isinstance(candidate, dict):
            usage = candidate
    return usage, consumed


class TranscriptTailer:
    """Per-session incremental transcript reads -> the latest context %.

    ``poll`` takes ``{session_id: transcript_path}`` and returns
    ``{session_id: pct}`` for every session whose percentage is known. State
    (byte offsets + last known values) lives per session id and is pruned when
    a session vanishes. Not thread-safe by itself — the widget serializes polls
    (one in flight at a time) on a worker thread.
    """

    def __init__(self) -> None:
        self._offsets: dict[str, int] = {}
        self._tokens: dict[str, int] = {}   # per-sid latest observed context tokens
        self._window: dict[str, int] = {}   # per-sid earned divisor (#84, auto-only)

    def poll(self, sessions: Mapping[str, str]) -> dict[str, float]:
        for sid, path_text in sessions.items():
            if path_text:
                self._read(sid, Path(path_text))
        # Prune state for sessions that vanished, so a long-running widget
        # doesn't accumulate offsets forever (and a re-appearing sid re-anchors).
        for tracked in (self._offsets, self._tokens, self._window):
            for sid in list(tracked):
                if sid not in sessions:
                    del tracked[sid]
        # The percentages are recomputed from the stored tokens every poll under
        # the CURRENT mode (#95), so a live settings flip corrects the gauge even
        # while a session is idle. A pinned mode bypasses the sticky store — a
        # spell under a forced 1M must not count as auto's "proven 1M".
        mode = config.CONTEXT_WINDOW_MODE
        out: dict[str, float] = {}
        for sid, tokens in self._tokens.items():
            if mode == "1m":
                window = WINDOW_1M_TOKENS
            elif mode == "200k":
                window = CONTEXT_WINDOW_TOKENS
            else:
                window = window_for(
                    tokens, self._window.get(sid, CONTEXT_WINDOW_TOKENS))
                self._window[sid] = window
            out[sid] = context_pct(tokens, window)
        return out

    def _read(self, sid: str, path: Path) -> None:
        try:
            size = path.stat().st_size
            offset = self._offsets.get(sid)
            if offset is None or size < offset:      # first sight, or shrunk/rotated
                offset = max(0, size - FIRST_READ_TAIL_CAP)
            if size == offset:                        # nothing new
                return
            with open(path, "rb") as fh:
                fh.seek(offset)
                chunk = fh.read()
        except OSError:
            return                                    # keep the last known value
        usage, consumed = consume(chunk)
        self._offsets[sid] = offset + consumed
        if usage is not None:
            self._tokens[sid] = context_tokens(usage)
