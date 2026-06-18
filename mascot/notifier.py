"""Native OS toast notifications (#19), complementing the in-app speech bubble.

When a session's ``notify`` (a permission/attention prompt, or a usage/session
limit) first appears, the widget also raises a **native OS toast** via ``plyer`` —
so you notice even when the card is off-screen or you're in another app. The bubble
is unchanged; this is an addition, not a replacement.

The toast is **edge-triggered**: the state files are polled every 500ms and a
``notify`` persists across polls, so a pure ``fresh_notifications`` step fires each
notify exactly once (a notify that clears and returns, or whose message changes,
fires again). The pure core (edge-detection + title/message formatting) is
unit-tested; the plyer call is a thin, lazy, best-effort shell run on a daemon
thread so it never blocks Tk and never crashes the widget.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

APP_NAME = "Claude Familiar"

# How long the OS should keep the toast up (seconds); the OS may clamp/ignore it.
NOTIFY_TIMEOUT_S = 10

# notify["type"] values that mean the session ended on a usage/session/account
# limit (vs a recoverable permission/attention prompt). Mirrors state_logic's
# usage-limit + StopFailure death types, so the toast title can say "usage limit".
_LIMIT_TYPES = frozenset({
    "usage_limit", "rate_limit", "billing_error",
    "authentication_failed", "oauth_org_not_allowed",
})


def fresh_notifications(prev_states: dict[str, dict],
                        next_states: dict[str, dict]) -> list[tuple[str, dict]]:
    """Sessions whose ``notify`` just became newly set or changed → ``[(sid, notify)]``.

    Edge-triggered: a notify unchanged across polls is skipped (so a 30s permission
    prompt toasts once, not every 500ms); a brand-new session that arrives already
    notifying fires; a notify that clears then returns, or whose message changes,
    fires again.
    """
    out: list[tuple[str, dict]] = []
    for sid, state in next_states.items():
        nxt = state.get("notify")
        if not nxt:
            continue
        prev = (prev_states.get(sid) or {}).get("notify")
        if nxt != prev:
            out.append((sid, nxt))
    return out


def toast_for(notify: dict[str, Any] | None) -> tuple[str, str] | None:
    """``(title, message)`` for a notify dict, or ``None`` if there's nothing to show."""
    if not notify:
        return None
    message = (notify.get("message") or "").strip()
    if not message:
        return None
    ntype = notify.get("type") or ""
    if ntype in _LIMIT_TYPES:
        title = f"{APP_NAME} — usage limit"
    elif ntype == "permission":
        title = f"{APP_NAME} — needs your permission"
    else:
        title = f"{APP_NAME} — needs you"
    return title, message


def _show_blocking(title: str, message: str, timeout: int) -> None:
    """Call plyer to show the toast (lazy import; best-effort)."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message,
                            app_name=APP_NAME, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — a toast must never crash the widget
        print("[mascot] native notification unavailable:", exc)


def notify_native(title: str, message: str, *, timeout: int = NOTIFY_TIMEOUT_S) -> None:
    """Show a native OS toast on a daemon thread, so it never blocks the Tk loop."""
    threading.Thread(target=_show_blocking, args=(title, message, timeout),
                     daemon=True).start()


def emit(notify: dict[str, Any] | None, *,
         show: Callable[[str, str], None] = notify_native) -> None:
    """Raise a toast for ``notify`` if it warrants one. ``show`` is injectable for tests."""
    toast = toast_for(notify)
    if toast is not None:
        show(*toast)
