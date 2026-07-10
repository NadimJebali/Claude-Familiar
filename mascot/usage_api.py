"""Opt-in OAuth usage poller — live 5h/weekly numbers without a CLI session (#70).

The VS Code extension never runs statusline commands, so ``usage.json`` ages
whenever no terminal session is open (and now reads "stale", #69). When the
``usage_api_enabled`` setting is on, the widget reads Claude Code's locally
stored OAuth access token and polls the account usage endpoint, merging results
into the same snapshot file under the two-writer discipline
(:func:`mascot.statusline.merge_snapshots`: freshest wins, and this source has
no ``effort`` opinion so it can never erase the statusline's).

Consent + safety (mirroring the Rust widget's guarantees): **off by default**;
the token is read from disk only when a poll runs, sent only to Anthropic's
usage endpoint as a Bearer header, **never logged**, and **never refreshed** —
an auth failure just keeps the current cadence (this module cannot mint or
renew credentials). Rate limiting backs off exponentially: a 429 doubles the
delay up to :data:`BACKOFF_MAX_S`; any other failure keeps the current delay;
a success resets it to :data:`POLL_S`.

The pure pieces (credential/response parsing, the delay policy, one poll cycle
with an injected transport) are clock-free and unit-tested; :class:`UsagePoller`
is the thin Qt shell — a single-shot ``QTimer`` kicks each cycle onto the global
``QThreadPool`` (never the UI thread) and reschedules from the outcome. The
endpoint's response shape is undocumented, so the parser tolerates the known
variants (fractional or percent ``utilization``, ``used_percentage``, epoch or
ISO-8601 ``resets_at``) and rejects a response with no usable window rather
than clobber good numbers.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal

from . import statusline

# Claude Code's locally-stored OAuth credentials and Anthropic's usage endpoint.
CREDENTIALS_PATH = Path.home() / ".claude" / ".credentials.json"
USAGE_URL = "https://api.anthropic.com/api/oauth/usage"

POLL_S = 300.0          # base cadence (the Rust widget's choice)
BACKOFF_MAX_S = 3600.0  # a 429 doubles the delay, capped here
FETCH_TIMEOUT_S = 10.0

# fetch(url, token, timeout) -> (http_status, body_text). Injectable for tests.
Fetch = Callable[[str, str, float], tuple[int, str]]

_WINDOWS = ("five_hour", "seven_day")


# --- pure: credentials --------------------------------------------------------
def parse_credentials(raw: str) -> str | None:
    """The OAuth access token from a ``.credentials.json`` body, or ``None``.

    Accepts the documented ``claudeAiOauth.accessToken`` layout and a top-level
    ``accessToken`` fallback. The token is returned to be sent as a header —
    never log or print it.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    oauth = data.get("claudeAiOauth")
    token = oauth.get("accessToken") if isinstance(oauth, dict) else None
    if token is None:
        token = data.get("accessToken")
    return token if isinstance(token, str) and token else None


# --- pure: the usage response -> our snapshot shape ----------------------------
def _pct(value: Any) -> float | None:
    """A 0..100 percentage from a raw utilization value: a 0..1 fraction is
    scaled up; anything above 1 is already a percent; non-numbers are unusable."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v * 100.0 if 0.0 <= v <= 1.0 else v


def _epoch(value: Any) -> float | None:
    """An epoch-seconds reset time from a number or an ISO-8601 string."""
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def parse_usage_response(raw: str, now: float) -> dict[str, Any] | None:
    """The snapshot to merge from a usage-endpoint response body, or ``None``.

    Each window needs a usable percentage (``utilization`` fraction/percent or
    ``used_percentage``) and reset time (epoch or ISO-8601); unusable windows
    are dropped. A response with **no** usable window is rejected outright, so
    an empty/odd body can never clobber a good snapshot.
    """
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    snap: dict[str, Any] = {"ts": now}
    for key in _WINDOWS:
        window = data.get(key)
        if not isinstance(window, dict):
            continue
        pct = _pct(window.get("utilization"))
        if pct is None:
            pct = _pct(window.get("used_percentage"))
        reset = _epoch(window.get("resets_at"))
        if pct is not None and reset is not None:
            snap[key] = {"used_percentage": pct, "resets_at": reset}
    return snap if any(key in snap for key in _WINDOWS) else None


# --- pure: the backoff policy ---------------------------------------------------
def next_delay(prev_delay: float, outcome: str) -> float:
    """The delay before the next poll: success resets to the base cadence, a
    rate limit doubles (capped), any other failure keeps the current delay."""
    if outcome == "ok":
        return POLL_S
    if outcome == "rate_limited":
        return min(prev_delay * 2.0, BACKOFF_MAX_S)
    return prev_delay


# --- one poll cycle (transport injected; no Qt) ---------------------------------
def _http_fetch(url: str, token: str, timeout: float) -> tuple[int, str]:
    """The real transport: one GET with the Bearer header via stdlib urllib."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:   # 4xx/5xx arrive as exceptions
        return exc.code, ""


def _write_atomic(path: Path, data: dict[str, Any]) -> None:
    """Write-then-rename so the widget's reader never sees a torn snapshot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def poll_once(*, credentials_path: Path, usage_path: Path,
              fetch: Fetch, now: float) -> str:
    """Run one poll cycle: token -> fetch -> parse -> merge-write.

    Returns the outcome for :func:`next_delay` (``"ok"`` / ``"rate_limited"`` /
    ``"error"``). Every failure leaves the snapshot file untouched.
    """
    try:
        token = parse_credentials(credentials_path.read_text(encoding="utf-8"))
    except OSError:
        token = None
    if token is None:
        return "error"

    try:
        status, body = fetch(USAGE_URL, token, FETCH_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — any transport failure is just a missed poll
        return "error"
    if status == 429:
        return "rate_limited"
    if status != 200:
        return "error"

    snapshot = parse_usage_response(body, now)
    if snapshot is None:
        return "error"
    try:
        existing = json.loads(usage_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        existing = None
    try:
        _write_atomic(usage_path, statusline.merge_snapshots(existing, snapshot))
    except OSError:
        return "error"
    return "ok"


# --- the Qt shell ----------------------------------------------------------------
class _PollSignals(QObject):
    done = Signal(str)


class _PollTask(QRunnable):
    """Runs one poll cycle off the UI thread and emits its outcome."""

    def __init__(self, poll: Callable[[], str], signals: _PollSignals) -> None:
        super().__init__()
        self._poll = poll
        self._signals = signals

    def run(self) -> None:  # executes on a pool thread
        try:
            outcome = self._poll()
        except Exception:  # noqa: BLE001 — a bad poll must never take down the pool
            outcome = "error"
        self._signals.done.emit(outcome)


class UsagePoller(QObject):
    """Polls the usage endpoint on a backoff-aware cadence, off the UI thread."""

    def __init__(self, parent: QObject | None = None, *,
                 credentials_path: Path = CREDENTIALS_PATH,
                 usage_path: Path = statusline.USAGE_PATH,
                 fetch: Fetch = _http_fetch) -> None:
        super().__init__(parent)
        self._credentials_path = credentials_path
        self._usage_path = usage_path
        self._fetch = fetch
        self._delay = POLL_S
        self._pool = QThreadPool.globalInstance()
        # The worker emits on a pool thread; the queued hop lands _on_done here.
        self._signals = _PollSignals()
        self._signals.done.connect(self._on_done)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)

    def start(self) -> None:
        """Poll right away (fresh bars on widget launch), then follow the cadence."""
        self._timer.start(0)

    def _fire(self) -> None:
        import time

        creds, usage, fetch = self._credentials_path, self._usage_path, self._fetch
        self._pool.start(_PollTask(
            lambda: poll_once(credentials_path=creds, usage_path=usage,
                              fetch=fetch, now=time.time()),
            self._signals))

    def _on_done(self, outcome: str) -> None:
        self._delay = next_delay(self._delay, outcome)
        self._timer.start(round(self._delay * 1000))

    def dispose(self) -> None:
        """Stop scheduling. Idempotent; an in-flight poll finishes harmlessly."""
        self._timer.stop()
