"""Tests for the atomic-write hardening: os.replace retry + no leaked .tmp files,
and the state-dir sweep of stranded temp files. All I/O under tmp_path.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import emit

from mascot import state_store


def test_write_never_leaks_tmp_when_replace_always_fails(tmp_path, monkeypatch):
    def _always_fails(src, dst):
        raise PermissionError("sharing violation")
    monkeypatch.setattr(emit.os, "replace", _always_fails)

    emit.write_state_atomic(tmp_path / "s.json", {"state": "idle"})  # must not raise

    assert list(tmp_path.glob("*.tmp")) == []
    assert not (tmp_path / "s.json").exists()  # the update is lost, cleanly


def test_write_retries_past_transient_replace_failures(tmp_path, monkeypatch):
    real_replace = os.replace
    calls = {"n": 0}

    def _flaky(src, dst):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("sharing violation")
        real_replace(src, dst)
    monkeypatch.setattr(emit.os, "replace", _flaky)

    emit.write_state_atomic(tmp_path / "s.json", {"state": "working"})

    assert calls["n"] == 3
    assert json.loads((tmp_path / "s.json").read_text())["state"] == "working"
    assert list(tmp_path.glob("*.tmp")) == []


def test_load_states_sweeps_stale_tmp_but_keeps_fresh_ones(tmp_path):
    now = 1_000_000.0
    stale = tmp_path / "sess.111.tmp"
    fresh = tmp_path / "sess.222.tmp"
    stale.write_text("{}")
    fresh.write_text("{}")
    os.utime(stale, (now - 600, now - 600))   # past the sweep age
    os.utime(fresh, (now - 5, now - 5))       # an in-flight write: untouched
    real = tmp_path / "sess.json"
    real.write_text(json.dumps({"session_id": "sess", "state": "idle", "ts": now}))

    states = state_store.load_states(tmp_path, now)

    assert not stale.exists()
    assert fresh.exists()
    assert "sess" in states  # the sweep never disturbs real session loading
