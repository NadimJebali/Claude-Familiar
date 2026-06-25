"""The effective-state overlay: a small stateful home for the card's expiry timers.

``effective_state.compute`` is the pure core — its priority ladder (dizzy >
celebrate > waiting_angry > stall-watchdog > sleeping > blink > mood-idle > raw)
and stall watchdog are correct and unit-tested. But it takes twelve keyword
arguments, and the widget used to thread all five live timers plus the four
configured thresholds into it on every animation frame.

``Overlay`` owns those five timers (``dizzy_until``, ``celebrate_until``,
``waiting_since``, ``idle_since``, ``blink_until``) and the thresholds, turning
that shallow call site into a deep one: the card signals intent
(``note_dizzy(now)``, ``note_celebrate(now)``, ``note_raw(raw, now)``,
``note_blink(now)``) and asks one question, ``effective(now, mood) -> str``. The
displayed state is unchanged because the read delegates straight to ``compute``.

Tk-free and clock-free (``now`` is always passed in), so every transition is
unit-testable exactly like the pure core it wraps.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import effective_state


@dataclass(frozen=True)
class OverlayConfig:
    """The fixed thresholds the overlay feeds into ``compute`` — the durations a
    dizzy/celebrate/blink overlay lasts and the watchdog/sleep/shake delays. Set
    once at construction (from ``config`` + the widget's constants); never change
    while a card lives."""
    dizzy_duration_s: float
    celebrate_duration_s: float
    blink_duration_s: float
    sleep_after_idle_s: float
    shake_after_s: float
    thinking_stall_s: float
    working_stall_s: float


class Overlay:
    """Owns one card's effective-state timers; reads back the displayed state.

    Intent-named writes mark *when* something happened; ``effective`` then layers
    those timers over the raw state via the pure core. The card no longer touches
    the timer fields directly — it asks ``is_dizzy`` / ``waiting_elapsed`` for the
    two behaviours (tap gate, attention shake) that legitimately need them.
    """

    def __init__(self, cfg: OverlayConfig, *, raw: str = "idle", now: float = 0.0) -> None:
        self._cfg = cfg
        self._dizzy_until = 0.0
        self._celebrate_until = 0.0
        self._blink_until = 0.0
        # The idle / waiting clocks start running if the card opens in that state,
        # matching the widget's original constructor bookkeeping.
        self._idle_since: float | None = now if raw == "idle" else None
        self._waiting_since: float | None = now if raw == "waiting" else None

    # --- intent writes ----------------------------------------------------
    def note_dizzy(self, now: float) -> None:
        """A shake landed: glaze the eyes over for ``dizzy_duration_s``."""
        self._dizzy_until = now + self._cfg.dizzy_duration_s

    def note_celebrate(self, now: float) -> None:
        """A turn just finished, or the pet was petted/fed: a brief happy face."""
        self._celebrate_until = now + self._cfg.celebrate_duration_s

    def note_blink(self, now: float) -> None:
        """An idle blink: a 120ms ``idle_blink`` window picked up by the next read."""
        self._blink_until = now + self._cfg.blink_duration_s

    def note_raw(self, raw: str, now: float) -> None:
        """Track the raw-state clocks: how long it's been idle (drives dozing) and
        how long an attention prompt has gone unanswered (drives the shake/glare).
        Each clock starts when its state is entered and clears when it's left."""
        self._idle_since = self._enter(self._idle_since, raw == "idle", now)
        self._waiting_since = self._enter(self._waiting_since, raw == "waiting", now)

    @staticmethod
    def _enter(since: float | None, active: bool, now: float) -> float | None:
        if not active:
            return None
        return now if since is None else since

    # --- the single read --------------------------------------------------
    def effective(self, raw: str, now: float, *, ts: float | None, mood: str = "content") -> str:
        """The effective (displayed) state: the raw state with this card's timers
        layered on, delegated to the pure core so the priority ladder is exact."""
        return effective_state.compute(
            raw, now,
            ts=ts,
            dizzy_until=self._dizzy_until,
            celebrate_until=self._celebrate_until,
            waiting_since=self._waiting_since,
            idle_since=self._idle_since,
            blink_until=self._blink_until,
            sleep_after_idle_s=self._cfg.sleep_after_idle_s,
            shake_after_s=self._cfg.shake_after_s,
            thinking_stall_s=self._cfg.thinking_stall_s,
            working_stall_s=self._cfg.working_stall_s,
            mood=mood,
        )

    # --- narrow timer reads (for behaviours that aren't the displayed state) ---
    def is_dizzy(self, now: float) -> bool:
        """Whether the dizzy overlay is still in effect — the tap gate suppresses
        petting while the mascot is reeling."""
        return now < self._dizzy_until

    def waiting_elapsed(self, now: float) -> float | None:
        """How long the current attention prompt has gone unanswered, or ``None`` if
        nothing is waiting — drives the attention shake's amplitude/frequency."""
        if self._waiting_since is None:
            return None
        return now - self._waiting_since
