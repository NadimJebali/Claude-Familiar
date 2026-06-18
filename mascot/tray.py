"""Cross-platform system-tray icon + menu via pystray (ADR-0001).

Tkinter has no native tray support. Earlier this was a Windows-only ctypes
implementation; now it uses **pystray** (with Pillow for the icon image) so the
tray works on Windows, Linux and macOS from one code path.

Threading model — the important part:
  pystray runs the tray on its **own** thread, and menu callbacks fire there.
  Tkinter is not thread-safe, so callbacks must not touch Tk from that thread.
  Instead the pystray thread only ever *enqueues* the chosen callback onto a
  thread-safe queue (`_TkDispatcher`), and a small ``root.after`` pump — scheduled
  on the Tk thread — drains the queue and runs each callback **on the Tk thread**.
  So the manager's callbacks still run on the Tk thread and may touch Tk safely,
  exactly as before.

pystray and Pillow are imported lazily (only when a tray is actually created), so
this module stays importable — and its pure menu/dispatch logic stays unit-testable
— even where those packages aren't installed. Construction is best-effort: any
failure (missing deps, no tray host) leaves the widget fully working without an
icon (see ``manager``).
"""
from __future__ import annotations

import io
import queue
from collections.abc import Callable

from . import icon as app_icon

# --- menu model (pure data) ------------------------------------------------
# (label, action key) in display order; a None label is a separator. Kept as data
# so the menu's shape is unit-testable without pystray or Tk.
SEPARATOR = None
MENU_SPEC: tuple[tuple[str | None, str | None], ...] = (
    ("Pet…", "pet"),
    ("Show / hide cards", "toggle"),
    ("Settings…", "settings"),
    (SEPARATOR, None),
    ("Quit", "quit"),
)
# The "default" item is what a left-click / activation triggers where the platform
# supports it (Windows). Elsewhere (e.g. Linux AppIndicator) a click opens the menu
# and this item is just a normal entry — so the behavior degrades gracefully.
DEFAULT_ACTION = "toggle"

# How often the Tk thread drains queued tray callbacks. 80ms is imperceptible for a
# menu click and negligible overhead when the queue is empty.
PUMP_INTERVAL_MS = 80


def _run_guarded(callback: Callable[[], None]) -> None:
    """Run a tray callback, never letting its error escape the pump."""
    try:
        callback()
    except Exception as exc:  # noqa: BLE001 — a tray click must not crash the widget
        print("[mascot] tray callback error:", exc)


class _TkDispatcher:
    """Marshals tray callbacks from the pystray thread onto the Tk thread.

    ``enqueue`` is thread-safe and is called from the pystray thread; ``drain`` runs
    the queued callbacks (guarding errors) and is called on the Tk thread by the
    ``root.after`` pump. Splitting the two keeps Tk single-threaded.
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[Callable[[], None]] = queue.Queue()

    def enqueue(self, callback: Callable[[], None]) -> None:
        self._queue.put(callback)

    def drain(self) -> None:
        while True:
            try:
                callback = self._queue.get_nowait()
            except queue.Empty:
                return
            _run_guarded(callback)


def _make_handler(dispatcher: _TkDispatcher, actions: dict[str, Callable[[], None]],
                  action_key: str) -> Callable[..., None]:
    """A pystray menu action that enqueues ``actions[action_key]`` for the Tk thread.

    pystray invokes the action on its own thread as ``action(icon, item)``; we accept
    (and ignore) those args and only enqueue, so nothing touches Tk off-thread.
    """
    def handler(_icon=None, _item=None) -> None:
        dispatcher.enqueue(actions[action_key])
    return handler


def _build_menu(pystray, dispatcher: _TkDispatcher,
                actions: dict[str, Callable[[], None]]):
    """Translate MENU_SPEC into a pystray ``Menu`` (needs pystray; thin shell).

    A row whose action key has no callback in ``actions`` is dropped — so omitting a
    callback (e.g. ``on_pet`` in simple hook-visualiser mode) hides that menu item
    without touching the static MENU_SPEC contract."""
    items = []
    for label, action_key in MENU_SPEC:
        if label is SEPARATOR:
            items.append(pystray.Menu.SEPARATOR)
        elif action_key in actions:
            items.append(pystray.MenuItem(
                label,
                _make_handler(dispatcher, actions, action_key),
                default=(action_key == DEFAULT_ACTION),
            ))
    return pystray.Menu(*items)


class SystemTray:
    """A notification-area icon with a small popup menu, backed by pystray.

    Callbacks (any may be omitted) run on the Tk thread:
      * ``on_toggle``   — left-click (where supported) or "Show / hide cards"
      * ``on_pet``      — the "Pet…" item
      * ``on_settings`` — the "Settings…" item
      * ``on_quit``     — the "Quit" item
    """

    def __init__(self, root, tooltip: str = "Claude Familiar", *,
                 on_toggle=None, on_pet=None, on_settings=None, on_quit=None) -> None:
        # Sentinels first so dispose() is safe even if construction fails.
        self._icon = None
        self._stopped = False

        self._root = root
        self._dispatcher = _TkDispatcher()
        # Only register callbacks that were actually provided; an omitted one drops
        # its menu row (see _build_menu). This is how simple mode (no on_pet) hides
        # the "Pet…" item.
        provided = {"pet": on_pet, "toggle": on_toggle,
                    "settings": on_settings, "quit": on_quit}
        self._actions: dict[str, Callable[[], None]] = {
            key: cb for key, cb in provided.items() if cb is not None
        }

        import pystray

        menu = _build_menu(pystray, self._dispatcher, self._actions)
        self._icon = pystray.Icon("claude_familiar", icon=self._load_image(),
                                  title=tooltip, menu=menu)

        # Drain queued callbacks on the Tk thread. This first schedule runs on the
        # Tk thread (we're constructed there) and the pump reschedules itself.
        self._root.after(PUMP_INTERVAL_MS, self._pump)
        self._icon.run_detached()

    @staticmethod
    def _load_image():
        """The mascot art as a Pillow image (reuses the single-source-of-truth PNG)."""
        from PIL import Image
        return Image.open(io.BytesIO(app_icon._png_bytes()))

    def _pump(self) -> None:
        """Run any queued tray callbacks on the Tk thread, then reschedule."""
        if self._stopped:
            return
        self._dispatcher.drain()
        self._root.after(PUMP_INTERVAL_MS, self._pump)

    def dispose(self) -> None:
        """Stop the tray icon and the pump. Idempotent."""
        self._stopped = True
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001 — teardown must never raise
                pass
            self._icon = None
