"""Tests for the pure session-roster reconciler (mascot/roster.py, issue #54).

Example-based lifecycle cases live here; the invariants are fuzzed in
tests/test_properties.py. No GUI — the core is pure, so these need no Tk.
"""
from __future__ import annotations

from mascot import roster


def _state(sid, st="idle"):
    return {"session_id": sid, "state": st, "ts": 1.0, "subagents": []}


def test_a_brand_new_session_is_created_with_index_zero():
    cmds = roster.reconcile([], {"s1": _state("s1")})
    assert cmds.create == [("s1", _state("s1"), 0)]
    assert cmds.update == []
    assert cmds.destroy == []


def test_an_existing_session_is_updated_not_recreated():
    cmds = roster.reconcile(["s1"], {"s1": _state("s1", "working")})
    assert cmds.create == []
    assert cmds.update == [("s1", _state("s1", "working"))]
    assert cmds.destroy == []


def test_a_vanished_session_is_destroyed():
    # SessionEnd, owner-death and staleness all manifest upstream (in
    # state_store.load_states) as "absent from live", so the reconciler prunes
    # any shown session that is no longer live — one code path for all three.
    cmds = roster.reconcile(["s1"], {})
    assert cmds.destroy == ["s1"]
    assert cmds.create == []
    assert cmds.update == []


def test_create_index_follows_sorted_session_id_order():
    live = {"b": _state("b"), "a": _state("a"), "c": _state("c")}
    cmds = roster.reconcile([], live)
    assert cmds.create == [("a", _state("a"), 0),
                           ("b", _state("b"), 1),
                           ("c", _state("c"), 2)]


def test_mixed_create_update_destroy_in_one_pass():
    cmds = roster.reconcile(["old", "keep"],
                            {"keep": _state("keep", "thinking"), "new": _state("new")})
    assert cmds.destroy == ["old"]
    assert cmds.update == [("keep", _state("keep", "thinking"))]
    # A new card's index is its position among ALL live sessions (sorted), matching
    # the manager's old inline loop: keep=0, new=1, so "new" is created at index 1.
    assert cmds.create == [("new", _state("new"), 1)]


def test_nothing_to_create_or_destroy_when_rosters_match():
    live = {"s1": _state("s1"), "s2": _state("s2")}
    cmds = roster.reconcile(["s1", "s2"], live)
    assert cmds.create == []
    assert cmds.destroy == []
    assert len(cmds.update) == 2


def test_destroy_is_sorted_and_disjoint_from_the_live_set():
    cmds = roster.reconcile(["z", "a", "m"], {"m": _state("m")})
    assert cmds.destroy == ["a", "z"]  # sorted, and excludes the still-live "m"


def test_empty_inputs_yield_no_commands():
    cmds = roster.reconcile([], {})
    assert cmds.create == []
    assert cmds.update == []
    assert cmds.destroy == []
