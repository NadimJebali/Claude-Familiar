"""Tk-free unit tests for the card's animation math (issue #27).

The two seams introduced in slice 3 — ``mascot.particles`` (the hearts/food/zzz
rising-particle field) and ``mascot.shake`` (the attention-shake offset) — carry
math that lived duplicated and untested inside the widget. These cover the
externally visible behaviour at each seam: a particle's position/alive-ness over
its lifetime and the per-kind count cap; the shake offset's boundedness and its
return to rest at ``end()``.

Like the other pure-core tests, this is view-free: ``advance`` returns the visible
particles to paint, and ``offset`` is pure ``now``-in math.
"""
from __future__ import annotations

import random

from mascot import particles, shake


# --- particle kinds (test doubles) ----------------------------------------
def _recording_kind(name: str, *, lifetime_s: float = 1.0, rise_px: float = 30.0,
                     max_count: int = 6, tag: str = "heart",
                     fade_from: tuple[int, int, int] | None = (255, 0, 0)) -> tuple:
    """A real ParticleKind; the second tuple element is unused (kept for the callers'
    ``kind, _ = ...`` unpacking)."""
    kind = particles.ParticleKind(
        name=name, lifetime_s=lifetime_s, rise_px=rise_px, pixel_px=2, tag=tag,
        max_count=max_count, fade_from=fade_from,
    )
    return kind, []


def _field(**kinds) -> particles.Particles:
    return particles.Particles(kinds, panel_fill=(29, 31, 41))


# --- particle lifetime ----------------------------------------------------

def test_particle_rises_and_drifts_over_its_lifetime():
    # Arrange: one heart at a known origin, no stagger, a fixed rightward drift.
    random.seed(0)
    kind, _ = _recording_kind("heart", lifetime_s=2.0, rise_px=40.0)
    field = _field(heart=kind)
    field.emit("heart", (100.0, 200.0), now=0.0, drift_range=(5.0, 5.0))
    p = field.alive("heart", 0.0)[0]

    # Act + Assert: at spawn it sits at the origin; halfway it has risen half the
    # rise and drifted half its sideways drift.
    x0, y0 = p.position(0.0)
    assert (x0, y0) == (100.0, 200.0)
    xh, yh = p.position(1.0)
    assert yh == 200.0 - 0.5 * 40.0          # risen half the rise distance
    assert xh > x0                           # drifted to the right


def test_particle_is_alive_until_expiry_then_drops():
    # Arrange: a one-second particle.
    kind, _ = _recording_kind("heart", lifetime_s=1.0)
    field = _field(heart=kind)
    field.emit("heart", (0.0, 0.0), now=0.0)
    p = field.alive("heart", 0.0)[0]

    # Act + Assert: alive through its life, gone at/after the lifetime boundary.
    assert p.alive(0.5) is True
    assert p.visible(0.5) is True
    assert p.alive(1.0) is False             # prog >= 1.0 -> expired
    assert field.alive("heart", 1.0) == []


def test_staggered_particle_is_alive_but_not_yet_visible():
    # Arrange: emit with a stagger so t0 is in the future.
    random.seed(1)
    kind, _ = _recording_kind("heart", lifetime_s=1.0)
    field = _field(heart=kind)
    field.emit("heart", (0.0, 0.0), now=0.0, stagger_s=0.5)
    p = field.alive("heart", 0.0)[0]

    # Act + Assert: before its staggered start it is alive but not drawn.
    assert p.progress(0.0) < 0.0
    assert p.alive(0.0) is True
    assert p.visible(0.0) is False


def test_fade_lerps_from_kind_color_toward_panel_fill():
    # Arrange: a kind that fades from pure red toward the panel fill.
    kind, _ = _recording_kind("heart", lifetime_s=1.0, fade_from=(255, 0, 0))
    field = _field(heart=kind)
    field.emit("heart", (0.0, 0.0), now=0.0)
    p = field.alive("heart", 0.0)[0]

    # Act + Assert: at spawn it is the kind color; partway it has moved toward the
    # panel fill (29, 31, 41) on every channel.
    assert p.color(0.0) == (255, 0, 0)
    r, g, b = p.color(0.5)
    assert r < 255 and g > 0 and b > 0


def test_non_fading_kind_has_no_color():
    # Arrange: food never fades — its sprite is fixed.
    kind, _ = _recording_kind("food", fade_from=None, tag="emote")
    field = _field(food=kind)
    field.emit("food", (0.0, 0.0), now=0.0)
    p = field.alive("food", 0.0)[0]

    # Act + Assert.
    assert p.color(0.0) is None


# --- count cap ------------------------------------------------------------

def test_emit_caps_live_count_per_kind_keeping_newest():
    # Arrange: a kind capped at 3.
    random.seed(2)
    kind, _ = _recording_kind("heart", max_count=3)
    field = _field(heart=kind)

    # Act: emit five at the same instant.
    for i in range(5):
        field.emit("heart", (float(i), 0.0), now=0.0)

    # Assert: only the cap survives, and it's the most-recently emitted ones.
    alive = field.alive("heart", 0.0)
    assert len(alive) == 3
    assert sorted(p.x for p in alive) == [2.0, 3.0, 4.0]


def test_cap_is_independent_across_tags():
    # Arrange: hearts and emotes paint under different canvas tags, so their caps
    # are separate.
    heart, _ = _recording_kind("heart", max_count=2, tag="heart")
    food, _ = _recording_kind("food", max_count=2, tag="emote", fade_from=None)
    field = _field(heart=heart, food=food)

    # Act: overflow hearts; emit one food.
    for i in range(4):
        field.emit("heart", (float(i), 0.0), now=0.0)
    field.emit("food", (0.0, 0.0), now=0.0)

    # Assert: the heart cap didn't evict the food.
    assert len(field.alive("heart", 0.0)) == 2
    assert len(field.alive("food", 0.0)) == 1


def test_kinds_sharing_a_tag_share_one_combined_cap():
    # Arrange: food and zzz both paint under the "emote" tag, capped at 3 — the old
    # single shared _emotes list. They must NOT each get their own cap of 3.
    food, _ = _recording_kind("food", max_count=3, tag="emote", fade_from=None)
    zzz, _ = _recording_kind("zzz", max_count=3, tag="emote")
    field = _field(food=food, zzz=zzz)

    # Act: emit four emotes total across both kinds.
    field.emit("food", (0.0, 0.0), now=0.0)
    field.emit("zzz", (1.0, 0.0), now=0.0)
    field.emit("food", (2.0, 0.0), now=0.0)
    field.emit("zzz", (3.0, 0.0), now=0.0)

    # Assert: the combined emote count is capped at 3 (the oldest, the first food,
    # is evicted), not 3-per-kind.
    live = field.alive("food", 0.0) + field.alive("zzz", 0.0)
    assert len(live) == 3
    assert sorted(p.x for p in live) == [1.0, 2.0, 3.0]


# --- advance (the view-free paint list) -----------------------------------

def test_advance_returns_visible_and_prunes_expired():
    # Arrange: a visible heart and an already-expired one.
    kind, _ = _recording_kind("heart", lifetime_s=1.0, tag="heart")
    field = _field(heart=kind)
    field.emit("heart", (10.0, 10.0), now=0.0)
    field.emit("heart", (99.0, 99.0), now=-5.0)   # spawned long ago -> expired

    painted = field.advance(0.5)

    # Only the live particle is returned to paint, and the expired one is pruned.
    assert len(painted) == 1
    assert len(field.alive("heart", 0.5)) == 1


def test_advance_orders_emotes_after_hearts_regardless_of_emission_order():
    # An emote is emitted FIRST, then a heart, while both are live. The panel paints
    # in the returned order, so hearts must come before emotes (emotes stack on top)
    # — by tag-registration order, not raw emission order.
    heart, _ = _recording_kind("heart", tag="heart")
    emote, _ = _recording_kind("food", tag="emote", fade_from=None)
    field = _field(heart=heart, food=emote)   # heart registered first
    field.emit("food", (0.0, 0.0), now=0.0)    # emote emitted before the heart
    field.emit("heart", (0.0, 0.0), now=0.0)

    painted = field.advance(0.5)

    assert [kind.tag for kind, *_ in painted] == ["heart", "emote"]


# --- shake ----------------------------------------------------------------

def _shake_cfg(**over) -> shake.ShakeConfig:
    base = {
        "after_s": 5.0, "ramp_s": 60.0,
        "amp_min": 2.0, "amp_max": 8.0,
        "freq_min": 4.0, "freq_max": 11.0,
    }
    base.update(over)
    return shake.ShakeConfig(**base)


def test_intensity_ramps_from_zero_at_grace_edge_to_one():
    # Arrange.
    s = shake.Shake(_shake_cfg(after_s=5.0, ramp_s=60.0), t0=0.0)

    # Act + Assert: 0 at the grace edge, linear to 1, capped at 1 once fully ramped.
    # The ramp has no low clamp (matching the old _apply_attention_shake's bare
    # min(1.0, ...)); the card only asks for an offset past the grace edge, so a
    # below-zero reading never reaches the live path.
    assert s.intensity(5.0) == 0.0
    assert s.intensity(35.0) == 0.5
    assert s.intensity(65.0) == 1.0
    assert s.intensity(1e6) == 1.0


def test_intensity_is_unclamped_below_the_grace_edge():
    # Arrange: before the grace edge the raw ramp goes negative — the original math
    # never guarded this because the card never reads it there.
    s = shake.Shake(_shake_cfg(after_s=5.0, ramp_s=60.0), t0=0.0)

    # Act + Assert: a bare linear value, not floored at 0.
    assert s.intensity(0.0) == (0.0 - 5.0) / 60.0


def test_offset_is_bounded_by_amplitude_across_the_ramp():
    # Arrange: max amplitude 8 -> |dx| <= amp*1.5, |dy| <= amp*0.6, so the whole
    # offset stays within amp_max*1.5 of rest however frantic it gets.
    random.seed(7)
    cfg = _shake_cfg(amp_max=8.0)
    s = shake.Shake(cfg, t0=0.0)
    bound = cfg.amp_max * 1.5

    # Act + Assert: sample many frames across the ramp; never exceed the bound.
    for frame in range(2000):
        now = frame * 0.04
        dx, dy = s.offset(now, elapsed=now)
        assert abs(dx) <= bound + 1            # +1 for rounding
        assert abs(dy) <= cfg.amp_max * 0.6 + 1


def test_begin_captures_rest_once_and_end_releases_it():
    # Arrange.
    s = shake.Shake(_shake_cfg(), t0=0.0)
    assert s.is_shaking is False
    assert s.rest_pos is None

    # Act: begin anchors the rest; a second begin must not move the anchor.
    s.begin((100, 200))
    s.begin((999, 999))

    # Assert: anchored at the first value; end releases it so the next shake
    # re-anchors (the return-to-rest contract the card relies on).
    assert s.is_shaking is True
    assert s.rest_pos == (100, 200)
    s.end()
    assert s.is_shaking is False
    assert s.rest_pos is None


def test_horizontal_sway_is_deterministic_at_zero_intensity():
    # Arrange: at the grace edge the intensity is 0, so the dx jitter term (which
    # scales with intensity) vanishes and dx is the pure deterministic sway —
    # repeatable on every read. This is the absolute-from-rest math the seam exists
    # to guarantee: the sway is a function of ``now``, never accumulated frame to
    # frame (the drift bug the module docstring documents).
    s = shake.Shake(_shake_cfg(after_s=0.0, ramp_s=1.0, amp_min=4.0, amp_max=4.0), t0=0.0)

    # Act: read the same instant twice.
    dx_a, _ = s.offset(0.25, elapsed=0.0)
    dx_b, _ = s.offset(0.25, elapsed=0.0)

    # Assert: the horizontal sway component is identical (no drift accumulation).
    assert dx_a == dx_b
