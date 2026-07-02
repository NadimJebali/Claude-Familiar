"""Per-poll pet I/O choreography for the widget (Deepen 2/6, #37).

Lifts the manager's untested per-poll sequence — pick up an external ``pet.json``
edit, advance :func:`mascot.pet_logic.tick`, grant milestones, and persist
(throttled, but forced by an award or a new milestone) — behind :meth:`PetService.poll`.

The **store** (a port over :mod:`mascot.pet_store`) and the **clock** (an explicit
``now``) are injected, so the service is a pure choreographer: the manager keeps only
the Tk/card I/O, and a fake store plus a supplied ``now`` drive the whole sequence
deterministically in tests, with no Tk root.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, NamedTuple, Protocol

from . import cosmetics, pet_logic, pet_store

# How often the widget flushes the pet to the store. The pet updates every poll in
# memory; persistence is throttled (an award forces an out-of-band save) and
# decay-on-load reconstructs anything missed if the process dies between flushes.
PET_SAVE_INTERVAL_S = 10.0


class Store(Protocol):
    """The persistence port the service drives — a seam over :mod:`mascot.pet_store`.

    ``load``/``save`` apply decay and stamp ``last_seen`` for a given ``now``; ``mtime``
    is the backing file's modification time (``None`` when absent), which the service
    watches to pick up edits made by a standalone Pet window. A test double implements
    the same three methods to run the whole sequence without touching disk.
    """

    def load(self, now: float) -> dict[str, Any]: ...
    def save(self, pet: dict[str, Any], now: float) -> dict[str, Any]: ...
    def mtime(self) -> float | None: ...


class PetStore:
    """The production :class:`Store`: :mod:`mascot.pet_store` bound to one pet.json
    path. Decay-on-load and the atomic write live in ``pet_store``; this only binds
    the path and exposes the file's mtime for the service's edit-detection."""

    def __init__(self, path: Path = pet_store.PET_PATH) -> None:
        self._path = path

    def load(self, now: float) -> dict[str, Any]:
        return pet_store.load(self._path, now)

    def save(self, pet: dict[str, Any], now: float) -> dict[str, Any]:
        return pet_store.save(self._path, pet, now)

    def mtime(self) -> float | None:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None


class PollResult(NamedTuple):
    """What one :meth:`PetService.poll` yields the manager: the advanced ``pet`` to
    push to every card, and ``celebrate`` — True only when this poll earned a new
    milestone piece, the manager's cue to play the hearts reaction."""

    pet: dict[str, Any]
    celebrate: bool


class PetService:
    """Owns the per-poll pet sequence around an injected store + clock."""

    def __init__(self, store: Store, *, now: float) -> None:
        self._store = store
        self._pet = store.load(now)
        self._prev_states: dict[str, dict[str, Any]] = {}
        self._last_tick = now
        self._last_save = now
        self._file_mtime = store.mtime()

    @property
    def pet(self) -> dict[str, Any]:
        """The pet the service currently owns (for the Pet window + petting trickle)."""
        return self._pet

    def commit(self, pet: dict[str, Any], *, now: float) -> dict[str, Any]:
        """Adopt an externally-mutated pet (a Pet-window action or a petting trickle)
        and flush it immediately, so the single writer stays the source of truth."""
        self._pet = pet
        self._save(now)
        return self._pet

    def flush(self, *, now: float) -> dict[str, Any]:
        """Persist the current pet now (the widget's flush-on-exit)."""
        self._save(now)
        return self._pet

    def poll(self, states: dict[str, dict[str, Any]], *, now: float) -> PollResult:
        self._maybe_reload(now)
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now
        # Energy drains while any session is busy and refills while all idle.
        working = any(s.get("state") in ("working", "thinking") for s in states.values())
        today = time.strftime("%Y-%m-%d", time.localtime(now))
        # The pure per-poll seam owns decay -> first-prompt gate -> award; we feed it
        # our last-seen snapshot so only sessions still present can fire a transition.
        self._pet, awarded = pet_logic.tick(
            self._pet, self._prev_states, states,
            elapsed=elapsed, working=working, today=today,
        )
        # Track only live sessions, so a closed card can't replay a stale transition.
        self._prev_states = dict(states)

        # Grant any milestone wardrobe pieces the pet's history has earned (idempotent).
        # A newly earned piece is a moment: celebrate the cards and force the save.
        self._pet, new_pieces = cosmetics.grant_milestones(self._pet)
        celebrate = bool(new_pieces)

        # Save on an award or new milestone (out of band), else once the throttle elapses.
        if awarded or new_pieces or (now - self._last_save >= PET_SAVE_INTERVAL_S):
            self._save(now)
        return PollResult(pet=self._pet, celebrate=celebrate)

    def _maybe_reload(self, now: float) -> None:
        """Pick up an edit made by a standalone Pet window: if the store's mtime
        changed under us, reload (load already decays up to ``now``). Our own writes
        record their mtime in :meth:`_save`, so they're never mistaken for an edit."""
        mtime = self._store.mtime()
        if mtime is not None and mtime != self._file_mtime:
            self._pet = self._store.load(now)
            self._file_mtime = mtime
            self._last_tick = now   # load already decayed up to now

    def _save(self, now: float) -> None:
        """Flush the pet through the store and reset the throttle clock. Records the
        write's mtime so the next :meth:`_maybe_reload` won't reload our own write."""
        self._pet = self._store.save(self._pet, now)
        self._last_save = now
        self._file_mtime = self._store.mtime()
