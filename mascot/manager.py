"""The widget's process entry point and session-to-window manager.

Owns the single Tk root, polls the state directory, and spawns/cleans up one
:class:`~mascot.tkinter_app.MascotWindow` per live Claude session. Also wires the
cross-platform system-tray icon. Run with: ``python -m mascot`` (or ``run_mascot.py``).
"""
from __future__ import annotations

import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from typing import TYPE_CHECKING

from . import (
    config,
    icon,
    notifier,
    pet_service,
    single_instance,
    state_store,
    usage,
)
from .tkinter_app import MascotWindow

if TYPE_CHECKING:
    from .pet_window import PetWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _pythonw() -> Path:
    """pythonw.exe (no console window) next to the running interpreter, if any."""
    candidate = Path(sys.executable).with_name("pythonw.exe")
    return candidate if candidate.exists() else Path(sys.executable)


class MascotManager:
    """Owns the single Tk root; spawns one Toplevel window per live session."""

    def __init__(self) -> None:
        self.windows: dict[str, MascotWindow] = {}
        self.root = tk.Tk()
        self.root.withdraw()  # hidden controller window
        self.root.title("Mascot Manager")
        icon.apply(self.root)  # mascot icon for the taskbar / any child windows

        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        print("[mascot] state dir:", config.STATE_DIR)
        print("[mascot] tkinter app started")

        # System-tray icon (cross-platform via pystray). Best-effort: any failure
        # (missing deps, no tray host) leaves the widget fully working, just without
        # a tray icon. Callbacks are marshaled back onto this Tk thread by SystemTray.
        # Tamagotchi on/off. When off the card is a *simple hook visualiser*: the pet
        # is never loaded, ticked, pushed, or wired into the cards/tray. Read once at
        # startup (restart-gated, like the other settings).
        self._pet_enabled = config.TAMAGOTCHI_ENABLED
        # Native OS toasts on/off (the in-app bubble is unaffected). Read once at
        # startup, restart-gated like the pet toggle above.
        self._notify_enabled = config.NATIVE_NOTIFICATIONS_ENABLED

        self._cards_hidden = False
        self.tray = None
        try:
            from .tray import SystemTray
            self.tray = SystemTray(
                self.root,
                tooltip="Claude Familiar",
                on_toggle=self._on_tray_toggle,
                # Omit the pet callback in simple mode so the tray drops "Pet…".
                on_pet=self._on_tray_pet if self._pet_enabled else None,
                on_settings=self._on_tray_settings,
                on_quit=self._on_tray_quit,
            )
        except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
            print("[mascot] system tray unavailable:", exc)
            self.tray = None

        # The one global pet lives behind PetService — the per-poll choreography of
        # decay -> award -> milestone -> persist around an injected store + clock. The
        # widget is its SOLE writer. Best-effort: any pet failure must leave the mascot
        # itself fully working, so a construction failure simply drops pet features for
        # the session (``None``). In simple mode there is no service at all — pet.json is
        # never touched, so on-disk progress is preserved for the next enable.
        now = time.time()
        self._pet_service: pet_service.PetService | None = None
        if self._pet_enabled:
            try:
                self._pet_service = pet_service.PetService(pet_service.PetStore(), now=now)
            except Exception as exc:  # noqa: BLE001
                print("[mascot] could not start pet service:", exc)
                self._pet_service = None
        self._pet_win: PetWindow | None = None   # the Pet window, when open (tray)
        self._notify_prev: dict[str, dict] = {}  # sid -> last state (native-toast edge)

        self.root.after(500, self._refresh)

    def _refresh(self) -> None:
        now = time.time()
        states = state_store.load_states(config.STATE_DIR, now)

        for sid in list(self.windows):
            if sid not in states:
                self.windows[sid].close()
                del self.windows[sid]

        for index, (sid, state) in enumerate(sorted(states.items())):
            win = self.windows.get(sid)
            if win is None:
                # The manager is the cards' PetHost; its pet_enabled (a live service)
                # gates the paw button, tooltip, and coin-on-tap in simple mode.
                win = MascotWindow(self.root, sid, state, index, host=self)
                self.windows[sid] = win
                if self._cards_hidden:        # honor a tray "hide" for new sessions
                    win.set_hidden(True)
            else:
                win.update_state(state, now)

        self._notify_sessions(states)
        self._update_pet(states, now)
        self._push_usage()
        self.root.after(500, self._refresh)

    # --- native OS notifications (#19) ------------------------------------
    def _notify_sessions(self, states: dict[str, dict]) -> None:
        """Raise a native OS toast when a session's ``notify`` first appears, to
        complement the in-app bubble. Edge-triggered (so repeated polls don't
        re-toast) and best-effort (a toast failure never disrupts the widget).
        No-op when native notifications are switched off in Settings."""
        if not self._notify_enabled:
            return
        try:
            for _sid, notify in notifier.fresh_notifications(self._notify_prev, states):
                notifier.emit(notify)
        except Exception as exc:  # noqa: BLE001 — a toast must never crash the widget
            print("[mascot] notification failed:", exc)
        self._notify_prev = dict(states)

    # --- usage bars (5h / weekly) -----------------------------------------
    def _push_usage(self) -> None:
        """Push the account-global usage snapshot (5h + weekly limits) to every
        card each poll, so their bottom bars reflect the latest numbers. The read
        is mtime-cached and best-effort — a usage failure never disrupts the
        mascot. Independent of the pet toggle (usage is Claude status, not a pet)."""
        try:
            snapshot = usage.load_usage()
            for win in self.windows.values():
                win.set_usage(snapshot)
        except Exception as exc:  # noqa: BLE001 — usage must never crash the widget
            print("[mascot] usage update failed:", exc)

    # --- pet (Tamagotchi) -------------------------------------------------
    def _update_pet(self, states: dict[str, dict], now: float) -> None:
        """Advance the global pet from this poll via :class:`PetService`, then do the
        Tk-side I/O the service leaves to us: celebrate the cards on a newly earned
        milestone and push the advanced pet to every card. Wrapped so a pet failure
        never disrupts the mascot. No-op when the pet is off or the service failed to
        start (simple hook-visualiser mode never creates one)."""
        if self._pet_service is None:
            return
        try:
            result = self._pet_service.poll(states, now=now)
            if result.celebrate:
                self.notify_care()
            # Push the latest pet to every card so its idle-face mood + hover tooltip
            # reflect the shared pet (the pet is one global creature, all cards mirror it).
            for win in self.windows.values():
                win.set_pet(result.pet)
        except Exception as exc:  # noqa: BLE001 — the pet must never crash the widget
            print("[mascot] pet update failed:", exc)

    # --- pet window (opened from the tray, in this process) ---------------
    def _on_tray_pet(self) -> None:
        self.open_pet()

    def _on_pet_window_closed(self) -> None:
        self._pet_win = None

    # --- PetHost: what the cards + Pet window need from their host ---------
    @property
    def pet_enabled(self) -> bool:
        """True when the pet is live (a PetService exists). Simple mode — and a rare
        pet-service startup failure — read as False, so the windows gate the paw
        button, tooltip, and coin-on-tap off this one flag."""
        return self._pet_service is not None

    def get_pet(self) -> dict:
        """The current global pet (the Pet window reads it live). ``{}`` only in the
        unreachable case where a window asks with no service — pet_enabled gates that."""
        return self._pet_service.pet if self._pet_service is not None else {}

    def save_pet(self, pet: dict) -> dict:
        """Persist a window action (buy/feed/equip/pet-tap) through PetService — the
        single writer — and return the persisted pet."""
        if self._pet_service is None:
            return pet
        return self._pet_service.commit(pet, now=time.time())

    def notify_care(self) -> None:
        """Play the happy reaction + hearts on every card when the pet is cared for."""
        for win in self.windows.values():
            try:
                win.celebrate()
            except Exception:  # noqa: BLE001
                pass

    def open_pet(self) -> None:
        """Open (or focus) the Pet window as a Toplevel in this process, so it shares
        the live in-memory pet and persists through the single writer (this host)."""
        if self._pet_service is None:
            return
        if self._pet_win is not None and getattr(self._pet_win, "_alive", False):
            self._pet_win.focus()
            return
        try:
            from .pet_window import PetWindow
            self._pet_win = PetWindow(self.root, host=self, on_close=self._on_pet_window_closed)
        except Exception as exc:  # noqa: BLE001 — never let it crash the widget
            print("[mascot] could not open pet window:", exc)
            self._pet_win = None

    # --- system-tray callbacks (run on the Tk thread) ---------------------
    def _on_tray_toggle(self) -> None:
        """Show / hide every card at once."""
        self._cards_hidden = not self._cards_hidden
        for win in self.windows.values():
            win.set_hidden(self._cards_hidden)

    def _on_tray_settings(self) -> None:
        """Open the settings panel as its own process, like the rest of the app."""
        try:
            subprocess.Popen([str(_pythonw()), "-m", "mascot.control_panel"],
                             cwd=str(PROJECT_ROOT))
        except OSError as exc:
            print("[mascot] could not open settings:", exc)

    def _on_tray_quit(self) -> None:
        """Close every card, drop the tray icon, and end the main loop."""
        for win in list(self.windows.values()):
            win.close()
        self.windows.clear()
        if self.tray is not None:
            self.tray.dispose()
            self.tray = None
        self.root.quit()

    def run(self) -> None:
        try:
            self.root.mainloop()
        finally:
            if self._pet_service is not None:   # flush the latest pet on any exit
                self._pet_service.flush(now=time.time())   # (simple mode has no service)
            if self.tray is not None:        # also covers a normal window-close exit
                self.tray.dispose()
                self.tray = None


def main() -> None:
    # Only one widget process at a time. A second one would poll the same state
    # dir and draw a duplicate, exactly-overlapping card for every session.
    guard = single_instance.acquire()
    if guard is None:
        print("[mascot] another Claude Familiar widget is already running; exiting.")
        return
    MascotManager().run()


if __name__ == "__main__":
    main()
