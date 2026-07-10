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

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

# --- menu model (pure data) ------------------------------------------------
SEPARATOR: None = None
MENU_SPEC: tuple[tuple[str | None, str | None], ...] = (
    ("Pet…", "pet"),
    ("Show / hide cards", "toggle"),
    ("Settings…", "settings"),
    (SEPARATOR, None),
    ("Quit", "quit"),
)
# What a left-click (Trigger) runs where the platform supports it (Windows);
# elsewhere it's just a normal menu row, so behavior degrades gracefully.
DEFAULT_ACTION = "toggle"

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
      * ``on_toggle``   — left-click (where supported) or "Show / hide cards"
      * ``on_pet``      — the "Pet…" item
      * ``on_settings`` — the "Settings…" item
      * ``on_quit``     — the "Quit" item
    """

    def __init__(self, *, tooltip: str = "Claude Familiar",
                 on_toggle: Callable[[], None] | None = None,
                 on_pet: Callable[[], None] | None = None,
                 on_settings: Callable[[], None] | None = None,
                 on_quit: Callable[[], None] | None = None,
                 icon: QIcon | None = None) -> None:
        self._tray: QSystemTrayIcon | None = None   # sentinel: dispose() is safe if init fails
        provided = {"pet": on_pet, "toggle": on_toggle,
                    "settings": on_settings, "quit": on_quit}
        self._actions: dict[str, Callable[[], None]] = {
            k: cb for k, cb in provided.items() if cb is not None
        }

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
            action = menu.addAction(label)
            # Bind key per-iteration; QAction.triggered passes a `checked` bool.
            action.triggered.connect(
                lambda _checked=False, k=key: self._actions[k]())
        return menu

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
