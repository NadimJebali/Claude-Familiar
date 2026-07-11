"""Machine-independent suite: pin the live-appliable config flags to their
shipped defaults for every test.

``mascot.config`` snapshots the REAL ``~/.claude/mascot/settings.json`` at
import, so without this pin the author's own choices (compact theme, consented
usage poller, pet on) would change what bare constructs like
``QtMascotApp(tmp_path)`` build mid-suite — the suite went red the first time
it ran on a machine whose settings weren't factory defaults. Tests that want a
non-default flag monkeypatch their own override, which lands after this
autouse fixture and wins.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _default_config(monkeypatch):
    from mascot import config

    monkeypatch.setattr(config, "THEME", "classic")
    monkeypatch.setattr(config, "TAMAGOTCHI_ENABLED", False)
    monkeypatch.setattr(config, "NATIVE_NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(config, "USAGE_API_ENABLED", False)
    monkeypatch.setattr(config, "WIDGET_SIZE", "small")
    monkeypatch.setattr(config, "UI_SCALE", 1.0)
    monkeypatch.setattr(config, "SIMPLE_STAGE", "baby")
