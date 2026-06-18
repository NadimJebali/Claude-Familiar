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
    "art_style": "pixel",        # "pixel" | "smooth"
    "transparent_bg": True,      # float the rounded card
    "sleep_after_idle_s": 90,    # idle this long -> sleeping sprite (blinks until then)
    "widget_size": "small",      # "small" | "medium" | "large"
    "shake_after_s": 30,         # unanswered prompt waits this long before shaking
    "shake_max_amp_px": 16,      # how violent: max sway (px) at full aggression
    "home_monitor": -1,          # which monitor cards spawn on; -1 = auto (primary)
    "tamagotchi_enabled": True,  # False -> simple hook visualiser (no pet layer)
}


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


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Merge `updates` into the saved settings and persist. Returns the result."""
    data = load_settings()
    data.update({k: v for k, v in updates.items() if k in DEFAULTS})
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
