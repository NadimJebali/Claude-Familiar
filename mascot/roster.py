"""Pure session-roster reconciliation: which cards to create, update, destroy.

The manager polls the state directory each tick and must keep exactly one card
per live session. That create/update/destroy decision used to sit inline in the
poll loop; it is extracted here as a pure function — the previously-shown session
ids plus the fresh (liveness-filtered) snapshots in, window commands out — so it
is unit-testable without a GUI and the manager (Tk today, Qt after the port) can
be a thin shell around it.

Liveness — owner death, staleness, ``SessionEnd`` — is resolved upstream in
``state_store.load_states``, so a session that should vanish simply isn't in
``live``; this core only diffs against the previously-shown set. Kept Tk-free,
I/O-free and clock-free.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

State = dict[str, Any]


@dataclass(frozen=True)
class RosterCommands:
    """What the shell must do to reconcile its windows with the live sessions.

    The three groups are disjoint by session id and together account for every
    live and every previously-shown session:

    - ``create``  — a live session with no card yet, paired with the sorted
      position it should occupy (drives initial placement/stacking).
    - ``update``  — a live session that already has a card (refresh its state).
    - ``destroy`` — a previously-shown session that is no longer live.
    """

    create: list[tuple[str, State, int]]
    update: list[tuple[str, State]]
    destroy: list[str]


def reconcile(shown: Iterable[str], live: dict[str, State]) -> RosterCommands:
    """Diff the currently-shown session ids against the live snapshots.

    ``shown`` is any iterable of the session ids that currently have a card (e.g.
    the manager's window dict). ``live`` maps session id -> its fresh state,
    already filtered to the sessions whose card belongs on screen. Cards are
    ordered by session id; a created card carries its index in that order, so the
    shell can place it without any ordering logic of its own.
    """
    shown_set = set(shown)
    create: list[tuple[str, State, int]] = []
    update: list[tuple[str, State]] = []
    for index, sid in enumerate(sorted(live)):
        if sid in shown_set:
            update.append((sid, live[sid]))
        else:
            create.append((sid, live[sid], index))
    destroy = sorted(shown_set - live.keys())
    return RosterCommands(create=create, update=update, destroy=destroy)
