"""Transcript tailer tests (PRD #67, #72): per-session context % from the
session's transcript JSONL.

The pure pieces (usage summing, incremental line consumption, the percentage)
run on synthetic lines shaped like the real transcripts (verified against a
live ``~/.claude/projects/**.jsonl``: assistant lines carry ``message.usage``
with input + cache token fields; sub-agent turns ride the same file flagged
``isSidechain``). The tailer is exercised on tmp files; the qt_app shell
offscreen via the QThreadPool wait convention.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from mascot import transcript


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _line(input_tokens=2, cache_read=100, cache_create=50, *,
          kind="assistant", sidechain=False, usage=True):
    rec = {"type": kind, "isSidechain": sidechain, "sessionId": "s"}
    if usage:
        rec["message"] = {"usage": {
            "input_tokens": input_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_create,
            "output_tokens": 10,
        }}
    else:
        rec["message"] = {}
    return json.dumps(rec)


# --- context_tokens -----------------------------------------------------------
def test_context_tokens_sums_the_three_input_fields():
    usage = {"input_tokens": 2, "cache_read_input_tokens": 340_883,
             "cache_creation_input_tokens": 2_745, "output_tokens": 535}
    assert transcript.context_tokens(usage) == 343_630


def test_context_tokens_tolerates_missing_and_garbage_fields():
    assert transcript.context_tokens({"input_tokens": 5}) == 5
    assert transcript.context_tokens({"input_tokens": "??",
                                      "cache_read_input_tokens": True}) == 0
    assert transcript.context_tokens({}) == 0
    assert transcript.context_tokens(None) == 0


# --- consume: incremental complete-line parsing --------------------------------
def test_consume_returns_last_assistant_usage_and_consumed_bytes():
    chunk = (_line(cache_read=100) + "\n" + _line(cache_read=200) + "\n").encode()
    usage, consumed = transcript.consume(chunk)
    assert usage["cache_read_input_tokens"] == 200   # the LAST assistant line wins
    assert consumed == len(chunk)                    # everything ended in newlines


def test_consume_leaves_a_partial_tail_line_for_the_next_poll():
    complete = (_line(cache_read=100) + "\n").encode()
    partial = _line(cache_read=999).encode()[:20]    # a write in progress
    usage, consumed = transcript.consume(complete + partial)
    assert usage["cache_read_input_tokens"] == 100
    assert consumed == len(complete)                 # the tail is retried later


def test_consume_skips_sidechain_and_non_assistant_and_garbage_lines():
    chunk = "\n".join([
        _line(cache_read=1, kind="user"),
        _line(cache_read=2, sidechain=True),         # a sub-agent turn: not ours
        "{this is not json",
        _line(cache_read=3, usage=False),            # assistant without usage
        _line(cache_read=4),
    ]).encode() + b"\n"
    usage, consumed = transcript.consume(chunk)
    assert usage["cache_read_input_tokens"] == 4
    assert consumed == len(chunk)


def test_consume_with_no_usable_line_is_none_but_still_consumes():
    chunk = (_line(kind="user") + "\n").encode()
    usage, consumed = transcript.consume(chunk)
    assert usage is None
    assert consumed == len(chunk)
    assert transcript.consume(b"") == (None, 0)


# --- context_pct ----------------------------------------------------------------
def test_context_pct_scales_and_clamps():
    assert transcript.context_pct(0) == 0.0
    assert transcript.context_pct(transcript.CONTEXT_WINDOW_TOKENS // 2) == 50.0
    # A 1M-context session overflows the default 200k divisor: clamp, don't lie.
    assert transcript.context_pct(343_630) == 100.0


# --- TranscriptTailer: offsets over real files ----------------------------------
def _write_lines(path, *lines):
    with open(path, "a", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")


def test_tailer_reads_incrementally_and_keeps_last_known(tmp_path):
    t = tmp_path / "sess.jsonl"
    _write_lines(t, _line(cache_read=100_000, cache_create=0, input_tokens=0))
    tailer = transcript.TranscriptTailer()

    out = tailer.poll({"s1": str(t)})
    assert out["s1"] == 50.0                          # 100k / 200k

    out = tailer.poll({"s1": str(t)})                 # no new bytes
    assert out["s1"] == 50.0                          # last known stands

    _write_lines(t, _line(cache_read=150_000, cache_create=0, input_tokens=0))
    out = tailer.poll({"s1": str(t)})
    assert out["s1"] == 75.0                          # only the new line was read


def test_tailer_missing_file_keeps_last_and_never_raises(tmp_path):
    t = tmp_path / "sess.jsonl"
    _write_lines(t, _line(cache_read=100_000, cache_create=0, input_tokens=0))
    tailer = transcript.TranscriptTailer()
    assert tailer.poll({"s1": str(t)})["s1"] == 50.0
    t.unlink()
    assert tailer.poll({"s1": str(t)})["s1"] == 50.0  # vanished file -> last known
    # A session that has never carried a transcript_path gets no gauge at all.
    assert "s2" not in tailer.poll({"s1": str(t), "s2": ""})


def test_tailer_first_read_caps_at_the_file_tail(tmp_path):
    # A huge pre-existing transcript: only the last FIRST_READ_TAIL_CAP bytes are
    # read on first sight, and the latest usage (near the end) is still found.
    t = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "user", "pad": "x" * 200})
    lines = [filler] * (transcript.FIRST_READ_TAIL_CAP // len(filler) + 64)
    lines.append(_line(cache_read=120_000, cache_create=0, input_tokens=0))
    _write_lines(t, *lines)
    assert t.stat().st_size > transcript.FIRST_READ_TAIL_CAP

    tailer = transcript.TranscriptTailer()
    assert tailer.poll({"s1": str(t)})["s1"] == 60.0


def test_tailer_recovers_from_a_shrunk_file(tmp_path):
    t = tmp_path / "sess.jsonl"
    _write_lines(t, *[_line(cache_read=100_000)] * 50)
    tailer = transcript.TranscriptTailer()
    tailer.poll({"s1": str(t)})
    t.write_text(_line(cache_read=20_000, cache_create=0, input_tokens=0) + "\n",
                 encoding="utf-8")                    # rotated/replaced: smaller now
    assert tailer.poll({"s1": str(t)})["s1"] == 10.0


def test_tailer_forgets_sessions_that_vanish(tmp_path):
    t = tmp_path / "sess.jsonl"
    _write_lines(t, _line())
    tailer = transcript.TranscriptTailer()
    tailer.poll({"s1": str(t)})
    out = tailer.poll({})                             # the session ended
    assert out == {}
    assert tailer.poll({"s1": str(t)})["s1"] is not None   # re-appearing re-reads


# --- the qt_app shell ------------------------------------------------------------
def test_manager_polls_context_off_thread_and_pushes_to_cards(app, tmp_path):
    from mascot import qt_app
    t = tmp_path / "sess.jsonl"
    _write_lines(t, _line(cache_read=100_000, cache_create=0, input_tokens=0))

    mgr = qt_app.QtMascotApp(tmp_path / "state")
    state = {"session_id": "s1", "state": "idle", "ts": time.time(),
             "subagents": [], "schema_version": 1, "transcript_path": str(t)}
    mgr._on_sessions({"s1": state})
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()                               # deliver the queued results
    assert mgr._context.get("s1") == 50.0
    assert mgr.cards["s1"]._context_pct == 50.0
    mgr._on_sessions({})                              # tidy up


# --- the adaptive window (#84) --------------------------------------------------
def test_window_snaps_to_1m_once_tokens_prove_it_and_sticks():
    base = transcript.CONTEXT_WINDOW_TOKENS
    one_m = transcript.WINDOW_1M_TOKENS
    assert transcript.window_for(150_000, base) == base       # under: stays 200k
    assert transcript.window_for(250_000, base) == one_m      # proven: snaps
    # Sticky: a post-compaction token drop keeps the proven window — the session
    # doesn't flip back to reading 60k as 30% of 200k.
    assert transcript.window_for(60_000, one_m) == one_m


def test_context_pct_scales_by_the_given_window():
    assert transcript.context_pct(350_000, transcript.WINDOW_1M_TOKENS) == 35.0
    assert transcript.context_pct(100_000) == 50.0            # default divisor stands


def test_tailer_adapts_the_window_per_session(tmp_path):
    p = tmp_path / "t.jsonl"

    def usage_line(tokens: int) -> str:
        return json.dumps({"type": "assistant",
                           "message": {"usage": {"input_tokens": tokens}}}) + "\n"

    t = transcript.TranscriptTailer()
    p.write_text(usage_line(150_000), encoding="utf-8")
    assert t.poll({"s": str(p)})["s"] == 75.0                 # 150k / 200k
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(usage_line(350_000))
    assert t.poll({"s": str(p)})["s"] == 35.0                 # crossed: 350k / 1M
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(usage_line(120_000))                         # compacted back down
    assert t.poll({"s": str(p)})["s"] == 12.0                 # the window sticks
