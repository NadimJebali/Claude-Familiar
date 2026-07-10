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

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import QApplication

from . import (
    config,
    notifier,
    pet_actions,
    pet_service,
    roster,
    settings,
    single_instance,
    transcript,
    usage,
)
from .qt_card import QtCard
from .qt_ingest import SessionIngest
from .sprite_qt import QtPixmapRenderer

if TYPE_CHECKING:
    from .qt_pet_window import QtPetWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _ContextSignals(QObject):
    done = Signal(dict)


class _ContextTask(QRunnable):
    """One transcript-tailer poll off the UI thread (#72). The tailer's state is
    only ever touched here; the app serializes tasks (one in flight at a time)."""

    def __init__(self, tailer: transcript.TranscriptTailer,
                 paths: dict[str, str], signals: _ContextSignals) -> None:
        super().__init__()
        self._tailer = tailer
        self._paths = paths
        self._signals = signals

    def run(self) -> None:  # executes on a pool thread
        try:
            results = self._tailer.poll(self._paths)
        except Exception:  # noqa: BLE001 — a bad poll must never take down the pool
            results = {}
        self._signals.done.emit(results)


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
        # Live OS-toast mute (#68). Starts from the persisted setting (which the
        # dead-setting bug used to ignore — toasts fired unconditionally); the
        # tray's checkable Notifications row flips it live and persists it.
        self._notifications_on: bool = config.NATIVE_NOTIFICATIONS_ENABLED

        self._ingest = SessionIngest(state_dir)
        self._ingest.sessions_changed.connect(self._on_sessions)

        # Per-session context % from transcript tailing (#72). The tailer reads
        # files, so each poll runs on the thread pool; one in flight at a time
        # keeps its state single-threaded. Results land in _on_context.
        self._tailer = transcript.TranscriptTailer()
        self._context: dict[str, float] = {}
        self._context_inflight = False
        self._context_signals = _ContextSignals()
        self._context_signals.done.connect(self._on_context)

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
                on_notifications=self._set_notifications,
                notifications_on=self._notifications_on,
                on_quit=self._quit,
            )
        except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
            print("[mascot] system tray unavailable:", exc)

        # The presentation seam (#74): classic = one QtCard per session (below,
        # unchanged); compact = the one-panel session list, which consumes the
        # same pushes (sessions / usage / context) instead of the cards.
        self._theme = config.THEME
        self._compact = None
        if self._theme == "compact":
            try:
                from .qt_compact import CompactWindow
                self._compact = CompactWindow()
                self._compact.show()
            except Exception as exc:  # noqa: BLE001 — fall back to the classic cards
                print("[mascot] compact window unavailable:", exc)
                self._compact = None

        # Opt-in usage poller (#70): live 5h/weekly numbers without a CLI session.
        # Consent-first — built only when the setting is on; best-effort like the
        # tray (a poller failure never stops the widget).
        self._usage_poller = None
        if config.USAGE_API_ENABLED:
            try:
                from .usage_api import UsagePoller
                self._usage_poller = UsagePoller(self)
                self._usage_poller.start()
            except Exception as exc:  # noqa: BLE001 — never let the poller stop startup
                print("[mascot] usage poller unavailable:", exc)

    def start(self) -> None:
        self._ingest.start()

    def _on_sessions(self, live: dict) -> None:
        """Carry the roster core's create/update/destroy commands out to the cards,
        raise a native toast for any session that just started needing you, then
        advance the pet from this poll and push its look to every card."""
        now = time.time()
        if self._compact is not None:
            # Compact theme (#74): the one panel consumes the same pushes the
            # cards would. The pet keeps earning (its card loop is just empty)
            # and toasts stay edge-triggered; there are no per-session cards.
            self._compact.set_sessions(live)
            self._notify(live)
            self._update_pet(live, now)
            self._compact.set_usage(usage.load_usage())
            self._poll_context(live)
            return
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
        self._push_usage()
        self._poll_context(live)

    def _notify(self, live: dict) -> None:
        """Edge-triggered native toast when a session's ``notify`` first appears.
        Reuses the pure notifier core; the tray is the sink instead of plyer.

        Gated on the live mute (#68) — but the edge tracker keeps running while
        muted, so unmuting never dumps a stale notify as a fresh toast."""
        if self._tray is None or not self._notifications_on:
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

    def _set_notifications(self, on: bool) -> None:
        """The tray's Notifications row flipped: apply the mute live and persist it,
        so the choice survives a restart (and the Settings checkbox agrees)."""
        self._notifications_on = bool(on)
        try:
            settings.save_settings({"native_notifications": self._notifications_on})
        except OSError as exc:
            print("[mascot] could not persist the notifications setting:", exc)

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
            for card in self._cards.values():
                card.set_pet(result.pet)
        except Exception as exc:  # noqa: BLE001 — the pet must never crash the widget
            print("[mascot] pet update failed:", exc)

    def _poll_context(self, live: dict) -> None:
        """Kick one off-thread transcript poll for this snapshot's sessions (#72).
        Skipped while one is already in flight — the next snapshot re-kicks, so
        the gauge lags a tick at worst and the tailer stays single-threaded."""
        if self._context_inflight:
            return
        paths = {sid: str(state.get("transcript_path") or "")
                 for sid, state in live.items()}
        self._context_inflight = True
        QThreadPool.globalInstance().start(
            _ContextTask(self._tailer, paths, self._context_signals))

    def _on_context(self, results: dict) -> None:
        """Adopt a finished context poll and push each session's % to its card
        (or to the compact panel's row rings)."""
        self._context_inflight = False
        self._context = dict(results)
        if self._compact is not None:
            self._compact.set_context(self._context)
            return
        for sid, card in self._cards.items():
            card.set_context(self._context.get(sid))

    def _push_usage(self) -> None:
        """Push the account-global usage snapshot (5h + weekly) to every card each poll,
        so their bottom bars reflect the latest numbers. The read is mtime-cached and
        best-effort — a usage failure never disrupts the widget. Independent of the pet
        toggle (usage is Claude status, not a pet), so simple-mode cards show it too."""
        try:
            snapshot = usage.load_usage()
            for card in self._cards.values():
                card.set_usage(snapshot)
        except Exception as exc:  # noqa: BLE001 — usage must never crash the widget
            print("[mascot] usage update failed:", exc)

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
        if self._compact is not None:
            self._compact.hide() if self._cards_hidden else self._compact.show()
        for card in self._cards.values():
            card.hide() if self._cards_hidden else card.show()

    def _open_settings(self) -> None:
        try:
            subprocess.Popen([sys.executable, "-m", "mascot.qt_control_panel"],
                             cwd=str(PROJECT_ROOT))
        except OSError as exc:
            print("[mascot] could not open settings:", exc)

    def _quit(self) -> None:
        if self._usage_poller is not None:
            self._usage_poller.dispose()
            self._usage_poller = None
        if self._compact is not None:
            self._compact.close()
            self._compact = None
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
