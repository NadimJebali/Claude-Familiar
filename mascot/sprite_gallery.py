"""Visual gallery for the Qt pixel-sprite renderer (issue #55).

Renders every face on every stage, the wardrobe hats, the gravestone and the
milestone flourish with :class:`~mascot.sprite_qt.QtPixmapRenderer`, so the port's
sprite output can be eyeballed in one window:

    python -m mascot.sprite_gallery

The visual counterpart to the offscreen smoke test (tests/test_sprite_qt.py): the
test proves nothing renders blank; the gallery is where a human judges the art.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import config, sprite_pixel, sprite_qt

_SLATE = "#201e29"   # the dark "desktop" the README art tiles glow on
_PX = 6              # cell size for the gallery tiles


def _accent(state: str) -> str:
    r, g, b = config.STATE_COLORS.get(state, config.STATE_COLORS["idle"])
    return f"#{r:02x}{g:02x}{b:02x}"


def _tile(pixmap: QPixmap, caption: str) -> QWidget:
    cell = QWidget()
    box = QVBoxLayout(cell)
    box.setContentsMargins(6, 6, 6, 6)
    box.setSpacing(2)
    art = QLabel()
    art.setPixmap(pixmap)
    art.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caption_label = QLabel(caption)
    caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caption_label.setStyleSheet("color: #b9b4c6; font-size: 10px;")
    box.addWidget(art)
    box.addWidget(caption_label)
    return cell


def _header(grid: QGridLayout, row: int, title: str) -> int:
    label = QLabel(title)
    label.setStyleSheet("color: #f7f3ee; font-size: 13px; font-weight: bold;")
    grid.addWidget(label, row, 0, 1, -1)   # span the whole row
    return row + 1


def build() -> QWidget:
    """The gallery widget (no event loop) — also the construct-smoke seam."""
    renderer = sprite_qt.QtPixmapRenderer()
    root = QWidget()
    root.setStyleSheet(f"background: {_SLATE};")
    grid = QGridLayout(root)
    grid.setSpacing(4)

    row = 0
    faces = list(sprite_pixel._FACES)
    for stage in ("egg", "baby", "teen", "adult"):
        row = _header(grid, row, f"stage: {stage}")
        for col, face in enumerate(faces):
            spec = sprite_qt.SpriteSpec(stage=stage, state=face, accent=_accent(face))
            grid.addWidget(_tile(renderer.creature(spec, _PX), face), row, col)
        row += 1

    row = _header(grid, row, "wardrobe hats (on baby)")
    for col, hat in enumerate(sprite_pixel._HATS):
        spec = sprite_qt.SpriteSpec("baby", "idle", _accent("idle"), hat=hat)
        grid.addWidget(_tile(renderer.creature(spec, _PX), hat), row, col)
    row += 1

    row = _header(grid, row, "special")
    grid.addWidget(_tile(renderer.gravestone(_PX), "gravestone"), row, 0)
    milestone = sprite_qt.SpriteSpec("adult", "happy", _accent("happy"), flourish=True)
    grid.addWidget(_tile(renderer.creature(milestone, _PX), "flourish"), row, 1)

    return root


def main() -> None:
    app = QApplication(sys.argv)
    scroll = QScrollArea()
    scroll.setWidget(build())
    scroll.setWidgetResizable(True)
    scroll.setWindowTitle("Claude Familiar — Qt sprite gallery")
    scroll.resize(1100, 720)
    scroll.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
