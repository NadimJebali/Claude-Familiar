"""The card's rising-particle field: hearts (from a pet) and mood emotes (food /
zzz). One shared lifetime path lives here; the per-kind difference is a single
sprite call.

The math was duplicated across the widget's ``_emit_hearts``/``_animate_hearts``
and ``_schedule_emote``/``_animate_emotes`` over two parallel lists. A particle
is a tiny piece of state — an origin, a stagger offset, a drift, a kind — and a
pure lifetime: ``progress = (now - t0) / lifetime``; it rises ``rise_px * prog``,
drifts ``drift * prog``, and fades by lerping its color toward the panel fill as
it climbs, expiring at ``prog >= 1``. A per-kind lifetime/rise/pixel-size and the
count cap come from a frozen ``ParticleKind``.

The whole module is view-free and clock-free (``now`` is passed in): ``advance``
prunes the expired and returns the visible particles as ``(kind, x, y, color)`` for
the Qt panel to paint, so the lifetime/position/fade is unit-testable exactly like
the pure cores the rest of the card wraps.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))  # type: ignore[return-value]


@dataclass(frozen=True)
class ParticleKind:
    """The fixed per-kind recipe: how long a particle lives, how far it climbs, its
    pixel size, its group ``tag`` (which shares a count cap), and ``max_count``.
    ``fade_from`` is the color a fading particle lerps from toward the panel fill
    (``None`` for kinds — like food — that don't fade)."""
    name: str
    lifetime_s: float
    rise_px: float
    pixel_px: int
    tag: str
    max_count: int
    fade_from: tuple[int, int, int] | None = None


@dataclass
class _Particle:
    """One live particle: where it spawned, when it became visible, how far it
    drifts sideways, and which kind it is. Position and alive-ness are pure
    functions of ``now`` — no Tk, no wall clock baked in."""
    kind: ParticleKind
    x: float
    y0: float
    t0: float
    drift: float

    def progress(self, now: float) -> float:
        """0 at spawn, 1 at expiry; negative while still in its staggered delay."""
        return (now - self.t0) / self.kind.lifetime_s

    def alive(self, now: float) -> bool:
        """Still in the field: not yet expired (a not-yet-visible particle, with a
        negative progress, is alive but not drawn)."""
        return self.progress(now) < 1.0

    def visible(self, now: float) -> bool:
        """Past its staggered start and not yet expired — i.e. it draws this frame."""
        return 0.0 <= self.progress(now) < 1.0

    def position(self, now: float) -> tuple[float, float]:
        """The (x, y) a visible particle sits at: drifting right, rising up."""
        prog = self.progress(now)
        return (self.x + self.drift * prog, self.y0 - prog * self.kind.rise_px)

    def color(self, now: float) -> tuple[int, int, int] | None:
        """The fade color this frame, lerped from the kind's ``fade_from`` toward
        the panel fill; ``None`` for kinds that don't fade (their sprite is fixed)."""
        if self.kind.fade_from is None:
            return None
        return _lerp(self.kind.fade_from, self._panel_fill, self.progress(now))

    # Set once, shared by all particles — the panel color they fade into.
    _panel_fill: tuple[int, int, int] = field(default=(29, 31, 41), repr=False)


class Particles:
    """The card's particle field. ``emit`` spawns a particle of a kind at an origin;
    ``draw`` advances every kind to ``now``, repaints the live ones, and drops the
    expired — the single lifetime path the two old parallel lists shared.

    The panel fill (fade target) is injected so the module stays free of the card's
    palette constants while painting exactly the colors it did before.
    """

    def __init__(self, kinds: dict[str, ParticleKind], *,
                 panel_fill: tuple[int, int, int]) -> None:
        self._kinds = kinds
        self._panel_fill = panel_fill
        self._particles: list[_Particle] = []
        # The paint order of the canvas tags, in kind-registration order. The card
        # registers hearts before emotes, so hearts paint first and emotes land on
        # top — preserving the old draw order (``_animate_hearts`` then
        # ``_animate_emotes``) now that one shared list holds every kind.
        self._tag_order: list[str] = []
        for spec in kinds.values():
            if spec.tag not in self._tag_order:
                self._tag_order.append(spec.tag)

    def emit(self, kind: str, origin: tuple[float, float], now: float, *,
             stagger_s: float = 0.0, drift_range: tuple[float, float] = (0.0, 0.0)) -> None:
        """Spawn one particle of ``kind`` at ``origin``, becoming visible after a
        random stagger in ``[0, stagger_s]`` and drifting sideways by a random
        amount in ``drift_range``. The cap is then applied across *all* live
        particles sharing this kind's canvas tag (newest kept) — so kinds that
        paint under one tag (food + zzz both ``"emote"``) share a single cap, just
        as the old code capped its one shared ``_emotes`` list."""
        spec = self._kinds[kind]
        self._particles.append(_Particle(
            kind=spec,
            x=origin[0],
            y0=origin[1],
            t0=now + random.uniform(0.0, stagger_s),
            drift=random.uniform(*drift_range),
            _panel_fill=self._panel_fill,
        ))
        self._trim(spec)

    def _trim(self, spec: ParticleKind) -> None:
        """Cap the live count for one canvas tag to its ``max_count`` (keep the
        newest), leaving particles under other tags untouched. Grouping by tag (not
        by kind) keeps food + zzz — which paint under the shared ``"emote"`` tag —
        on one combined cap, matching the old single ``_emotes`` list."""
        same = [p for p in self._particles if p.kind.tag == spec.tag]
        if len(same) <= spec.max_count:
            return
        drop = {id(p) for p in same[:-spec.max_count]}
        self._particles = [p for p in self._particles if id(p) not in drop]

    def alive(self, kind: str, now: float) -> list[_Particle]:
        """The still-living particles of one kind at ``now`` — for tests and the
        prune in ``advance``."""
        spec = self._kinds[kind]
        return [p for p in self._particles if p.kind is spec and p.alive(now)]

    def advance(self, now: float) -> list[tuple[ParticleKind, float, float,
                                                 tuple[int, int, int] | None]]:
        """Drop expired particles and return the visible ones to paint this frame as
        ``(kind, x, y, color)``, walking the tags in registration order (hearts before
        emotes) and keeping emission order within a tag — so emotes always stack over
        hearts. View-free: the Qt panel paints the returned cells."""
        live = [p for p in self._particles if p.alive(now)]
        painted: list[tuple[ParticleKind, float, float, tuple[int, int, int] | None]] = []
        for tag in self._tag_order:
            for p in live:
                if p.kind.tag == tag and p.visible(now):
                    x, y = p.position(now)
                    painted.append((p.kind, x, y, p.color(now)))
        self._particles = live
        return painted
