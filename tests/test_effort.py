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


# --- effort core: animated color math (xhigh wave + max rainbow) -----------
def _valid_rgb(c):
    return (isinstance(c, tuple) and len(c) == 3
            and all(isinstance(x, int) and 0 <= x <= 255 for x in c))


def test_wave_color_is_always_a_valid_color():
    for t in (-100.0, -1.3, 0.0, 0.5, 3.7, 1e6):
        assert _valid_rgb(effort_mod.wave_color(t))


def test_wave_color_stays_within_the_two_shimmer_endpoints():
    lo, hi = effort_mod.WAVE_LO, effort_mod.WAVE_HI
    for k in range(50):
        c = effort_mod.wave_color(k * 0.13)
        for i in range(3):
            assert min(lo[i], hi[i]) <= c[i] <= max(lo[i], hi[i])


def test_wave_color_oscillates():
    seen = {effort_mod.wave_color(k * 0.3) for k in range(40)}
    assert len(seen) > 3  # genuinely sweeps, not a constant


def test_wave_color_is_periodic():
    p = effort_mod.WAVE_PERIOD_S
    assert effort_mod.wave_color(0.37) == effort_mod.wave_color(0.37 + p)


def test_rainbow_color_is_always_a_valid_color():
    for t in (-100.0, -0.9, 0.0, 1.1, 5.5, 1e6):
        assert _valid_rgb(effort_mod.rainbow_color(t))


def test_rainbow_color_is_periodic():
    p = effort_mod.RAINBOW_PERIOD_S
    assert effort_mod.rainbow_color(1.9) == effort_mod.rainbow_color(1.9 + p)


def test_rainbow_color_cycles_widely():
    # Over a full period it visits many distinct hues, not a narrow band.
    seen = {effort_mod.rainbow_color(k * effort_mod.RAINBOW_PERIOD_S / 30)
            for k in range(30)}
    assert len(seen) >= 10


def test_rainbow_color_hits_palette_anchors():
    # At the start of each 1/7 segment the color equals that rainbow anchor.
    n = len(effort_mod.RAINBOW)
    for i in range(n):
        t = i * effort_mod.RAINBOW_PERIOD_S / n
        assert effort_mod.rainbow_color(t) == effort_mod.RAINBOW[i]


def test_panel_fill_animates_for_xhigh_and_max():
    # The two special levels sweep with the clock; sampling across a period must
    # produce more than one panel color.
    for level, period in (("xhigh", effort_mod.WAVE_PERIOD_S),
                          ("max", effort_mod.RAINBOW_PERIOD_S)):
        fills = {effort_mod.panel_fill(level, PANEL, k * period / 12)
                 for k in range(12)}
        assert len(fills) > 2


def test_panel_fill_is_static_for_quiet_levels():
    # low/medium/high do not animate — same panel color at any t.
    for level in ("low", "medium", "high"):
        assert (effort_mod.panel_fill(level, PANEL, 0.0)
                == effort_mod.panel_fill(level, PANEL, 3.3))


def test_border_accent_only_for_animated_levels():
    # Only the two animated levels get a full-strength moving border accent.
    for level in ("", "auto", "low", "medium", "high"):
        assert effort_mod.border_accent(level, 0.0) is None
    for level in ("xhigh", "max"):
        assert _valid_rgb(effort_mod.border_accent(level, 0.0))


def test_border_accent_moves_with_the_clock():
    xs = {effort_mod.border_accent("max", k * effort_mod.RAINBOW_PERIOD_S / 10)
          for k in range(10)}
    assert len(xs) > 2


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

