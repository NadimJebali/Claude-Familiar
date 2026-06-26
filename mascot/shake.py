"""The card's attention shake: while a permission/attention prompt sits
unanswered, the whole card jostles — gently at first, then steadily more frantic
the longer it's ignored.

This seam owns the *math*: the intensity ramp (0 at the grace edge, 1 once fully
ignored), the amplitude/frequency derivation from that intensity, and — crucially
— the absolute-from-rest offset. ``begin(rest_pos)`` captures the resting
position once; ``offset(now)`` returns the rounded ``(dx, dy)`` to add to rest
this frame; ``end()`` clears the capture so the next shake re-anchors.

Why absolute-from-rest matters (a documented past bug): an earlier version moved
the card by deltas off ``winfo_x()``. Because that value lags a frame behind a
just-applied ``geometry`` on Windows, the error accumulated on every shake
reversal and slowly walked a frantically shaking card clean off-screen. Holding
the rest position and always offsetting from it avoids that drift entirely.

Tk-free and clock-free (``now`` is passed in; the caller reads ``winfo_x/y`` and
applies ``geometry``), so the offset bounds and the return-to-rest at ``end`` are
unit-testable.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True)
class ShakeConfig:
    """The fixed shake recipe: the delay before shaking, the ramp to full
    aggression, the amplitude band (px) and the frequency band (sways/sec). Set
    once from the widget's constants; never changes while a card lives."""
    after_s: float
    ramp_s: float
    amp_min: float
    amp_max: float
    freq_min: float
    freq_max: float


class Shake:
    """Owns one card's attention-shake offset. The card asks ``offset(now, elapsed)``
    for the per-frame ``(dx, dy)`` to add to the resting position; ``begin`` /
    ``end`` bracket the capture of that rest so the offset is always taken from a
    fixed anchor (see the module docstring for the drift bug this prevents).
    """

    def __init__(self, cfg: ShakeConfig, *, t0: float) -> None:
        self._cfg = cfg
        # ``t0`` anchors the shake's phase to the same clock the card's animation
        # uses, so the sway is continuous rather than restarting each frame.
        self._t0 = t0
        self._rest_pos: tuple[int, int] | None = None

    @property
    def rest_pos(self) -> tuple[int, int] | None:
        """The captured resting position, or ``None`` while not shaking."""
        return self._rest_pos

    @property
    def is_shaking(self) -> bool:
        """Whether a rest position is currently captured (a shake is in progress)."""
        return self._rest_pos is not None

    def begin(self, rest_pos: tuple[int, int]) -> None:
        """Capture the resting position once, the moment a shake begins. Subsequent
        calls while already shaking are ignored, so the anchor never moves mid-shake."""
        if self._rest_pos is None:
            self._rest_pos = rest_pos

    def end(self) -> None:
        """Settle: forget the captured rest so the next shake re-anchors. The card
        snaps the geometry back to rest before calling this."""
        self._rest_pos = None

    def intensity(self, elapsed: float) -> float:
        """How frantic the shake is: 0 at the grace edge (``after_s``), ramping to 1
        over ``ramp_s`` and capped there. Matches the old ``_apply_attention_shake``
        exactly — a bare ``min(1.0, ...)`` with no low clamp. The card only calls
        ``offset`` once past the grace window (``elapsed >= after_s``), so the value
        is never negative on the live path; leaving it unclamped keeps the math
        byte-for-byte the original rather than adding a guard the original lacked."""
        return min(1.0, (elapsed - self._cfg.after_s) / self._cfg.ramp_s)

    def offset(self, now: float, elapsed: float) -> tuple[int, int]:
        """The rounded ``(dx, dy)`` to add to the resting position this frame.

        A steady horizontal sway (amplitude/frequency scaled by intensity) plus a
        jitter that grows with intensity, so it reads as a gentle wobble at first
        and a violent buzz once ignored a while."""
        cfg = self._cfg
        intensity = self.intensity(elapsed)
        amp = cfg.amp_min + (cfg.amp_max - cfg.amp_min) * intensity
        freq = cfg.freq_min + (cfg.freq_max - cfg.freq_min) * intensity
        phase = (now - self._t0) * freq * 2 * math.pi
        dx = amp * math.sin(phase) + random.uniform(-1.0, 1.0) * amp * 0.5 * intensity
        dy = random.uniform(-1.0, 1.0) * amp * 0.6
        return round(dx), round(dy)
