"""Usage-core tests: the pure snapshot->view (with reset decay), the
traffic-light bar color thresholds, and the mtime-cached snapshot loader.

Pure, synthetic, no Tk — mirrors the effort/pet pure-core convention. The card
row itself is GUI, verified visually via demo.py.
"""
from __future__ import annotations

import json
import os

from mascot import usage


def _snap(five=None, seven=None, **extra):
    snap = dict(extra)
    if five is not None:
        snap["five_hour"] = {"used_percentage": five[0], "resets_at": five[1]}
    if seven is not None:
        snap["seven_day"] = {"used_percentage": seven[0], "resets_at": seven[1]}
    return snap


# --- usage_view: present windows -> labeled bars ---------------------------
def test_usage_view_returns_both_windows_labeled_5h_and_7d():
    snap = _snap(five=(34, 2000), seven=(61, 5000))
    bars = usage.usage_view(snap, now=1000.0)
    assert [b.label for b in bars] == ["5h", "7d"]
    assert [round(b.pct) for b in bars] == [34, 61]


def test_usage_view_window_past_its_reset_reads_zero():
    # 1s before the reset the recorded pct stands; 1s after, the window reset -> 0.
    snap = _snap(five=(80, 2000))
    assert usage.usage_view(snap, now=1999.0)[0].pct == 80
    assert usage.usage_view(snap, now=2001.0)[0].pct == 0.0


def test_usage_view_omits_absent_windows():
    bars = usage.usage_view(_snap(seven=(50, 9999)), now=0.0)
    assert [b.label for b in bars] == ["7d"]


def test_usage_view_malformed_or_empty_yields_no_bars():
    assert usage.usage_view(None, now=0.0) == []
    assert usage.usage_view({}, now=0.0) == []
    # A window missing resets_at is unusable → dropped.
    assert usage.usage_view({"five_hour": {"used_percentage": 20}}, now=0.0) == []


# --- bar_color: traffic-light thresholds -----------------------------------
def test_bar_color_calm_below_seventy():
    assert usage.bar_color(0) == usage.CALM
    assert usage.bar_color(69.9) == usage.CALM


def test_bar_color_warns_from_seventy_to_ninety():
    assert usage.bar_color(70.0) == usage.WARN     # boundary is inclusive of warn
    assert usage.bar_color(89.9) == usage.WARN


def test_bar_color_alarms_from_ninety():
    assert usage.bar_color(90.0) == usage.ALARM     # the CLI's own 0.9 alarm
    assert usage.bar_color(100.0) == usage.ALARM


# --- load_usage: mtime-cached snapshot reader ------------------------------
def test_load_usage_reads_snapshot(tmp_path):
    p = tmp_path / "usage.json"
    p.write_text(json.dumps(_snap(five=(10, 99))), encoding="utf-8")
    snap = usage.load_usage(p)
    assert snap["five_hour"]["used_percentage"] == 10


def test_load_usage_missing_or_corrupt_is_none(tmp_path):
    assert usage.load_usage(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert usage.load_usage(bad) is None


def test_load_usage_cache_invalidates_when_file_changes(tmp_path):
    p = tmp_path / "usage.json"
    p.write_text(json.dumps(_snap(five=(10, 99))), encoding="utf-8")
    os.utime(p, (1000, 1000))
    assert usage.load_usage(p)["five_hour"]["used_percentage"] == 10
    p.write_text(json.dumps(_snap(five=(55, 99))), encoding="utf-8")
    os.utime(p, (2000, 2000))
    assert usage.load_usage(p)["five_hour"]["used_percentage"] == 55
