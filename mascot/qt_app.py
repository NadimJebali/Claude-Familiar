"""Qt widget entry point and session-to-card manager (issues #56, #61).

The Qt counterpart to ``mascot.manager``: it owns the ``QApplication``, subscribes
to :class:`~mascot.qt_ingest.SessionIngest` (event-driven, off-UI-thread reads),
reconciles the live snapshots into one :class:`~mascot.qt_card.QtCard` per session
via the pure :func:`mascot.roster.reconcile`, owns the system tray, and raises a
native toast when a session first needs the user. A single-instance guard (shared
with the Tk widget) keeps a second copy from drawing duplicate cards.

Run the skeleton with::

    python -m mascot.qt_app

During the migration this coexists with the Tk widget (``python -m mascot``); the
cutover (#63) makes Qt the only entry point.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from . import notifier, roster, single_instance
from .qt_card import QtCard
from .qt_ingest import SessionIngest
from .sprite_qt import QtPixmapRenderer

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class QtMascotApp(QObject):
    """Owns the cards + tray; reconciles them against each set of live snapshots."""

    def __init__(self, state_dir=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._renderer = QtPixmapRenderer()
        self._cards: dict[str, QtCard] = {}
        self._cards_hidden = False
        self._notify_prev: dict[str, dict] = {}   # sid -> last state (toast edge-trigger)

        self._ingest = SessionIngest(state_dir)
        self._ingest.sessions_changed.connect(self._on_sessions)

        # Best-effort tray: no host just means no icon, widget still runs. "Pet…" is
        # omitted (no on_pet) until the Qt Pet window (#60), so its row is dropped.
        self._tray = None
        try:
            from .qt_tray import QtSystemTray
            self._tray = QtSystemTray(
                on_toggle=self._toggle_cards,
                on_settings=self._open_settings,
                on_quit=self._quit,
            )
        except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
            print("[mascot] system tray unavailable:", exc)

    def start(self) -> None:
        self._ingest.start()

    def _on_sessions(self, live: dict) -> None:
        """Carry the roster core's create/update/destroy commands out to the cards,
        then raise a native toast for any session that just started needing you."""
        cmds = roster.reconcile(self._cards, live)
        for sid in cmds.destroy:
            self._cards.pop(sid).close()
        for sid, state, index in cmds.create:
            card = QtCard(sid, state, index, self._renderer)
            card.show()
            if self._cards_hidden:            # honor a tray "hide" for new sessions
                card.hide()
            self._cards[sid] = card
        for sid, state in cmds.update:
            self._cards[sid].set_state(state)
        self._notify(live)

    def _notify(self, live: dict) -> None:
        """Edge-triggered native toast when a session's ``notify`` first appears.
        Reuses the pure notifier core; the tray is the sink instead of plyer."""
        if self._tray is None:
            self._notify_prev = dict(live)
            return
        try:
            for _sid, notify in notifier.fresh_notifications(self._notify_prev, live):
                toast = notifier.toast_for(notify)
                if toast is not None:
                    self._tray.show_toast(*toast)
        except Exception as exc:  # noqa: BLE001 — a toast must never crash the widget
            print("[mascot] toast failed:", exc)
        self._notify_prev = dict(live)

    # --- tray callbacks (run on the UI thread) ---------------------------
    def _toggle_cards(self) -> None:
        self._cards_hidden = not self._cards_hidden
        for card in self._cards.values():
            card.hide() if self._cards_hidden else card.show()

    def _open_settings(self) -> None:
        try:
            subprocess.Popen([sys.executable, "-m", "mascot.control_panel"],
                             cwd=str(PROJECT_ROOT))
        except OSError as exc:
            print("[mascot] could not open settings:", exc)

    def _quit(self) -> None:
        for card in list(self._cards.values()):
            card.close()
        self._cards.clear()
        if self._tray is not None:
            self._tray.dispose()
            self._tray = None
        app = QApplication.instance()
        if app is not None:
            app.quit()

    @property
    def cards(self) -> dict[str, QtCard]:
        return self._cards


def main() -> None:
    # One widget at a time — a second would draw a duplicate card per session.
    guard = single_instance.acquire()
    if guard is None:
        print("[mascot] another Claude Familiar widget is already running; exiting.")
        return
    app = QApplication(sys.argv)
    mascot = QtMascotApp()
    mascot.start()
    print("[mascot] Qt widget started (walking skeleton)")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
