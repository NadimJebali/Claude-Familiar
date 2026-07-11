"""Tests for the persisted-settings defaults (the shipped out-of-box choices).

Most settings are exercised through their consumers; the context-gauge window
gets pinned here because its *default* is the contract: current Claude Code
plans run 1M-token windows, and the auto-inference's blind spot (a ``[1m]``
session below 200k reads against 200k — #95) means an "auto" default over-reads
the ring for exactly those users. The gauge therefore ships pinned to **1m**;
"auto" (200k until the tokens prove 1M) and "200k" stay one Settings pick away.
"""
from __future__ import annotations

from mascot import settings


def test_context_window_ships_pinned_to_1m(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    assert settings.load_settings()["context_window"] == "1m"


def test_valid_window_falls_back_to_the_shipped_default():
    # Like every valid_* guard: garbage never strands the widget, it lands on
    # the same choice a fresh install ships with.
    assert settings.valid_window("bogus") == "1m"
    assert settings.valid_window(None) == "1m"
    for mode in settings.WINDOWS:
        assert settings.valid_window(mode) == mode
