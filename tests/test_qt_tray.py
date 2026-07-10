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


def test_menu_rows_includes_notifications_between_settings_and_quit():
    rows = qt_tray.menu_rows(
        {"toggle": 1, "settings": 1, "notifications": 1, "quit": 1})
    labels = [label for label, _ in rows]
    assert labels == ["Show / hide cards", "Settings…", "Notifications",
                      qt_tray.SEPARATOR, "Quit"]


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


# --- the checkable Notifications row (#68) -----------------------------------
def test_notifications_row_is_checkable_and_routes_the_new_state(app):
    got: list[bool] = []
    tray = qt_tray.QtSystemTray(on_quit=lambda: None,
                                on_notifications=got.append, notifications_on=True)
    menu = tray._build_menu()
    action = next(a for a in menu.actions() if a.text() == "Notifications")
    assert action.isCheckable()
    assert action.isChecked()            # reflects the current setting
    action.trigger()                     # the user unchecks the row
    assert got == [False]                # callback gets the NEW state
    tray.dispose()


def test_notifications_row_reflects_an_off_setting(app):
    tray = qt_tray.QtSystemTray(on_quit=lambda: None,
                                on_notifications=lambda _on: None,
                                notifications_on=False)
    menu = tray._build_menu()
    action = next(a for a in menu.actions() if a.text() == "Notifications")
    assert action.isCheckable() and not action.isChecked()
    tray.dispose()


def test_omitting_the_notifications_callback_hides_the_row(app):
    tray = qt_tray.QtSystemTray(on_quit=lambda: None)
    menu = tray._build_menu()
    assert all(a.text() != "Notifications" for a in menu.actions())
    tray.dispose()


# --- the Theme submenu (#76) --------------------------------------------------
def test_theme_submenu_radio_checks_current_and_routes_the_choice(app):
    got: list[str] = []
    tray = qt_tray.QtSystemTray(on_quit=lambda: None,
                                on_theme=got.append, current_theme="classic")
    menu = tray._build_menu()
    sub = next(a.menu() for a in menu.actions() if a.text() == "Theme")
    labels = {a.text(): a for a in sub.actions()}
    assert set(labels) == {"Classic", "Compact"}
    assert labels["Classic"].isChecked() and not labels["Compact"].isChecked()

    labels["Compact"].trigger()               # the user picks Compact
    assert got == ["compact"]

    tray.set_theme("compact")                 # the app confirms the switch
    assert labels["Compact"].isChecked() and not labels["Classic"].isChecked()
    tray.dispose()


def test_omitting_the_theme_callback_hides_the_submenu(app):
    tray = qt_tray.QtSystemTray(on_quit=lambda: None)
    menu = tray._build_menu()
    assert all(a.text() != "Theme" for a in menu.actions())
    tray.dispose()


# --- manager toast routing through the notifier core ------------------------
class _FakeTray:
    def __init__(self, sink: list[tuple[str, str]]):
        self._sink = sink

    def show_toast(self, title, message):
        self._sink.append((title, message))


def _waiting_state(message: str) -> dict:
    return {"session_id": "s1", "state": "waiting", "ts": 1.0, "subagents": [],
            "notify": {"message": message, "type": "permission"}}


def test_manager_toasts_once_per_fresh_notify(app, tmp_path):
    mgr = qt_app.QtMascotApp(tmp_path)
    mgr._notifications_on = True          # unmuted (the default now ships muted)

    toasts: list[tuple[str, str]] = []
    mgr._tray = _FakeTray(toasts)
    mgr._notify_prev = {}
    waiting = _waiting_state("Claude needs you")

    mgr._on_sessions({"s1": waiting})
    assert toasts and "Claude needs you" in toasts[0][1]

    toasts.clear()
    mgr._on_sessions({"s1": waiting})     # unchanged notify -> no repeat toast
    assert toasts == []


def test_a_muted_manager_never_toasts_and_unmuting_skips_the_backlog(app, tmp_path,
                                                                     monkeypatch):
    # The gate fix (#68): native_notifications used to be a dead setting — toasts
    # fired unconditionally. Muted -> no toast; the edge tracker keeps running while
    # muted, so unmuting must NOT dump the stale notify as a fresh toast.
    from mascot import settings as settings_mod
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    mgr = qt_app.QtMascotApp(tmp_path)
    mgr._notifications_on = False

    toasts: list[tuple[str, str]] = []
    mgr._tray = _FakeTray(toasts)
    mgr._notify_prev = {}

    mgr._on_sessions({"s1": _waiting_state("old ask")})
    assert toasts == []                   # muted

    mgr._set_notifications(True)          # unmute via the tray row
    mgr._on_sessions({"s1": _waiting_state("old ask")})
    assert toasts == []                   # tracked while muted -> no backlog dump

    mgr._on_sessions({"s1": _waiting_state("new ask")})
    assert toasts and "new ask" in toasts[0][1]   # a genuinely fresh notify toasts


def test_set_notifications_persists_the_choice(app, tmp_path, monkeypatch):
    from mascot import settings as settings_mod
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", tmp_path / "settings.json")
    mgr = qt_app.QtMascotApp(tmp_path)

    mgr._set_notifications(True)
    assert mgr._notifications_on is True
    assert settings_mod.load_settings()["native_notifications"] is True

    mgr._set_notifications(False)
    assert mgr._notifications_on is False
    assert settings_mod.load_settings()["native_notifications"] is False
