"""Persistent user settings for the mascot.

Stored as JSON at ``~/.claude/mascot/settings.json``. `config` reads these at
import; the control panel writes them. Missing/corrupt file -> defaults, so the
widget always runs even before the settings page is ever opened.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SETTINGS_PATH = Path.home() / ".claude" / "mascot" / "settings.json"

DEFAULTS: dict[str, Any] = {
    "transparent_bg": True,      # float the rounded card
    "sleep_after_idle_s": 90,    # idle this long -> sleeping sprite (blinks until then)
    "widget_size": "small",      # "small" | "medium" | "large"
    "simple_stage": "baby",      # pet-off look: "egg" | "baby" | "teen" | "adult"
    "shake_after_s": 30,         # unanswered prompt waits this long before shaking
    "shake_max_amp_px": 16,      # how violent: max sway (px) at full aggression
    "home_monitor": -1,          # which monitor cards spawn on; -1 = auto (primary)
    # Quiet by default (PRD #67): a fresh install is a simple hook visualiser with
    # no OS toasts — the pet layer and notifications are each one toggle away
    # (Settings panel; the tray's checkable Notifications row applies live).
    "tamagotchi_enabled": False,   # True -> the Tamagotchi pet layer
    "native_notifications": False,  # True -> native OS toasts (in-app bubble always on)
    # Consent-first (#70): True lets the widget read your Claude Code login token
    # and poll Anthropic's usage endpoint for live 5h/weekly numbers. The token is
    # never logged and never refreshed; see mascot/usage_api.py.
    "usage_api_enabled": False,
    # Presentation theme (#74): "classic" = one mascot card per session (today's
    # look); "compact" = one small panel listing every session as a row.
    "theme": "classic",
}

THEMES = ("classic", "compact")


def valid_theme(value: Any) -> str:
    """``value`` if it names a known theme, else the classic default — so a
    hand-edited settings file can never leave the widget without a presentation."""
    return value if value in THEMES else "classic"


def load_settings() -> dict[str, Any]:
    """Return saved settings merged over the defaults (defaults win for gaps)."""
    data = dict(DEFAULTS)
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            data.update({k: saved[k] for k in saved if k in DEFAULTS})
    except (OSError, json.JSONDecodeError):
        pass
    return data


def read_settings_or_none() -> dict[str, Any] | None:
    """Like :func:`load_settings`, but ``None`` when the file is absent or
    unparseable instead of silently falling back to the defaults — for the
    widget's live settings watch (#81), where a torn mid-write read must apply
    *nothing* rather than "apply factory defaults" (which would e.g. flip a
    compact user back to classic). The completed write fires its own event."""
    try:
        saved = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(saved, dict):
        return None
    data = dict(DEFAULTS)
    data.update({k: saved[k] for k in saved if k in DEFAULTS})
    return data


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge `updates` into the saved settings and persist. Returns the result."""
    data = load_settings()
    data.update({k: v for k, v in updates.items() if k in DEFAULTS})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
