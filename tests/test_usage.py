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


# --- is_stale: label aged usage data (#69) ----------------------------------
def test_is_stale_flags_an_aged_snapshot():
    snap = {"ts": 1000.0}
    assert usage.is_stale(snap, now=1000.0) is False
    assert usage.is_stale(snap, now=1000.0 + usage.STALE_AFTER_S) is False   # boundary
    assert usage.is_stale(snap, now=1000.0 + usage.STALE_AFTER_S + 1) is True


def test_is_stale_without_a_timestamp_cannot_vouch():
    # A snapshot with no (or garbage) ts is of unknown age -> label it stale.
    assert usage.is_stale({"five_hour": {}}, now=100.0) is True
    assert usage.is_stale({"ts": "soon"}, now=100.0) is True


def test_is_stale_with_no_snapshot_is_false():
    # Nothing is shown at all, so there is nothing to label.
    assert usage.is_stale(None, now=100.0) is False
    assert usage.is_stale("garbage", now=100.0) is False


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


# --- exhausted_until: the account-level death signal (#91) -----------------------
def test_exhausted_until_reads_full_windows():
    now = 1000.0
    ok = {"five_hour": {"used_percentage": 47, "resets_at": 5000.0},
          "seven_day": {"used_percentage": 90, "resets_at": 9000.0}}
    assert usage.exhausted_until(ok, now) is None             # under the limit
    five = {"five_hour": {"used_percentage": 100, "resets_at": 5000.0}}
    assert usage.exhausted_until(five, now) == 5000.0
    weekly = {"five_hour": {"used_percentage": 40, "resets_at": 5000.0},
              "seven_day": {"used_percentage": 100.0, "resets_at": 9000.0}}
    assert usage.exhausted_until(weekly, now) == 9000.0
    both = {"five_hour": {"used_percentage": 100, "resets_at": 5000.0},
            "seven_day": {"used_percentage": 100, "resets_at": 9000.0}}
    assert usage.exhausted_until(both, now) == 9000.0         # the later reset rules


def test_exhausted_until_expires_and_tolerates_garbage():
    past = {"five_hour": {"used_percentage": 100, "resets_at": 500.0}}
    assert usage.exhausted_until(past, now=1000.0) is None    # reset passed: revive
    assert usage.exhausted_until(None, 0.0) is None
    assert usage.exhausted_until({}, 0.0) is None
    assert usage.exhausted_until(
        {"five_hour": {"used_percentage": "x", "resets_at": None}}, 0.0) is None
