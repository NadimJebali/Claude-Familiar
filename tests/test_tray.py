"""Tests for the cross-platform tray (#18).

The tray itself is GUI/threading I/O (verified live), but its logic seams are pure
and tested here: the menu model, the off-thread→Tk-thread dispatcher, and the
mapping from a pystray menu action to the right callback. pystray/Pillow are
imported lazily by ``tray``, so these import cleanly without the deps; the one test
that builds a real pystray ``Menu`` skips when pystray is unavailable.
"""
import pytest

from mascot import tray

# --- menu model (pure) ----------------------------------------------------

def test_menu_spec_lists_the_four_actions_in_order_with_a_separator_before_quit():
    labels = [label for label, _ in tray.MENU_SPEC]
    keys = [key for _, key in tray.MENU_SPEC]
    assert labels == ["Pet…", "Show / hide cards", "Settings…", tray.SEPARATOR, "Quit"]
    assert keys == ["pet", "toggle", "settings", None, "quit"]


def test_default_action_is_toggle():
    # Left-click / activation (where supported) shows-or-hides the cards.
    assert tray.DEFAULT_ACTION == "toggle"
    assert tray.DEFAULT_ACTION in dict(tray.MENU_SPEC).values()


# --- _run_guarded ---------------------------------------------------------

def test_run_guarded_runs_the_callback():
    ran = []
    tray._run_guarded(lambda: ran.append(1))
    assert ran == [1]


def test_run_guarded_swallows_callback_errors():
    # A failing tray callback must never escape into the pump (would crash the loop).
    def boom():
        raise RuntimeError("nope")
    tray._run_guarded(boom)   # must not raise


# --- _TkDispatcher --------------------------------------------------------

def test_dispatcher_drain_runs_enqueued_callbacks_in_order():
    disp = tray._TkDispatcher()
    order = []
    disp.enqueue(lambda: order.append("a"))
    disp.enqueue(lambda: order.append("b"))
    assert order == []           # nothing runs until drained (on the Tk thread)
    disp.drain()
    assert order == ["a", "b"]


def test_dispatcher_drain_guards_errors_and_keeps_going():
    disp = tray._TkDispatcher()
    ran = []
    disp.enqueue(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    disp.enqueue(lambda: ran.append("after"))
    disp.drain()                 # must not raise; later callback still runs
    assert ran == ["after"]


def test_dispatcher_drain_on_empty_queue_is_a_noop():
    tray._TkDispatcher().drain()   # must not raise/block


# --- _make_handler (pystray action -> dispatch) ---------------------------

def test_handler_enqueues_the_mapped_callback_without_running_it():
    disp = tray._TkDispatcher()
    fired = []
    actions = {"pet": lambda: fired.append("pet"), "quit": lambda: fired.append("quit")}
    handler = tray._make_handler(disp, actions, "quit")

    handler(object(), object())  # pystray fires action(icon, item) on its OWN thread
    assert fired == []           # ...so nothing runs off the Tk thread yet
    disp.drain()                 # the Tk-thread pump runs it
    assert fired == ["quit"]


def test_handler_ignores_the_pystray_icon_and_item_args():
    disp = tray._TkDispatcher()
    fired = []
    handler = tray._make_handler(disp, {"pet": lambda: fired.append("pet")}, "pet")
    handler()                    # also callable with no args
    disp.drain()
    assert fired == ["pet"]


# --- _build_menu (needs pystray) ------------------------------------------

def test_build_menu_mirrors_the_spec_and_routes_clicks_to_callbacks():
    pystray = pytest.importorskip("pystray")
    disp = tray._TkDispatcher()
    fired = []
    actions = {k: (lambda k=k: fired.append(k)) for k in ("pet", "toggle", "settings", "quit")}

    menu = tray._build_menu(pystray, disp, actions)
    items = list(menu)

    visible = [it.text for it in items if it is not pystray.Menu.SEPARATOR]
    assert visible == ["Pet…", "Show / hide cards", "Settings…", "Quit"]
    assert sum(it is pystray.Menu.SEPARATOR for it in items) == 1
    # the toggle item is the platform default (left-click)
    toggle = next(it for it in items if it.text == "Show / hide cards")
    assert toggle.default is True

    # Clicking an item routes through the dispatcher to the matching callback.
    settings = next(it for it in items if it.text == "Settings…")
    settings(object())
    disp.drain()
    assert fired == ["settings"]


def test_build_menu_omits_pet_row_when_no_pet_callback_is_provided():
    # Simple hook-visualiser mode wires no on_pet, so the "Pet…" row must disappear
    # while every other row (and the separator) stays — without changing MENU_SPEC.
    pystray = pytest.importorskip("pystray")
    disp = tray._TkDispatcher()
    actions = {k: (lambda: None) for k in ("toggle", "settings", "quit")}  # no "pet"

    menu = tray._build_menu(pystray, disp, actions)
    visible = [it.text for it in menu if it is not pystray.Menu.SEPARATOR]

    assert visible == ["Show / hide cards", "Settings…", "Quit"]
    assert "Pet…" not in visible
    assert sum(it is pystray.Menu.SEPARATOR for it in menu) == 1  # separator preserved
    # MENU_SPEC itself is untouched — the full-shape contract still holds.
    assert next(label for label, _ in tray.MENU_SPEC) == "Pet…"
