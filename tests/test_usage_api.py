"""Opt-in OAuth usage poller tests (PRD #67, #70).

The pure pieces (credential/response parsing, the delay policy) are tested
directly with synthetic inputs — no network anywhere in this file; ``poll_once``
runs with an injected fetch. The Qt shell is exercised offscreen via the same
QThreadPool wait used by the ingest tests. The endpoint's exact response shape
is undocumented, so the parser cases pin the tolerated variants.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication

from mascot import usage_api


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- parse_credentials -------------------------------------------------------
def test_parse_credentials_documented_layout():
    raw = json.dumps({"claudeAiOauth": {"accessToken": "tok-123"}})
    assert usage_api.parse_credentials(raw) == "tok-123"


def test_parse_credentials_top_level_fallback():
    assert usage_api.parse_credentials(json.dumps({"accessToken": "tok-9"})) == "tok-9"


def test_parse_credentials_missing_or_garbage_is_none():
    assert usage_api.parse_credentials("") is None
    assert usage_api.parse_credentials("{not json") is None
    assert usage_api.parse_credentials(json.dumps({"claudeAiOauth": {}})) is None
    assert usage_api.parse_credentials(json.dumps({"accessToken": 42})) is None


# --- parse_usage_response ----------------------------------------------------
def test_parse_response_fractional_utilization_becomes_percent():
    body = json.dumps({"five_hour": {"utilization": 0.34, "resets_at": 1000.0},
                       "seven_day": {"utilization": 0.9, "resets_at": 2000.0}})
    snap = usage_api.parse_usage_response(body, now=50.0)
    assert snap["ts"] == 50.0
    assert snap["five_hour"] == {"used_percentage": 34.0, "resets_at": 1000.0}
    assert snap["seven_day"]["used_percentage"] == 90.0


def test_parse_response_percent_utilization_and_used_percentage_pass_through():
    body = json.dumps({"five_hour": {"utilization": 76, "resets_at": 1000.0},
                       "seven_day": {"used_percentage": 61, "resets_at": 2000.0}})
    snap = usage_api.parse_usage_response(body, now=0.0)
    assert snap["five_hour"]["used_percentage"] == 76.0
    assert snap["seven_day"]["used_percentage"] == 61.0


def test_parse_response_iso_resets_at_becomes_epoch():
    body = json.dumps(
        {"five_hour": {"utilization": 0.5, "resets_at": "1970-01-01T01:00:00+00:00"}})
    snap = usage_api.parse_usage_response(body, now=0.0)
    assert snap["five_hour"]["resets_at"] == 3600.0


def test_parse_response_one_valid_window_is_enough():
    body = json.dumps({"five_hour": {"utilization": 0.2, "resets_at": 99.0},
                       "seven_day": {"utilization": "??", "resets_at": None}})
    snap = usage_api.parse_usage_response(body, now=0.0)
    assert "five_hour" in snap and "seven_day" not in snap


def test_parse_response_without_any_window_is_rejected():
    # Never clobber a good snapshot with an empty one (the Rust widget's rule).
    assert usage_api.parse_usage_response(json.dumps({"ok": True}), now=0.0) is None
    assert usage_api.parse_usage_response("{not json", now=0.0) is None
    assert usage_api.parse_usage_response("", now=0.0) is None


# --- next_delay: the backoff policy ------------------------------------------
def test_next_delay_success_resets_to_base():
    assert usage_api.next_delay(2400.0, "ok") == usage_api.POLL_S


def test_next_delay_rate_limit_doubles_up_to_the_cap():
    assert usage_api.next_delay(usage_api.POLL_S, "rate_limited") == usage_api.POLL_S * 2
    assert usage_api.next_delay(3000.0, "rate_limited") == usage_api.BACKOFF_MAX_S


def test_next_delay_other_failures_keep_the_current_delay():
    assert usage_api.next_delay(600.0, "error") == 600.0


# --- poll_once: the full cycle with an injected transport ---------------------
def _creds(tmp_path, token="tok-abc"):
    p = tmp_path / ".credentials.json"
    p.write_text(json.dumps({"claudeAiOauth": {"accessToken": token}}), encoding="utf-8")
    return p


def _ok_fetch(status=200, body=None):
    body = body if body is not None else json.dumps(
        {"five_hour": {"utilization": 0.42, "resets_at": 9e9}})
    calls = []

    def fetch(url, token, timeout):
        calls.append((url, token, timeout))
        return status, body
    fetch.calls = calls
    return fetch


def test_poll_once_merges_into_the_snapshot_preserving_effort(tmp_path):
    usage_path = tmp_path / "usage.json"
    usage_path.write_text(json.dumps({"ts": 1.0, "effort": "max"}), encoding="utf-8")
    fetch = _ok_fetch()

    outcome = usage_api.poll_once(credentials_path=_creds(tmp_path),
                                  usage_path=usage_path, fetch=fetch, now=100.0)
    assert outcome == "ok"
    snap = json.loads(usage_path.read_text(encoding="utf-8"))
    assert snap["five_hour"]["used_percentage"] == 42.0
    assert snap["effort"] == "max"          # this source has no effort opinion
    assert snap["ts"] == 100.0
    assert fetch.calls[0][0] == usage_api.USAGE_URL
    assert fetch.calls[0][1] == "tok-abc"   # the Bearer token reached the transport


def test_poll_once_without_credentials_is_an_error_and_writes_nothing(tmp_path):
    usage_path = tmp_path / "usage.json"
    outcome = usage_api.poll_once(credentials_path=tmp_path / "absent.json",
                                  usage_path=usage_path, fetch=_ok_fetch(), now=1.0)
    assert outcome == "error"
    assert not usage_path.exists()


def test_poll_once_rate_limited_reports_and_writes_nothing(tmp_path):
    usage_path = tmp_path / "usage.json"
    outcome = usage_api.poll_once(credentials_path=_creds(tmp_path),
                                  usage_path=usage_path,
                                  fetch=_ok_fetch(status=429, body=""), now=1.0)
    assert outcome == "rate_limited"
    assert not usage_path.exists()


def test_poll_once_bad_status_or_body_never_clobbers(tmp_path):
    usage_path = tmp_path / "usage.json"
    usage_path.write_text(json.dumps({"ts": 5.0, "effort": "low"}), encoding="utf-8")
    creds = _creds(tmp_path)

    assert usage_api.poll_once(credentials_path=creds, usage_path=usage_path,
                               fetch=_ok_fetch(status=401, body=""), now=9.0) == "error"
    assert usage_api.poll_once(credentials_path=creds, usage_path=usage_path,
                               fetch=_ok_fetch(body="{garbage"), now=9.0) == "error"

    def exploding(url, token, timeout):
        raise OSError("network down")
    assert usage_api.poll_once(credentials_path=creds, usage_path=usage_path,
                               fetch=exploding, now=9.0) == "error"

    snap = json.loads(usage_path.read_text(encoding="utf-8"))
    assert snap == {"ts": 5.0, "effort": "low"}   # untouched by every failure


# --- the Qt shell -------------------------------------------------------------
def test_poller_shell_polls_off_thread_and_reschedules(app, tmp_path):
    usage_path = tmp_path / "usage.json"
    poller = usage_api.UsagePoller(credentials_path=_creds(tmp_path),
                                   usage_path=usage_path, fetch=_ok_fetch())
    poller._fire()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()                     # deliver the queued outcome signal
    assert json.loads(usage_path.read_text(encoding="utf-8"))[
        "five_hour"]["used_percentage"] == 42.0
    assert poller._timer.isActive()         # rescheduled...
    assert poller._delay == usage_api.POLL_S   # ...at the base cadence after "ok"
    poller.dispose()
    assert not poller._timer.isActive()


def test_poller_shell_backs_off_on_rate_limit(app, tmp_path):
    poller = usage_api.UsagePoller(credentials_path=_creds(tmp_path),
                                   usage_path=tmp_path / "usage.json",
                                   fetch=_ok_fetch(status=429, body=""))
    poller._fire()
    QThreadPool.globalInstance().waitForDone(3000)
    app.processEvents()
    assert poller._delay == usage_api.POLL_S * 2
    poller.dispose()


# --- the consent gate ---------------------------------------------------------
def test_usage_api_ships_opt_in():
    from mascot import settings as settings_mod
    assert settings_mod.DEFAULTS["usage_api_enabled"] is False


def test_manager_builds_no_poller_by_default(app, tmp_path):
    from mascot import qt_app
    mgr = qt_app.QtMascotApp(tmp_path)
    assert mgr._usage_poller is None        # consent-first: off unless enabled


def test_manager_builds_and_disposes_the_poller_when_enabled(app, tmp_path, monkeypatch):
    from mascot import config, qt_app
    monkeypatch.setattr(config, "USAGE_API_ENABLED", True)
    mgr = qt_app.QtMascotApp(tmp_path)
    assert mgr._usage_poller is not None
    assert mgr._usage_poller._timer.isActive()   # started (first poll scheduled)
    mgr._quit()
    assert mgr._usage_poller is None
