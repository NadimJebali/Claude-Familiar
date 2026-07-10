"""Qt system-tray icon + menu and native toasts (issue #61).

Replaces the pystray tray (``mascot/tray.py``) **and** the plyer toasts (the sink
in ``mascot/notifier.py``) with one ``QSystemTrayIcon`` — the icon, its menu, and
the native toast all go through Qt. Because Qt delivers menu callbacks on the UI
thread, the off-thread dispatcher + pump the pystray tray needed is gone.

The menu **shape** stays pure data (``MENU_SPEC`` + :func:`menu_rows`) so it is
unit-testable without a QApplication; a row whose action has no callback is
dropped (so omitting ``on_pet`` hides "Pet…"), matching the pystray contract.
Construction is best-effort — no tray host just means the widget runs without an
icon. The tray icon is rendered by the Qt sprite renderer, so it needs no Tk.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

# --- menu model (pure data) ------------------------------------------------
SEPARATOR: None = None
MENU_SPEC: tuple[tuple[str | None, str | None], ...] = (
    ("Pet…", "pet"),
    ("Show / hide cards", "toggle"),
    ("Settings…", "settings"),
    ("Notifications", "notifications"),
    ("Theme", "theme"),
    (SEPARATOR, None),
    ("Quit", "quit"),
)
# What a left-click (Trigger) runs where the platform supports it (Windows);
# elsewhere it's just a normal menu row, so behavior degrades gracefully.
DEFAULT_ACTION = "toggle"
# Rows that render as checkable items: their callback takes the NEW checked state
# (bool) instead of no arguments — a live mute/unmute, not a command.
CHECKABLE_KEYS = frozenset({"notifications"})
# The Theme row renders as a radio submenu (#76): one entry per theme, the current
# one checked; its callback receives the picked theme value.
THEME_ROWS = (("Classic", "classic"), ("Compact", "compact"))

# How long the OS should keep a toast up (ms); mirrors notifier.NOTIFY_TIMEOUT_S.
TOAST_TIMEOUT_MS = 10_000


def menu_rows(actions: Mapping[str, object]) -> list[tuple[str | None, str | None]]:
    """The ``(label, key)`` rows to show for the provided action keys.

    Drops any row whose action isn't in ``actions`` (an omitted callback hides its
    item), then trims separators that would end up leading, trailing, or doubled —
    so dropping rows can never leave a stray divider. Pure: the menu's shape is
    testable without Qt.
    """
    kept: list[tuple[str | None, str | None]] = []
    for label, key in MENU_SPEC:
        if label is SEPARATOR:
            if kept and kept[-1][0] is not SEPARATOR:
                kept.append((SEPARATOR, None))
        elif key in actions:
            kept.append((label, key))
    while kept and kept[-1][0] is SEPARATOR:
        kept.pop()
    return kept


def _mascot_icon() -> QIcon:
    """The tray icon: the mascot rendered by the Qt sprite seam (no Tk)."""
    from . import config
    from .sprite_qt import QtPixmapRenderer, SpriteSpec

    r, g, b = config.STATE_COLORS["idle"]
    pixmap = QtPixmapRenderer().creature(
        SpriteSpec(stage="baby", state="idle", accent=f"#{r:02x}{g:02x}{b:02x}"), px=3)
    return QIcon(pixmap)


class QtSystemTray:
    """A notification-area icon with a popup menu and native toasts, via Qt.

    Callbacks (any may be omitted) run on the UI thread:
      * ``on_toggle``        — left-click (where supported) or "Show / hide cards"
      * ``on_pet``           — the "Pet…" item
      * ``on_settings``      — the "Settings…" item
      * ``on_notifications`` — the checkable "Notifications" row; receives the NEW
        checked state (a live mute/unmute), initial check from ``notifications_on``
      * ``on_theme``         — a pick in the radio "Theme" submenu; receives the
        chosen theme value, initial check from ``current_theme``. The app confirms
        an applied switch back via :meth:`set_theme`.
      * ``on_quit``          — the "Quit" item
    """

    def __init__(self, *, tooltip: str = "Claude Familiar",
                 on_toggle: Callable[[], None] | None = None,
                 on_pet: Callable[[], None] | None = None,
                 on_settings: Callable[[], None] | None = None,
                 on_notifications: Callable[[bool], None] | None = None,
                 notifications_on: bool = False,
                 on_theme: Callable[[str], None] | None = None,
                 current_theme: str = "classic",
                 on_quit: Callable[[], None] | None = None,
                 icon: QIcon | None = None) -> None:
        self._tray: QSystemTrayIcon | None = None   # sentinel: dispose() is safe if init fails
        provided: dict[str, Callable[..., None] | None] = {
            "pet": on_pet, "toggle": on_toggle, "settings": on_settings,
            "notifications": on_notifications, "theme": on_theme, "quit": on_quit}
        self._actions: dict[str, Callable[..., None]] = {
            k: cb for k, cb in provided.items() if cb is not None
        }
        # Initial checked state per provided checkable row (today: notifications).
        self._check_state: dict[str, bool] = (
            {"notifications": notifications_on} if on_notifications is not None else {})
        self._theme_current = current_theme
        self._theme_actions: dict[str, object] = {}   # value -> QAction (radio checks)

        tray = QSystemTrayIcon()
        tray.setToolTip(tooltip)
        tray.setIcon(icon if icon is not None else _mascot_icon())
        tray.setContextMenu(self._build_menu())
        if DEFAULT_ACTION in self._actions:
            tray.activated.connect(self._on_activated)
        tray.show()
        self._tray = tray

    def _build_menu(self) -> QMenu:
        menu = QMenu()
        for label, key in menu_rows(self._actions):
            if label is SEPARATOR:
                menu.addSeparator()
                continue
            if key == "theme":
                menu.addMenu(self._build_theme_menu(menu))
                continue
            action = menu.addAction(label)
            # Bind key per-iteration; QAction.triggered passes a `checked` bool.
            if key in CHECKABLE_KEYS:
                # A checkable row: Qt flips the check itself; the callback gets
                # the NEW state so the app can apply + persist it.
                action.setCheckable(True)
                action.setChecked(self._check_state.get(key, False))
                action.triggered.connect(
                    lambda checked=False, k=key: self._actions[k](bool(checked)))
            else:
                action.triggered.connect(
                    lambda _checked=False, k=key: self._actions[k]())
        return menu

    def _build_theme_menu(self, parent: QMenu) -> QMenu:
        """The radio Theme submenu (#76): one exclusive entry per theme; a pick
        routes the value to the app, which confirms back via :meth:`set_theme`."""
        sub = QMenu("Theme", parent)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for label, value in THEME_ROWS:
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(value == self._theme_current)
            group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, v=value: self._actions["theme"](v))
            self._theme_actions[value] = action
        return sub

    def set_theme(self, theme: str) -> None:
        """Reflect an applied theme switch in the submenu's radio checks."""
        self._theme_current = theme
        for value, action in self._theme_actions.items():
            action.setChecked(value == theme)  # type: ignore[attr-defined]

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._actions[DEFAULT_ACTION]()

    def show_toast(self, title: str, message: str) -> None:
        """Raise a native OS toast (no-op if the tray isn't up)."""
        if self._tray is not None:
            self._tray.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, TOAST_TIMEOUT_MS)

    def dispose(self) -> None:
        """Hide and drop the tray icon. Idempotent."""
        if self._tray is not None:
            self._tray.hide()
            self._tray = None
