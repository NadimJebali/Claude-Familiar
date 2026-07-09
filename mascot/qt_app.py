"""Qt widget entry point and session-to-card manager (issues #56, #61, #57, #60).

The Qt counterpart to ``mascot.manager``: it owns the ``QApplication``, subscribes
to :class:`~mascot.qt_ingest.SessionIngest` (event-driven, off-UI-thread reads),
reconciles the live snapshots into one :class:`~mascot.qt_card.QtCard` per session
via the pure :func:`mascot.roster.reconcile`, owns the system tray, and raises a
native toast when a session first needs the user. A single-instance guard (shared
with the Tk widget) keeps a second copy from drawing duplicate cards.

It is also the cards' :class:`~mascot.pet_host.PetHost`: each poll it advances the
one global pet through :class:`~mascot.pet_service.PetService` (the single writer)
and pushes the pet's look to every card, awards the petting trickle, and opens the
Pet window in this process so it shares the live pet.

Run the skeleton with::

    python -m mascot.qt_app

During the migration this coexists with the Tk widget (``python -m mascot``); the
cutover (#63) makes Qt the only entry point.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from . import config, notifier, pet_actions, pet_service, roster, single_instance
from .pet_view import pet_view
from .qt_card import QtCard
from .qt_ingest import SessionIngest
from .sprite_qt import QtPixmapRenderer

if TYPE_CHECKING:
    from .qt_pet_window import QtPetWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class QtMascotApp(QObject):
    """Owns the cards + tray + the one global pet; the cards' :class:`PetHost`.

    Reconciles the cards against each set of live snapshots and, each poll, advances
    the pet through :class:`~mascot.pet_service.PetService` (the single writer) and
    pushes its look to every card. Being the cards' host, it awards the petting
    trickle and opens the Pet window in this process, so it shares the live pet.
    """

    def __init__(self, state_dir=None, parent: QObject | None = None, *,
                 service: pet_service.PetService | None = None) -> None:
        super().__init__(parent)
        self._renderer = QtPixmapRenderer()
        self._cards: dict[str, QtCard] = {}
        self._cards_hidden = False
        self._notify_prev: dict[str, dict] = {}   # sid -> last state (toast edge-trigger)

        self._ingest = SessionIngest(state_dir)
        self._ingest.sessions_changed.connect(self._on_sessions)

        # The one global pet behind PetService — the per-poll decay -> award ->
        # milestone -> persist choreography over an injected store + clock; this
        # widget is its SOLE writer. Gated on the Tamagotchi setting: simple mode
        # builds no service (pet.json is never touched, preserving on-disk progress)
        # and the card is a plain hook visualiser. Best-effort — a construction
        # failure just drops pet features for the session. Injectable for tests.
        self._pet_service = service
        if self._pet_service is None and config.TAMAGOTCHI_ENABLED:
            try:
                self._pet_service = pet_service.PetService(
                    pet_service.PetStore(), now=time.time())
            except Exception as exc:  # noqa: BLE001 — a pet failure must not stop startup
                print("[mascot] could not start pet service:", exc)
                self._pet_service = None
        self._pet_window: QtPetWindow | None = None   # the Pet window, when open

        # Best-effort tray: no host just means no icon, widget still runs. "Pet…"
        # appears only when the pet is live (its callback opens the in-process Pet
        # window); simple mode omits the callback, so the pure menu drops the row.
        self._tray = None
        try:
            from .qt_tray import QtSystemTray
            self._tray = QtSystemTray(
                on_toggle=self._toggle_cards,
                on_pet=self.open_pet if self.pet_enabled else None,
                on_settings=self._open_settings,
                on_quit=self._quit,
            )
        except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
            print("[mascot] system tray unavailable:", exc)

    def start(self) -> None:
        self._ingest.start()

    def _on_sessions(self, live: dict) -> None:
        """Carry the roster core's create/update/destroy commands out to the cards,
        raise a native toast for any session that just started needing you, then
        advance the pet from this poll and push its look to every card."""
        now = time.time()
        cmds = roster.reconcile(self._cards, live)
        for sid in cmds.destroy:
            self._cards.pop(sid).close()
        for sid, state, index in cmds.create:
            card = QtCard(sid, state, index, self._renderer, pet_enabled=self.pet_enabled)
            card.petted.connect(self._on_petted)
            card.open_pet_requested.connect(self.open_pet)
            card.show()
            if self._cards_hidden:            # honor a tray "hide" for new sessions
                card.hide()
            self._cards[sid] = card
        for sid, state in cmds.update:
            self._cards[sid].set_state(state)
        self._notify(live)
        self._update_pet(live, now)

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

    def _on_petted(self, _session_id: str) -> None:
        """A card was petted: the happy hop already played on the card; award the
        daily-capped coin/XP trickle through PetService (the single writer). A no-op
        in simple mode, so the on-card coin-on-tap is gated on the live pet."""
        if self._pet_service is None:
            return
        try:
            pet_actions.pet_tap(self, time.time())
        except Exception as exc:  # noqa: BLE001 — a pet action must never crash the widget
            print("[mascot] pet tap failed:", exc)

    # --- pet (Tamagotchi) -------------------------------------------------
    def _update_pet(self, live: dict, now: float) -> None:
        """Advance the global pet from this poll via :class:`PetService`, then do the
        card I/O the service leaves us: celebrate every card on a newly earned
        milestone and push the pet's look (mood tint + stage/hat) to each. No-op in
        simple mode / on a pet failure — the widget itself always keeps running."""
        if self._pet_service is None:
            return
        try:
            result = self._pet_service.poll(live, now=now)
            if result.celebrate:
                self.notify_care()
            view = pet_view(result.pet, now=now)
            for card in self._cards.values():
                card.set_pet(view)
        except Exception as exc:  # noqa: BLE001 — the pet must never crash the widget
            print("[mascot] pet update failed:", exc)

    # --- PetHost: what the cards + Pet window need from their host ---------
    @property
    def pet_enabled(self) -> bool:
        """True when the pet is live (a PetService exists). Simple mode — and a rare
        pet-service startup failure — read as False, gating the paw button, petting
        coin trickle, and the tray "Pet…" row off this one flag."""
        return self._pet_service is not None

    def get_pet(self) -> dict[str, Any]:
        """The current global pet. ``{}`` only in the unreachable case where a window
        asks with no service — ``pet_enabled`` gates that."""
        return self._pet_service.pet if self._pet_service is not None else {}

    def save_pet(self, pet: dict[str, Any]) -> dict[str, Any]:
        """Persist a window/petting action through PetService — the single writer —
        and return the persisted pet."""
        if self._pet_service is None:
            return pet
        return self._pet_service.commit(pet, now=time.time())

    def notify_care(self) -> None:
        """Play the happy hop on every card when the pet is cared for."""
        for card in self._cards.values():
            try:
                card.celebrate()
            except Exception:  # noqa: BLE001
                pass

    def open_pet(self) -> None:
        """Open (or re-focus) the Pet window in this process, so it shares the live
        in-memory pet and persists through the single writer (this host)."""
        if self._pet_service is None:
            return
        if self._pet_window is not None and self._pet_window.isVisible():
            self._pet_window.raise_()
            self._pet_window.activateWindow()
            return
        try:
            from .qt_pet_window import QtPetWindow
            self._pet_window = QtPetWindow(
                self, renderer=self._renderer, on_close=self._on_pet_window_closed)
            self._pet_window.show()
        except Exception as exc:  # noqa: BLE001 — never let it crash the widget
            print("[mascot] could not open pet window:", exc)
            self._pet_window = None

    def _on_pet_window_closed(self) -> None:
        self._pet_window = None

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
        if self._pet_window is not None:
            self._pet_window.close()
            self._pet_window = None
        for card in list(self._cards.values()):
            card.close()
        self._cards.clear()
        if self._pet_service is not None:   # flush the latest pet on exit
            try:
                self._pet_service.flush(now=time.time())
            except Exception as exc:  # noqa: BLE001
                print("[mascot] pet flush failed:", exc)
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
