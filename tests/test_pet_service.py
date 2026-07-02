"""Tests for PetService: the per-poll pet I/O choreography (Deepen 2/6, #37).

PetService lifts the manager's untested per-poll sequence — pick up an external
pet.json edit, advance pet_logic.tick, grant milestones, and persist (throttled, but
forced by an award or a new milestone) — behind poll(states, now). The store and clock
are injected, so a fake store (recording saves, with a settable mtime) and an explicit
`now` drive it deterministically, no Tk root.
"""
from __future__ import annotations

from mascot import pet_service, pet_store


class FakeStore:
    """In-memory store port: keeps the pet, records every save, and exposes an mtime
    that a save bumps (like a real file write) and a test can bump to fake an edit."""

    def __init__(self, pet: dict) -> None:
        self._pet = dict(pet)
        self.saves: list[dict] = []
        self.loads = 0
        self._mtime = 1.0

    def load(self, now: float) -> dict:
        self.loads += 1
        return dict(self._pet)

    def save(self, pet: dict, now: float) -> dict:
        self._pet = dict(pet)
        self.saves.append(dict(pet))
        self._mtime += 1.0
        return dict(pet)

    def mtime(self) -> float | None:
        return self._mtime

    def external_edit(self, pet: dict) -> None:
        """Simulate a standalone Pet window writing pet.json under the manager."""
        self._pet = dict(pet)
        self._mtime += 1.0


def _pet(**over) -> dict:
    p = pet_store.default_pet(1000.0)
    p.update(over)
    return p


# --- tracer bullet -----------------------------------------------------------
def test_poll_returns_the_advanced_pet_and_no_celebrate_by_default():
    svc = pet_service.PetService(FakeStore(_pet()), now=1000.0)
    result = svc.poll({}, now=1000.0)
    assert isinstance(result.pet, dict)
    assert result.celebrate is False


# --- a completed turn earns from the session transition it feeds tick ---------
def test_a_completed_turn_across_two_polls_awards_coins_and_xp():
    # First poll registers the session; the second sees working -> idle, which the
    # service feeds tick as its last-seen snapshot, earning a completed-turn reward.
    svc = pet_service.PetService(FakeStore(_pet(coins=0, xp=0)), now=1000.0)
    svc.poll({"s1": {"state": "working"}}, now=1000.0)
    result = svc.poll({"s1": {"state": "idle"}}, now=1000.0)
    assert result.pet["coins"] > 0
    assert result.pet["xp"] > 0


# --- persistence is throttled: at most one flush per interval on a quiet run ----
def test_the_pet_is_flushed_once_the_save_interval_elapses():
    store = FakeStore(_pet())
    svc = pet_service.PetService(store, now=1000.0)
    svc.poll({}, now=1000.0 + pet_service.PET_SAVE_INTERVAL_S)
    assert len(store.saves) == 1


def test_a_quiet_poll_within_the_save_interval_does_not_persist():
    store = FakeStore(_pet())
    svc = pet_service.PetService(store, now=1000.0)
    svc.poll({}, now=1001.0)   # 1s later, nothing earned and the interval not up
    assert store.saves == []


def test_an_award_forces_a_save_inside_the_throttle_interval():
    # A completed turn one second in must persist immediately, not wait out the
    # interval — the earn overrides the throttle so coins can't be lost to a crash.
    store = FakeStore(_pet(coins=0, xp=0))
    svc = pet_service.PetService(store, now=1000.0)
    svc.poll({"s1": {"state": "working"}}, now=1000.0)
    assert store.saves == []                             # nothing earned to flush yet
    svc.poll({"s1": {"state": "idle"}}, now=1001.0)      # completed turn, only 1s in
    assert len(store.saves) == 1


# --- external pet.json edits (a standalone Pet window) are picked up by mtime ---
def test_an_external_pet_json_edit_is_picked_up_on_the_next_poll():
    store = FakeStore(_pet(coins=0))
    svc = pet_service.PetService(store, now=1000.0)
    # A standalone Pet window writes pet.json under the manager: coins jump to 500.
    store.external_edit(_pet(coins=500))
    result = svc.poll({}, now=1000.0)
    assert result.pet["coins"] == 500


def test_the_services_own_save_is_not_mistaken_for_an_external_edit():
    # A self-save bumps the store mtime too; the service must record its own write
    # so the next poll doesn't reload (which would reset the tick and drop progress).
    store = FakeStore(_pet())
    svc = pet_service.PetService(store, now=1000.0)
    assert store.loads == 1                                # only the constructor load
    svc.poll({}, now=1000.0 + pet_service.PET_SAVE_INTERVAL_S)      # throttled flush
    assert len(store.saves) == 1
    svc.poll({}, now=1000.0 + 2 * pet_service.PET_SAVE_INTERVAL_S)  # quiet poll after
    assert store.loads == 1                                # its own write: no reload


# --- a newly earned milestone piece is a moment: celebrate + force a save ------
def test_a_newly_earned_milestone_celebrates_and_forces_a_save():
    # days_active has crossed the 7-day "flower" mark but the piece isn't granted yet.
    store = FakeStore(_pet(days_active=7, wardrobe=[]))
    svc = pet_service.PetService(store, now=1000.0)
    result = svc.poll({}, now=1000.0)   # 0s in: no throttle flush, only the milestone
    assert result.celebrate is True
    assert len(store.saves) == 1


def test_an_already_owned_milestone_does_not_celebrate_again():
    # Same 7-day history, but the piece is already in the wardrobe: grant is a no-op,
    # so there's nothing to celebrate on this (or any later) poll.
    store = FakeStore(_pet(days_active=7, wardrobe=["flower"]))
    svc = pet_service.PetService(store, now=1000.0)
    result = svc.poll({}, now=1000.0)
    assert result.celebrate is False


# --- replay protection: the snapshot means a transition fires exactly once ------
def test_a_completed_turn_awards_once_not_on_every_later_idle_poll():
    store = FakeStore(_pet(coins=0, xp=0))
    svc = pet_service.PetService(store, now=1000.0)
    svc.poll({"s1": {"state": "working"}}, now=1000.0)
    earned = svc.poll({"s1": {"state": "idle"}}, now=1000.0).pet["coins"]
    assert earned > 0
    # Staying idle is not a new completed turn: the per-poll snapshot means the same
    # working -> idle edge can't re-fire, so coins hold steady.
    steady = svc.poll({"s1": {"state": "idle"}}, now=1000.0).pet["coins"]
    assert steady == earned


def test_a_closed_session_cannot_replay_a_stale_transition():
    # s1 completes a turn, then its card closes (absent from the next poll). Because
    # the snapshot drops it, a later session reusing the id starts fresh — its old
    # working -> idle edge cannot re-fire and double-award.
    store = FakeStore(_pet(coins=0, xp=0))
    svc = pet_service.PetService(store, now=1000.0)
    svc.poll({"s1": {"state": "working"}}, now=1000.0)
    earned = svc.poll({"s1": {"state": "idle"}}, now=1000.0).pet["coins"]
    assert earned > 0
    svc.poll({}, now=1000.0)                                        # s1's card closed
    reopened = svc.poll({"s1": {"state": "idle"}}, now=1000.0).pet["coins"]
    assert reopened == earned                                       # no replayed turn


# --- external-write port: the Pet window / petting / exit flush go through here -
def test_pet_exposes_the_current_creature():
    svc = pet_service.PetService(FakeStore(_pet(coins=42)), now=1000.0)
    assert svc.pet["coins"] == 42


def test_commit_replaces_the_pet_and_persists_it():
    # A Pet-window action (feeding) hands the service a mutated pet to own + flush.
    store = FakeStore(_pet(coins=0))
    svc = pet_service.PetService(store, now=1000.0)
    returned = svc.commit(_pet(coins=99), now=1000.0)
    assert svc.pet["coins"] == 99
    assert returned["coins"] == 99
    assert store.saves[-1]["coins"] == 99


def test_a_commit_is_not_mistaken_for_an_external_edit():
    # commit persists (bumping the store mtime); like a poll-save it must record its
    # own write, so the very next poll doesn't reload and clobber in-memory progress.
    store = FakeStore(_pet())
    svc = pet_service.PetService(store, now=1000.0)
    svc.commit(_pet(coins=99), now=1000.0)
    loads_before = store.loads
    svc.poll({}, now=1000.0)
    assert store.loads == loads_before


def test_flush_persists_the_current_pet():
    # The exit path flushes whatever the service currently holds, no replacement.
    store = FakeStore(_pet(coins=7))
    svc = pet_service.PetService(store, now=1000.0)
    svc.flush(now=1000.0)
    assert store.saves[-1]["coins"] == 7


# --- the production Store adapter over pet_store + a real pet.json --------------
def test_petstore_adapter_round_trips_through_a_real_file(tmp_path):
    path = tmp_path / "pet.json"
    store = pet_service.PetStore(path)
    assert store.mtime() is None                    # nothing on disk yet
    store.save(pet_store.default_pet(1000.0), 1000.0)
    assert store.mtime() is not None                # the write created the file
    assert store.load(1000.0)["coins"] == 0         # and it round-trips the pet
