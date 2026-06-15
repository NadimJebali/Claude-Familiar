"""Custom-drawn mascot art (pure Tkinter Canvas, no image assets).

`draw_creature` renders an original little character — "the familiar" — using
only vector primitives, with a different facial expression per Claude state.
Drawing on a Canvas keeps the project dependency-free and crisp at any DPI.

The character keeps a consistent identity across states (coral body, antenna
whose bulb glows in the state's accent color); only the face and a few accents
change so the user reads *mood* at a glance.
"""
from __future__ import annotations

import tkinter as tk

# --- palette ---------------------------------------------------------------
BODY = "#e58a5c"     # coral body
BODY_DK = "#bf6638"  # outline / shading
BELLY = "#f2b48d"    # lighter belly
EYE_WHITE = "#fbf7f0"
PUPIL = "#2b2330"
CHEEK = "#f29aa0"    # soft blush
MOUTH = "#7a3322"
GLINT = "#ffffff"


def _oval(c: tk.Canvas, x: float, y: float, rx: float, ry: float | None = None, **kw) -> int:
    """Centered oval helper."""
    ry = rx if ry is None else ry
    return c.create_oval(x - rx, y - ry, x + rx, y + ry, **kw)


def round_rect(c: tk.Canvas, x1: float, y1: float, x2: float, y2: float, r: float, **kw) -> int:
    """A rounded rectangle as a smoothed polygon (Tkinter has no native one)."""
    pts = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return c.create_polygon(pts, smooth=True, **kw)


def draw_creature(
    c: tk.Canvas, cx: float, cy: float, state: str, accent: str, R: float = 30.0,
    tag: str = "creature",
) -> None:
    """Draw the mascot centered at (cx, cy) for the given state.

    All items are tagged `tag` so the caller can move (bob) or delete the whole
    character as a group.
    """
    # --- antenna (its bulb glows in the state accent = the familiar's "mood") --
    bulb_x, bulb_y = cx + R * 0.16, cy - R * 1.74
    c.create_line(
        cx, cy - R * 1.0, cx - R * 0.05, cy - R * 1.4, bulb_x, bulb_y + R * 0.14,
        smooth=True, width=max(2, int(R * 0.08)), fill=BODY_DK,
        capstyle=tk.ROUND, tags=tag,
    )
    _oval(c, bulb_x, bulb_y, R * 0.15, fill=accent, outline="", tags=tag)
    _oval(c, bulb_x - R * 0.05, bulb_y - R * 0.05, R * 0.05, fill=GLINT, outline="", tags=tag)

    # --- feet ----------------------------------------------------------------
    _oval(c, cx - R * 0.42, cy + R * 1.04, R * 0.22, R * 0.16, fill=BODY_DK, outline="", tags=tag)
    _oval(c, cx + R * 0.42, cy + R * 1.04, R * 0.22, R * 0.16, fill=BODY_DK, outline="", tags=tag)

    # --- arms (little side nubs) --------------------------------------------
    arm_y = cy + R * 0.2
    _oval(c, cx - R * 0.98, arm_y, R * 0.2, R * 0.24, fill=BODY, outline=BODY_DK, width=1, tags=tag)
    _oval(c, cx + R * 0.98, arm_y, R * 0.2, R * 0.24, fill=BODY, outline=BODY_DK, width=1, tags=tag)

    # --- body + belly --------------------------------------------------------
    c.create_oval(cx - R, cy - R * 1.04, cx + R, cy + R * 1.12,
                  fill=BODY, outline=BODY_DK, width=2, tags=tag)
    _oval(c, cx, cy + R * 0.4, R * 0.62, R * 0.78, fill=BELLY, outline="", tags=tag)

    _draw_face(c, cx, cy, R, state, accent, tag)


# --- faces -----------------------------------------------------------------
def _draw_face(c: tk.Canvas, cx: float, cy: float, R: float, state: str, accent: str, tag: str) -> None:
    ey = cy - R * 0.16          # eye line
    ex = R * 0.42               # eye x offset from center
    er = R * 0.24               # eye radius
    lx, rx = cx - ex, cx + ex   # left/right eye centers
    my = cy + R * 0.34          # mouth center

    if state == "sleeping":
        _eyes_closed(c, lx, rx, ey, er, tag)
        _zzz(c, cx + R * 0.7, cy - R * 1.0, R, accent, tag)
        _mouth_line(c, cx, my, R * 0.22, tag)
        return

    if state == "dizzy":
        _eye_spiral(c, lx, ey, er, tag)
        _eye_spiral(c, rx, ey, er, tag)
        _mouth_wave(c, cx, my, R, tag)
        return

    if state == "waiting":
        _eyes_open(c, lx, rx, ey, er * 1.12, look=(0, -0.1), tag=tag)
        _brows(c, lx, rx, ey - er * 1.5, R, "raised", tag)
        _cheeks(c, cx, cy, R, tag)
        _oval(c, cx, my + R * 0.04, R * 0.16, R * 0.2, fill=MOUTH, outline="", tags=tag)  # "oh!"
        _accent_mark(c, cx + R * 1.05, cy - R * 0.5, R, accent, "!", tag)
        return

    if state == "working":
        _eyes_open(c, lx, rx, ey, er, look=(0, 0.15), squint=True, tag=tag)
        _brows(c, lx, rx, ey - er * 1.1, R, "focus", tag)
        _mouth_line(c, cx, my, R * 0.3, tag)
        _oval(c, rx + er * 1.1, ey - er * 0.6, R * 0.07, fill=accent, outline="", tags=tag)  # focus spark
        return

    if state == "thinking":
        _eyes_open(c, lx, rx, ey, er, look=(0.45, -0.5), tag=tag)
        _brows(c, lx, rx, ey - er * 1.4, R, "curious", tag)
        _cheeks(c, cx, cy, R, tag)
        # little flat, off-center mouth
        c.create_line(cx - R * 0.05, my, cx + R * 0.28, my - R * 0.04,
                      width=2, fill=MOUTH, capstyle=tk.ROUND, tags=tag)
        _thought_bubble(c, cx + R * 0.95, cy - R * 0.95, R, accent, tag)
        return

    # idle (default): calm and content
    _eyes_open(c, lx, rx, ey, er, look=(0, 0), tag=tag)
    _cheeks(c, cx, cy, R, tag)
    _smile(c, cx, my, R * 0.34, tag)


# --- eye / mouth primitives ------------------------------------------------
def _eyes_open(c, lx, rx, y, er, look=(0.0, 0.0), squint=False, tag="creature") -> None:
    ry = er * (0.6 if squint else 1.0)
    for x in (lx, rx):
        c.create_oval(x - er, y - ry, x + er, y + ry,
                      fill=EYE_WHITE, outline=BODY_DK, width=1, tags=tag)
        pr = er * 0.56
        px, py = x + look[0] * er * 0.55, y + look[1] * ry * 0.55
        _oval(c, px, py, pr, fill=PUPIL, outline="", tags=tag)
        _oval(c, px - pr * 0.35, py - pr * 0.35, pr * 0.32, fill=GLINT, outline="", tags=tag)


def _eyes_closed(c, lx, rx, y, er, tag="creature") -> None:
    # gentle ∩ arcs = peaceful closed eyes
    for x in (lx, rx):
        c.create_arc(x - er, y - er, x + er, y + er, start=20, extent=140,
                     style=tk.ARC, width=2, outline=PUPIL, tags=tag)


def _eye_spiral(c, x, y, er, tag="creature") -> None:
    c.create_arc(x - er, y - er, x + er, y + er, start=90, extent=250,
                 style=tk.ARC, width=2, outline=PUPIL, tags=tag)
    c.create_arc(x - er * 0.5, y - er * 0.5, x + er * 0.5, y + er * 0.5,
                 start=270, extent=250, style=tk.ARC, width=2, outline=PUPIL, tags=tag)
    _oval(c, x, y, er * 0.12, fill=PUPIL, outline="", tags=tag)


def _brows(c, lx, rx, y, R, kind, tag="creature") -> None:
    w = R * 0.26
    if kind == "raised":
        for x in (lx, rx):
            c.create_arc(x - w, y - R * 0.05, x + w, y + R * 0.3, start=20, extent=140,
                         style=tk.ARC, width=2, outline=BODY_DK, tags=tag)
    elif kind == "focus":  # angled inward = concentration
        c.create_line(lx - w, y, lx + w, y + R * 0.12, width=2, fill=BODY_DK, capstyle=tk.ROUND, tags=tag)
        c.create_line(rx - w, y + R * 0.12, rx + w, y, width=2, fill=BODY_DK, capstyle=tk.ROUND, tags=tag)
    elif kind == "curious":  # one raised
        c.create_line(lx - w, y + R * 0.08, lx + w, y - R * 0.02, width=2, fill=BODY_DK, capstyle=tk.ROUND, tags=tag)
        c.create_line(rx - w, y - R * 0.08, rx + w, y - R * 0.12, width=2, fill=BODY_DK, capstyle=tk.ROUND, tags=tag)


def _cheeks(c, cx, cy, R, tag="creature") -> None:
    for sx in (-1, 1):
        _oval(c, cx + sx * R * 0.6, cy + R * 0.16, R * 0.13, R * 0.1,
              fill=CHEEK, outline="", tags=tag)


def _smile(c, cx, my, w, tag="creature") -> None:
    c.create_arc(cx - w, my - w, cx + w, my + w, start=200, extent=140,
                 style=tk.ARC, width=2, outline=MOUTH, tags=tag)


def _mouth_line(c, cx, my, w, tag="creature") -> None:
    c.create_line(cx - w, my, cx + w, my, width=2, fill=MOUTH, capstyle=tk.ROUND, tags=tag)


def _mouth_wave(c, cx, my, R, tag="creature") -> None:
    w = R * 0.34
    c.create_line(cx - w, my, cx - w * 0.33, my - R * 0.12, cx + w * 0.33, my + R * 0.12,
                  cx + w, my, smooth=True, width=2, fill=MOUTH, capstyle=tk.ROUND, tags=tag)


# --- decorative accents ----------------------------------------------------
def _zzz(c, x, y, R, accent, tag="creature") -> None:
    c.create_text(x, y, text="z z z", font=("Segoe UI", max(7, int(R * 0.3)), "bold"),
                  fill=accent, tags=tag)


def _accent_mark(c, x, y, R, accent, text, tag="creature") -> None:
    c.create_text(x, y, text=text, font=("Segoe UI", max(9, int(R * 0.5)), "bold"),
                  fill=accent, tags=tag)


def _thought_bubble(c, x, y, R, accent, tag="creature") -> None:
    _oval(c, x - R * 0.18, y + R * 0.22, R * 0.07, fill=accent, outline="", tags=tag)
    _oval(c, x, y, R * 0.13, fill=accent, outline="", tags=tag)
