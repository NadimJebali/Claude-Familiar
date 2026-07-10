"""Statusline emitter tests: the pure core (statusline JSON -> usage snapshot +
footer line) and the end-to-end round-trip through hooks/status_emit.py.

The pure functions are tested directly (fast, focused); the script is exercised
as a subprocess with HOME redirected to a tmp dir, mirroring the emit round-trip
convention in test_phase1.py.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from mascot import effort as effort_mod
from mascot import statusline

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _ansi_rgb(rgb):
    return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"

# A payload shaped like Claude Code's documented statusline JSON.
SAMPLE = {
    "model": {"display_name": "Opus 4.8"},
    "workspace": {"current_dir": "/home/upwork/Claude-Familiar"},
    "effort": {"level": "max"},
    "rate_limits": {
        "five_hour": {"used_percentage": 34, "resets_at": 1_783_560_000},
        "seven_day": {"used_percentage": 61, "resets_at": 1_784_000_000},
    },
}


# --- snapshot_from_status --------------------------------------------------
def test_snapshot_extracts_both_windows_effort_and_heartbeat():
    snap = statusline.snapshot_from_status(SAMPLE, now=1000.0)
    assert snap["five_hour"] == {"used_percentage": 34, "resets_at": 1_783_560_000}
    assert snap["seven_day"] == {"used_percentage": 61, "resets_at": 1_784_000_000}
    assert snap["effort"] == "max"
    assert snap["ts"] == 1000.0


def test_snapshot_omits_absent_windows_and_effort():
    # An API-key user (no subscription) has no rate_limits; a model without effort
    # has no effort block. Neither should appear in the snapshot.
    snap = statusline.snapshot_from_status({"model": {"display_name": "X"}}, now=5.0)
    assert "five_hour" not in snap
    assert "seven_day" not in snap
    assert "effort" not in snap
    assert snap["ts"] == 5.0


def test_snapshot_keeps_only_the_present_window():
    payload = {"rate_limits": {"five_hour": {"used_percentage": 12, "resets_at": 9}}}
    snap = statusline.snapshot_from_status(payload, now=1.0)
    assert snap["five_hour"]["used_percentage"] == 12
    assert "seven_day" not in snap


def test_snapshot_tolerates_malformed_limits():
    # rate_limits not a dict, and a window missing fields → skipped, no crash.
    assert statusline.snapshot_from_status({"rate_limits": "nope"}, now=1.0) == {"ts": 1.0}
    bad = {"rate_limits": {"five_hour": {"used_percentage": 50}}}  # no resets_at
    assert "five_hour" not in statusline.snapshot_from_status(bad, now=1.0)


# --- footer_line -----------------------------------------------------------
def test_footer_line_shows_model_effort_usage_and_dir():
    line = statusline.footer_line(SAMPLE)
    assert "Opus 4.8" in line
    assert "max" in line
    assert "5h 34%" in line
    assert "wk 61%" in line
    assert "Claude-Familiar" in line  # basename of current_dir


def test_footer_line_colors_the_effort_in_its_palette():
    line = statusline.footer_line(SAMPLE)
    assert _ansi_rgb(effort_mod.TINTS["max"]) in line  # effort token colored
    assert "\x1b[0m" in line                            # and reset afterwards


def test_footer_line_can_disable_color():
    line = statusline.footer_line(SAMPLE, color=False)
    assert "\x1b[" not in line
    assert "max" in line


def test_footer_line_no_dangling_separators_when_parts_missing():
    # Only a model present → just the model, no leading/trailing/double separator.
    line = statusline.footer_line({"model": {"display_name": "Sonnet"}}, color=False)
    assert line == "Sonnet"


def test_footer_line_empty_payload_is_empty_string():
    assert statusline.footer_line({}, color=False) == ""


# --- merge_snapshots: the two-writer discipline (#69) -----------------------
# usage.json gains a second writer (the OAuth poller) beside status_emit.py.
# Adopted rule: the freshest snapshot wins, and a writer never erases a field it
# has no opinion on (the poller carries no effort; the statusline's must survive).

def _snap(ts, **fields):
    return {"ts": ts, **fields}


def test_merge_newer_incoming_replaces_and_fills_gaps():
    existing = _snap(100.0, effort="high",
                     five_hour={"used_percentage": 10, "resets_at": 999.0})
    incoming = _snap(200.0,
                     five_hour={"used_percentage": 50, "resets_at": 999.0},
                     seven_day={"used_percentage": 61, "resets_at": 999.0})
    merged = statusline.merge_snapshots(existing, incoming)
    assert merged["ts"] == 200.0
    assert merged["five_hour"]["used_percentage"] == 50   # newer data wins
    assert merged["seven_day"]["used_percentage"] == 61
    assert merged["effort"] == "high"    # incoming had no opinion -> preserved


def test_merge_older_or_equal_incoming_is_ignored():
    existing = _snap(200.0, five_hour={"used_percentage": 50, "resets_at": 9.0})
    older = _snap(100.0, five_hour={"used_percentage": 10, "resets_at": 9.0})
    assert statusline.merge_snapshots(existing, older) == existing
    same_ts = _snap(200.0, five_hour={"used_percentage": 10, "resets_at": 9.0})
    assert statusline.merge_snapshots(existing, same_ts) == existing


def test_merge_tolerates_missing_or_malformed_sides():
    incoming = _snap(5.0, effort="max")
    assert statusline.merge_snapshots(None, incoming) == incoming
    assert statusline.merge_snapshots("garbage", incoming) == incoming
    existing = _snap(5.0, effort="low")
    assert statusline.merge_snapshots(existing, None) == existing
    assert statusline.merge_snapshots(existing, "junk") == existing
    # A ts-less incoming can't prove freshness -> the existing snapshot stands.
    assert statusline.merge_snapshots(existing, {"effort": "max"}) == existing


def test_merge_never_mutates_its_inputs():
    existing = _snap(1.0, effort="low")
    incoming = _snap(2.0, five_hour={"used_percentage": 1, "resets_at": 9.0})
    existing_copy, incoming_copy = dict(existing), dict(incoming)
    merged = statusline.merge_snapshots(existing, incoming)
    assert existing == existing_copy and incoming == incoming_copy
    assert merged is not existing and merged is not incoming


# --- end-to-end: hooks/status_emit.py --------------------------------------
STATUS_EMIT = PROJECT_ROOT / "hooks" / "status_emit.py"


def _run_emitter(stdin_text, home):
    """Run the emitter as Claude would, with HOME redirected to a tmp dir so the
    snapshot lands under it. Returns (exit_code, stdout, usage_path)."""
    env = {"HOME": str(home), "USERPROFILE": str(home),
           "PATH": os.environ.get("PATH", "")}
    proc = subprocess.run(
        [sys.executable, str(STATUS_EMIT)],
        input=stdin_text, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stdout, home / ".claude" / "mascot" / "usage.json"


def test_emitter_writes_snapshot_and_prints_footer(tmp_path):
    code, out, usage = _run_emitter(json.dumps(SAMPLE), tmp_path)
    assert code == 0
    assert usage.exists()
    snap = json.loads(usage.read_text(encoding="utf-8"))
    assert snap["five_hour"]["used_percentage"] == 34
    assert snap["seven_day"]["used_percentage"] == 61
    assert snap["effort"] == "max"
    assert out.strip() != ""             # a non-empty footer line
    assert "5h 34%" in out


def test_emitter_survives_malformed_stdin_without_corrupting(tmp_path):
    # First a good write, then garbage stdin: must exit 0 and leave the good file.
    _run_emitter(json.dumps(SAMPLE), tmp_path)
    code, _out, usage = _run_emitter("{ this is not json", tmp_path)
    assert code == 0
    snap = json.loads(usage.read_text(encoding="utf-8"))
    assert snap["effort"] == "max"       # previous good snapshot intact
    assert list(usage.parent.glob("*.tmp")) == []  # no stranded temp files


def test_emitter_merges_preserving_fields_it_has_no_opinion_on(tmp_path):
    # The two-writer discipline (#69) through the real shell: an existing snapshot
    # carries an effort; a fresh statusline payload WITHOUT one must update the
    # windows yet leave the recorded effort standing (merge, not overwrite).
    usage_path = tmp_path / ".claude" / "mascot" / "usage.json"
    usage_path.parent.mkdir(parents=True, exist_ok=True)
    usage_path.write_text(json.dumps(
        {"ts": 1.0, "effort": "max",
         "five_hour": {"used_percentage": 10, "resets_at": 999.0}}), encoding="utf-8")

    payload = {"rate_limits": SAMPLE["rate_limits"]}   # windows only, no effort
    code, _out, usage = _run_emitter(json.dumps(payload), tmp_path)
    assert code == 0
    snap = json.loads(usage.read_text(encoding="utf-8"))
    assert snap["five_hour"]["used_percentage"] == 34  # fresh windows landed
    assert snap["effort"] == "max"                     # preserved across the write


# --- installer: statusLine install / skip-warn / refresh / uninstall -------
def _install_hooks():
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import install_hooks
    return install_hooks


def test_install_statusline_added_when_slot_is_free():
    ih = _install_hooks()
    out, action = ih.install_statusline({})
    assert action == "installed"
    assert "status_emit.py" in out["statusLine"]["command"]
    assert out["statusLine"]["type"] == "command"


def test_install_statusline_skips_a_foreign_statusline():
    ih = _install_hooks()
    foreign = {"statusLine": {"type": "command", "command": "my-own-prompt.sh"}}
    out, action = ih.install_statusline(foreign)
    assert action == "skipped"
    assert out["statusLine"]["command"] == "my-own-prompt.sh"  # left untouched


def test_install_statusline_refreshes_our_own_stale_entry():
    ih = _install_hooks()
    stale = {"statusLine": {"type": "command",
                            "command": '"/old/py" "/x/hooks/status_emit.py"'}}
    out, action = ih.install_statusline(stale)
    assert action == "refreshed"
    assert out["statusLine"]["command"] == ih._status_command()


def test_uninstall_statusline_removes_only_ours():
    ih = _install_hooks()
    ours, removed = ih.uninstall_statusline({"statusLine": ih._status_line_entry()})
    assert removed is True
    assert "statusLine" not in ours

    foreign = {"statusLine": {"type": "command", "command": "my-own-prompt.sh"}}
    kept, removed = ih.uninstall_statusline(foreign)
    assert removed is False
    assert kept["statusLine"]["command"] == "my-own-prompt.sh"


def test_install_and_uninstall_statusline_round_trip_is_clean():
    ih = _install_hooks()
    settings: dict = {}
    settings, _ = ih.install_statusline(settings)
    # Re-running install is idempotent (refresh, not duplicate).
    settings, action = ih.install_statusline(settings)
    assert action == "refreshed"
    settings, removed = ih.uninstall_statusline(settings)
    assert removed and settings == {}
