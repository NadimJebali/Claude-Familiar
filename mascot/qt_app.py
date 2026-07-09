"""Qt widget entry point and session-to-card manager (issue #56, walking skeleton).

The Qt counterpart to ``mascot.manager``: it owns the ``QApplication``, subscribes
to :class:`~mascot.qt_ingest.SessionIngest` (event-driven, off-UI-thread reads),
and reconciles the live snapshots into one :class:`~mascot.qt_card.QtCard` per
session using the pure :func:`mascot.roster.reconcile`. A single-instance guard
(shared with the Tk widget) keeps a second copy from drawing duplicate cards.

Run the skeleton with::

    python -m mascot.qt_app

During the migration this coexists with the Tk widget (``python -m mascot``); the
cutover (#63) makes Qt the only entry point.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from . import roster, single_instance
from .qt_card import QtCard
from .qt_ingest import SessionIngest
from .sprite_qt import QtPixmapRenderer


class QtMascotApp(QObject):
    """Owns the cards; reconciles them against each fresh set of live snapshots."""

    def __init__(self, state_dir=None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._renderer = QtPixmapRenderer()
        self._cards: dict[str, QtCard] = {}
        self._ingest = SessionIngest(state_dir)
        self._ingest.sessions_changed.connect(self._on_sessions)

    def start(self) -> None:
        self._ingest.start()

    def _on_sessions(self, live: dict) -> None:
        """Carry the roster core's create/update/destroy commands out to the cards."""
        cmds = roster.reconcile(self._cards, live)
        for sid in cmds.destroy:
            self._cards.pop(sid).close()
        for sid, state, index in cmds.create:
            card = QtCard(sid, state, index, self._renderer)
            card.show()
            self._cards[sid] = card
        for sid, state in cmds.update:
            self._cards[sid].set_state(state)

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
