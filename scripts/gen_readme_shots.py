#!/usr/bin/env python3
"""Generate the README theme screenshots from the real widgets.

Renders the Classic cards and the Compact panel — the very ``QtCard`` /
``CompactWindow`` the widget runs — fed a small staged scene (working/idle
states, effort levels, the file · model line, context rings, usage bars) and
grabbed **without ever showing a window**, so nothing flashes on screen.

Unlike ``gen_readme_art.py`` this does NOT force the offscreen platform:
offscreen has no real font stack (text renders as tofu boxes) and these shots
contain captions and labels, so run it on a machine with a display:

    python scripts/gen_readme_shots.py

Output: ``docs/images/theme-classic.png``, ``docs/images/theme-compact.png``.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"
GAP = 14                        # transparent gap between the two classic cards


def _usage(now: float) -> dict:
    return {"five_hour": {"used_percentage": 47, "resets_at": now + 3 * 3600},
            "seven_day": {"used_percentage": 40, "resets_at": now + 5 * 86400},
            "ts": now}


def _classic(app: QApplication) -> QImage:
    """Two cards side by side: a max-effort working card (rainbow, file · model
    line, a sub-agent badge) and an xhigh idle one (ripple, amber ring)."""
    from mascot.qt_card import QtCard
    from mascot.sprite_qt import QtPixmapRenderer

    renderer = QtPixmapRenderer()
    now = time.time()
    working = {"session_id": "a", "state": "working", "tool": "Edit", "ts": now,
               "subagents": [{"id": "s1", "type": "code-reviewer"}],
               "schema_version": 1, "model": "claude-fable-5",
               "file": "C:/project/src/App.tsx", "effort": "max"}
    idle = {"session_id": "b", "state": "idle", "tool": None, "ts": now,
            "subagents": [], "schema_version": 1, "model": "claude-opus-4-8",
            "effort": "xhigh"}

    grabs = []
    for state, ctx in ((working, 47.0), (idle, 76.0)):
        card = QtCard(state["session_id"], state, 0, renderer)
        card.set_usage(_usage(now))
        card.set_context(ctx)
        for _ in range(8):              # let the render timer produce a frame
            app.processEvents()
            time.sleep(0.05)
        grabs.append(card._panel.grab())
        card.close()

    width = sum(g.width() for g in grabs) + GAP * (len(grabs) - 1)
    height = max(g.height() for g in grabs)
    img = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    try:
        x = 0
        for g in grabs:
            p.drawPixmap(x, 0, g)
            x += g.width() + GAP
    finally:
        p.end()
    return img


def _compact(app: QApplication) -> QImage:
    """The one-panel session list: a rainbow working row with the file, an
    xhigh ripple row, a dimmed idle row — rings at three fills, bars below."""
    from mascot.qt_compact import CompactWindow

    now = time.time()
    window = CompactWindow()
    window._anim_t0 = now - 0.9         # a mid-animation phase, so cells show
    window.set_sessions({
        "frontend": {"state": "working", "tool": "Edit", "ts": now,
                     "model": "claude-fable-5", "effort": "max",
                     "file": "C:/project/src/App.tsx",
                     "subagents": [{"id": "x", "type": "code-reviewer"}]},
        "backend": {"state": "working", "tool": "Read", "ts": now,
                    "model": "claude-opus-4-8", "effort": "xhigh",
                    "subagents": []},
        "docs": {"state": "idle", "tool": None, "ts": now,
                 "model": "claude-haiku-4-5-20251001", "subagents": []},
    })
    window.set_usage(_usage(now))
    window.set_context({"frontend": 35.0, "backend": 62.0, "docs": 21.0})
    window._tick()
    app.processEvents()
    img = window.grab().toImage()
    window.close()
    return img


def main() -> None:
    # Neutralize THIS machine's account-level effort signal: rows without a
    # per-session effort fall back to it (by design), but the staged scene must
    # render as a no-signal machine would — the idle row stays plain.
    from mascot import effort
    effort.settings_effort = lambda: ""

    app = QApplication.instance() or QApplication(sys.argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    _classic(app).save(str(OUT_DIR / "theme-classic.png"))
    print("wrote", OUT_DIR / "theme-classic.png")
    _compact(app).save(str(OUT_DIR / "theme-compact.png"))
    print("wrote", OUT_DIR / "theme-compact.png")


if __name__ == "__main__":
    main()
