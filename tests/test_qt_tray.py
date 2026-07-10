"""Tests for the Qt tray + native toasts (issue #61).

The tray icon/host is GUI I/O (verified live), but its seams are pure and tested
here: the menu model (:func:`menu_rows`), the QMenu build + click routing, and the
manager's edge-triggered toast routing through the pure notifier core. Offscreen;
skips where PySide6 is absent.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mascot import qt_app, qt_tray


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


# --- menu_rows (pure: shape without a QApplication) --------------------------
def test_menu_rows_lists_every_action_in_order_with_a_separator():
    rows = qt_tray.menu_rows({"pet": 1, "toggle": 1, "settings": 1, "quit": 1})
    assert rows == [("Pet…", "pet"), ("Show / hide cards", "toggle"),
                    ("Settings…", "settings"), (qt_tray.SEPARATOR, None), ("Quit", "quit")]


def test_menu_rows_drops_pet_when_no_callback_but_keeps_the_separator():
    rows = qt_tray.menu_rows({"toggle": 1, "settings": 1, "quit": 1})
    labels = [label for label, _ in rows]
    assert "Pet…" not in labels
    assert labels == ["Show / hide cards", "Settings…", qt_tray.SEPARATOR, "Quit"]


def test_menu_rows_trims_a_leading_separator():
    # Only "quit": the separator would lead the menu, so it's trimmed away.
    assert qt_tray.menu_rows({"quit": 1}) == [("Quit", "quit")]


def test_menu_rows_never_ends_with_a_separator():
    rows = qt_tray.menu_rows({"pet": 1, "toggle": 1})   # settings+quit gone -> trailing sep
    assert rows[-1][0] is not qt_tray.SEPARATOR
    assert [label for label, _ in rows] == ["Pet…", "Show / hide cards"]


# --- QMenu build + click routing (offscreen) --------------------------------
def test_build_menu_shows_provided_rows_and_routes_clicks(app):
    fired: list[str] = []
    tray = qt_tray.QtSystemTray(
        on_toggle=lambda: fired.append("toggle"),
        on_settings=lambda: fired.append("settings"),
        on_quit=lambda: fired.append("quit"),
    )
    menu = tray._build_menu()
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts == ["Show / hide cards", "Settings…", "Quit"]   # no Pet… (no on_pet)

    next(a for a in menu.actions() if a.text() == "Settings…").trigger()
    assert fired == ["settings"]
    tray.dispose()


def test_show_toast_after_dispose_is_a_noop(app):
    tray = qt_tray.QtSystemTray(on_quit=lambda: None)
    tray.dispose()
    tray.show_toast("title", "message")   # must not raise


# --- manager toast routing through the notifier core ------------------------
def test_manager_toasts_once_per_fresh_notify(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path)

    toasts: list[tuple[str, str]] = []

    class _FakeTray:
        def show_toast(self, title, message):
            toasts.append((title, message))

    mgr._tray = _FakeTray()
    mgr._notify_prev = {}
    waiting = {"session_id": "s1", "state": "waiting", "ts": 1.0, "subagents": [],
               "notify": {"message": "Claude needs you", "type": "permission"}}

    mgr._on_sessions({"s1": waiting})
    assert toasts and "Claude needs you" in toasts[0][1]

    toasts.clear()
    mgr._on_sessions({"s1": waiting})     # unchanged notify -> no repeat toast
    assert toasts == []
