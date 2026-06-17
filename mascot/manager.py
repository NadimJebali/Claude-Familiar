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

from . import config, icon, osplatform, single_instance, state_store
from .tkinter_app import MascotWindow

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
                    on_settings=self._on_tray_settings,
                    on_quit=self._on_tray_quit,
                )
            except Exception as exc:  # noqa: BLE001 — never let the tray stop startup
                print("[mascot] system tray unavailable:", exc)
                self.tray = None

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
                win = MascotWindow(self.root, sid, state, index)
                self.windows[sid] = win
                if self._cards_hidden:        # honor a tray "hide" for new sessions
                    win.set_hidden(True)
            else:
                win.update_state(state, now)

        self.root.after(500, self._refresh)

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
