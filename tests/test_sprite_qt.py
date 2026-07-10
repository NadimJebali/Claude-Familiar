"""Offscreen smoke test for the Qt pixel-sprite renderer (mascot/sprite_qt.py, #55).

Renders every face/stage/hat headlessly (QT_QPA_PLATFORM=offscreen) and asserts
each produces a non-blank pixmap. No golden-image pixel assertions — those are
brittle across platforms and DPI; visual quality is checked via the gallery demo
(python -m mascot.sprite_gallery). Skips cleanly where PySide6 isn't installed,
matching the pywin32/pystray-gated suites.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from mascot import config, sprite_pixel, sprite_qt


@pytest.fixture(scope="module")
def app():
    # QPixmap needs a QGuiApplication and the gallery needs QApplication (widgets);
    # QApplication is a QGuiApplication, so one covers both. It's a singleton.
    return QApplication.instance() or QApplication([])


def _accent(state: str) -> str:
    r, g, b = config.STATE_COLORS.get(state, config.STATE_COLORS["idle"])
    return f"#{r:02x}{g:02x}{b:02x}"


def _lit_cells(pixmap) -> int:
    """Count lit cells — sample each cell's top-left, where a filled px-rect lands."""
    img = pixmap.toImage()
    step = pixmap.width() // sprite_qt._CANVAS  # == px; one sample per grid cell
    return sum(
        img.pixelColor(x, y).alpha() > 0
        for y in range(0, img.height(), step)
        for x in range(0, img.width(), step)
    )


def test_every_face_on_every_stage_renders_nonblank(app):
    r = sprite_qt.QtPixmapRenderer()
    for stage in (*sprite_pixel._BODIES, "egg"):
        for state in sprite_pixel._FACES:
            spec = sprite_qt.SpriteSpec(stage=stage, state=state, accent=_accent(state))
            pm = r.creature(spec, px=4)
            assert not pm.isNull(), f"{stage}/{state} null"
            assert _lit_cells(pm) > 0, f"{stage}/{state} blank"


def test_every_hat_renders_on_the_creature(app):
    r = sprite_qt.QtPixmapRenderer()
    bare = _lit_cells(r.creature(sprite_qt.SpriteSpec("baby", "idle", _accent("idle")), px=6))
    for hat in sprite_pixel._HATS:
        spec = sprite_qt.SpriteSpec("baby", "idle", _accent("idle"), hat=hat)
        pm = r.creature(spec, px=6)
        assert not pm.isNull()
        assert _lit_cells(pm) >= bare, hat   # a hat only adds cells over the creature


def test_the_egg_ignores_its_hat(app):
    r = sprite_qt.QtPixmapRenderer()
    bare = _lit_cells(r.creature(sprite_qt.SpriteSpec("egg", "idle", _accent("idle")), px=6))
    worn = _lit_cells(r.creature(
        sprite_qt.SpriteSpec("egg", "idle", _accent("idle"), hat="crown"), px=6))
    assert worn == bare   # the egg never wears anything


def test_gravestone_renders_nonblank(app):
    r = sprite_qt.QtPixmapRenderer()
    pm = r.gravestone(px=5)
    assert not pm.isNull()
    assert _lit_cells(pm) > 0


def test_flourish_lights_extra_cells(app):
    r = sprite_qt.QtPixmapRenderer()
    plain = _lit_cells(r.creature(sprite_qt.SpriteSpec("adult", "happy", _accent("happy")), px=6))
    flourished = _lit_cells(r.creature(
        sprite_qt.SpriteSpec("adult", "happy", _accent("happy"), flourish=True), px=6))
    assert flourished > plain   # the milestone sparkle adds corner pixels


def test_pixmaps_are_cached_by_spec_and_size(app):
    r = sprite_qt.QtPixmapRenderer()
    spec = sprite_qt.SpriteSpec("teen", "working", _accent("working"))
    first = r.creature(spec, px=5)
    assert r.creature(spec, px=5) is first     # same spec+size -> cached, no re-render
    assert r.creature(spec, px=6) is not first  # a different size is a distinct entry
    grave = r.gravestone(px=5)
    assert r.gravestone(px=5) is grave


def test_gallery_builds_without_error(app):
    # Construct-smoke for the visual demo (the repo's convention for GUI code):
    # every tile renders through the same renderer, so a broken demo can't ship.
    from mascot import sprite_gallery

    assert sprite_gallery.build() is not None
