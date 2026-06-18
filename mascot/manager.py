"""The widget's process entry point and session-to-window manager.

Owns the single Tk root, polls the state directory, and spawns/cleans up one
:class:`~mascot.tkinter_app.MascotWindow` per live Claude session. Also wires the
Windows system-tray icon. Run with: ``python -m mascot`` (or ``run_mascot.py``).
"""
from __future__ import annotations

import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path

from . import config, icon, osplatform, pet_logic, pet_store, single_instance, state_store
from .tkinter_app import MascotWindow

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# How often the widget flushes the pet to pet.json. The pet updates every poll in
# memory; persistence is throttled (an award forces an out-of-band save) and
# decay-on-load reconstructs anything missed if the process dies between flushes.
PET_SAVE_INTERVAL_S = 10.0


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

        # System-tray icon (Windows only). Best-effort: any failure leaves the
        # widget fully working, just without a tray icon.
        self._cards_hidden = False
        self.tray = None
        if osplatform.IS_WINDOWS:
            try:
                from .tray import SystemTray
                self.tray = SystemTray(
                    tooltip="Claude Familiar",
                    on_toggle=self._on_tray_toggle,
                    on_pet=self._on_tray_pet,
                    on_settings=self._on_tray_settings,
                    on_quit=self._on_tray_quit,
                )
            except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
                print("[mascot] system tray unavailable:", exc)
                self.tray = None

        # The one global pet. The widget is its SOLE writer: it applies decay and
        # derives coin/XP events from polled session-state transitions. Best-effort
        # — any pet failure must leave the mascot itself fully working.
        now = time.time()
        try:
            self.pet = pet_store.load(pet_store.PET_PATH, now)
        except Exception as exc:  # noqa: BLE001
            print("[mascot] could not load pet:", exc)
            self.pet = pet_store.default_pet(now)
        self._pet_prev: dict[str, dict] = {}   # sid -> last session state (transitions)
        self._pet_last_tick = now
        self._pet_last_save = now
        self._pet_file_mtime = self._pet_mtime()
        self._pet_win = None                   # the Pet window, when open (tray)

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
                win = MascotWindow(self.root, sid, state, index,
                                   on_open_pet=self._open_pet_window,
                                   on_pet=self._on_pet_petted)
                self.windows[sid] = win
                if self._cards_hidden:        # honor a tray "hide" for new sessions
                    win.set_hidden(True)
            else:
                win.update_state(state, now)

        self._update_pet(states, now)
        self.root.after(500, self._refresh)

    # --- pet (Tamagotchi) -------------------------------------------------
    def _update_pet(self, states: dict[str, dict], now: float) -> None:
        """Advance the global pet from this poll: decay needs over real elapsed
        time and award coins/XP for session-state transitions, then persist
        (throttled). Wrapped so a pet failure never disrupts the mascot."""
        try:
            # Pick up edits made by a standalone Pet window (opened from Settings):
            # if pet.json changed under us, reload it (decay-on-load brings it to now).
            mtime = self._pet_mtime()
            if mtime is not None and mtime != self._pet_file_mtime:
                self.pet = pet_store.load(pet_store.PET_PATH, now)
                self._pet_file_mtime = mtime
                self._pet_last_tick = now      # load already decayed up to now

            elapsed = max(0.0, now - self._pet_last_tick)
            self._pet_last_tick = now
            # Energy drains while any session is busy and refills while all idle.
            working = any(s.get("state") in ("working", "thinking") for s in states.values())
            self.pet = pet_logic.decay(self.pet, elapsed, working)

            today = time.strftime("%Y-%m-%d", time.localtime(now))
            awarded = False
            for sid, state in states.items():
                prev = self._pet_prev.get(sid)
                if prev is None:
                    continue   # a new session has no transition yet
                events = pet_logic.events_for_transition(prev, state)
                # Daily first-prompt streak: the first new prompt of the day pays a
                # bonus. Claim it once per calendar day (persisted in last_prompt_date).
                if (pet_logic.started_prompt(prev, state)
                        and self.pet.get("last_prompt_date") != today):
                    self.pet = {**self.pet, "last_prompt_date": today}
                    events = [*events, pet_logic.FIRST_PROMPT_OF_DAY]
                if events:
                    self.pet = pet_logic.apply_events(self.pet, events, today=today)
                    awarded = True
            # Track only live sessions, so a closed card can't fire a stale transition.
            self._pet_prev = dict(states)

            # Push the latest pet to every card so its idle-face mood + hover tooltip
            # reflect the shared pet (the pet is one global creature, all cards mirror it).
            for win in self.windows.values():
                win.set_pet(self.pet)

            if awarded or (now - self._pet_last_save >= PET_SAVE_INTERVAL_S):
                self._save_pet(now)
        except Exception as exc:  # noqa: BLE001 — the pet must never crash the widget
            print("[mascot] pet update failed:", exc)

    def _save_pet(self, now: float) -> None:
        """Flush the pet to pet.json (best-effort). Records our own write's mtime so
        we don't mistake it for an external edit on the next poll."""
        try:
            self.pet = pet_store.save(pet_store.PET_PATH, self.pet, now)
            self._pet_last_save = now
            self._pet_file_mtime = self._pet_mtime()
        except Exception as exc:  # noqa: BLE001
            print("[mascot] could not save pet:", exc)

    @staticmethod
    def _pet_mtime() -> float | None:
        try:
            return pet_store.PET_PATH.stat().st_mtime
        except OSError:
            return None

    # --- pet window (opened from the tray, in this process) ---------------
    def _on_tray_pet(self) -> None:
        self._open_pet_window()

    def _open_pet_window(self) -> None:
        """Open (or focus) the Pet window as a Toplevel in this process, so it
        shares the live in-memory pet and persists through the single writer."""
        if self._pet_win is not None and getattr(self._pet_win, "_alive", False):
            self._pet_win.focus()
            return
        try:
            from .pet_window import PetWindow
            self._pet_win = PetWindow(
                self.root,
                load_pet=lambda: self.pet,
                save_pet=self._pet_window_save,
                on_care=self._celebrate_cards,
                on_close=self._on_pet_window_closed,
            )
        except Exception as exc:  # noqa: BLE001 — never let it crash the widget
            print("[mascot] could not open pet window:", exc)
            self._pet_win = None

    def _pet_window_save(self, pet: dict) -> dict:
        """Persist a Pet-window action through the single writer + record mtime."""
        self.pet = pet
        self._save_pet(time.time())
        return self.pet

    def _on_pet_window_closed(self) -> None:
        self._pet_win = None

    def _celebrate_cards(self) -> None:
        """Play the happy reaction + hearts on every card when the pet is fed/played."""
        for win in self.windows.values():
            try:
                win.celebrate()
            except Exception:  # noqa: BLE001
                pass

    def _on_pet_petted(self) -> None:
        """A card tap pets the pet: a small daily-capped coin/XP trickle."""
        try:
            today = time.strftime("%Y-%m-%d", time.localtime())
            self.pet = pet_logic.apply_events(self.pet, [pet_logic.PET], today=today)
            self._save_pet(time.time())
        except Exception as exc:  # noqa: BLE001
            print("[mascot] pet trickle failed:", exc)

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
            self._save_pet(time.time())      # flush the latest pet on any exit
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
