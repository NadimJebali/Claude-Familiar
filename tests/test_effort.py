"""Effort tests: hook-side capture (emit stamps CLAUDE_EFFORT) + the pure effort
core (normalize / resolve / palette blend / settings fallback).

Mirrors the pure-core testing convention of test_phase1.py — synthetic inputs,
behavior at the public seam, no Tk. The card wiring itself is GUI, verified
visually via demo.py.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import emit
from state_logic import compute_next_state, default_state

from mascot import effort as effort_mod

SID = "4a6ff882-6153-4b83-bd9a-1017fdd10aee"


# --- effort core: normalize -------------------------------------------------
def test_normalize_passes_known_levels_through():
    for level in ("low", "medium", "high", "xhigh", "max"):
        assert effort_mod.normalize(level) == level


def test_normalize_is_case_and_whitespace_tolerant():
    assert effort_mod.normalize("  MAX ") == "max"


def test_normalize_maps_ultracode_to_xhigh():
    assert effort_mod.normalize("ultracode") == "xhigh"


def test_normalize_unknown_and_auto_and_empty_are_blank():
    assert effort_mod.normalize("auto") == ""
    assert effort_mod.normalize("banana") == ""
    assert effort_mod.normalize("") == ""
    assert effort_mod.normalize(None) == ""


# --- effort core: resolve precedence ---------------------------------------
def test_resolve_prefers_state_effort_over_fallback():
    assert effort_mod.resolve("high", "low") == "high"


def test_resolve_falls_back_when_state_effort_blank():
    assert effort_mod.resolve("", "medium") == "medium"


def test_resolve_normalizes_both_and_applies_alias():
    assert effort_mod.resolve("ULTRACODE", "low") == "xhigh"
    assert effort_mod.resolve("garbage", "  Max ") == "max"


def test_resolve_unknown_everywhere_is_blank():
    assert effort_mod.resolve("auto", "nonsense") == ""


# --- effort core: blend primitive ------------------------------------------
def test_blend_strength_zero_returns_base():
    base = (29, 31, 41)
    assert effort_mod.blend(base, (255, 0, 0), 0.0) == base


def test_blend_strength_one_returns_target():
    target = (255, 0, 0)
    assert effort_mod.blend((29, 31, 41), target, 1.0) == target


def test_blend_midpoint_is_between_and_integer():
    out = effort_mod.blend((0, 0, 0), (100, 200, 50), 0.5)
    assert out == (50, 100, 25)
    assert all(isinstance(c, int) for c in out)


def test_blend_clamps_to_byte_range():
    out = effort_mod.blend((250, 250, 250), (500, -100, 300), 1.0)
    assert out == (255, 0, 255)


# --- effort core: panel_fill (static tints) --------------------------------
PANEL = (29, 31, 41)  # the card's dark panel, mirrors tkinter_app.PANEL_FILL


def test_panel_fill_unknown_effort_is_none():
    # Unknown effort → no tint → the card keeps its exact default panel.
    assert effort_mod.panel_fill("", PANEL) is None
    assert effort_mod.panel_fill("auto", PANEL) is None


def test_panel_fill_known_level_is_visibly_tinted():
    for level in effort_mod.LEVELS:
        out = effort_mod.panel_fill(level, PANEL)
        assert out is not None
        assert out != PANEL  # actually moved off the base panel color


def test_panel_fill_moves_toward_the_levels_tint():
    # Each channel of the low tint pulls the panel toward warning-amber.
    tint = effort_mod.TINTS["low"]
    out = effort_mod.panel_fill("low", PANEL)
    for i in range(3):
        lo, hi = sorted((PANEL[i], tint[i]))
        assert lo <= out[i] <= hi


def test_panel_fill_stays_dark_enough_for_text():
    # A subtle tint, not a wash-out: the panel must remain closer to the dark
    # base than to the bright tint (so captions/labels stay readable).
    for level in effort_mod.LEVELS:
        out = effort_mod.panel_fill(level, PANEL)
        assert sum(out) < sum(effort_mod.TINTS[level])


# --- effort core: settings fallback reader ---------------------------------
def test_read_settings_effort_returns_normalized_level(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"effortLevel": "ULTRACODE"}), encoding="utf-8")
    assert effort_mod.read_settings_effort(p) == "xhigh"


def test_read_settings_effort_missing_file_is_blank(tmp_path):
    assert effort_mod.read_settings_effort(tmp_path / "nope.json") == ""


def test_read_settings_effort_corrupt_or_absent_key_is_blank(tmp_path):
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert effort_mod.read_settings_effort(corrupt) == ""
    nokey = tmp_path / "nokey.json"
    nokey.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    assert effort_mod.read_settings_effort(nokey) == ""


def test_settings_effort_cache_invalidates_when_file_changes(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"effortLevel": "low"}), encoding="utf-8")
    os.utime(p, (1000, 1000))
    assert effort_mod.settings_effort(p) == "low"
    # Rewrite with a newer mtime → the cached value must be refreshed.
    p.write_text(json.dumps({"effortLevel": "max"}), encoding="utf-8")
    os.utime(p, (2000, 2000))
    assert effort_mod.settings_effort(p) == "max"


# --- state shape: effort is a first-class, carried field -------------------
def test_default_state_has_empty_effort():
    assert default_state(SID)["effort"] == ""


def test_compute_next_state_carries_effort_across_transitions():
    current = {**default_state(SID), "effort": "xhigh", "state": "thinking"}
    nxt = compute_next_state(current, "PreToolUse", {"tool_name": "Bash"})
    assert nxt["effort"] == "xhigh"


# --- hook capture: emit stamps the live effort -----------------------------
def test_update_state_stamps_effort_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_EFFORT", "max")
    out = emit.update_state(
        tmp_path, "UserPromptSubmit", {"session_id": SID}, now=1.0
    )
    assert out["effort"] == "max"
    written = json.loads((tmp_path / f"{SID}.json").read_text(encoding="utf-8"))
    assert written["effort"] == "max"


def test_update_state_preserves_effort_when_env_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_EFFORT", "high")
    emit.update_state(tmp_path, "UserPromptSubmit", {"session_id": SID}, now=1.0)
    # A later event with no CLAUDE_EFFORT in the environment must not erase the
    # last known level (a hook can fire from a context without the var set).
    monkeypatch.delenv("CLAUDE_EFFORT", raising=False)
    out = emit.update_state(tmp_path, "PreToolUse", {"session_id": SID}, now=2.0)
    assert out["effort"] == "high"

