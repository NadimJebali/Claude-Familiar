"""App icon, rendered from the pixel mascot (single source of truth).

The same `sprite_pixel` idle grid that draws the on-screen creature also produces
the app icon, so they can never drift apart. Two outputs:

  * ``make_photo`` — a ``tk.PhotoImage`` for ``window.iconphoto`` (taskbar / title
    bar of the live windows).
  * ``ensure_ico`` — a Windows ``.ico`` file (for Start-up / desktop shortcuts),
    written as raw bytes so there are no external dependencies.
"""
from __future__ import annotations

import struct
import tkinter as tk
from pathlib import Path

from . import sprite_pixel

ICON_PATH = Path(__file__).resolve().parent.parent / "assets" / "claude_familiar.ico"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _pixel_rows() -> list[list[tuple[int, int, int] | None]]:
    """The idle mascot as a 16x16 grid of RGB tuples (``None`` = transparent)."""
    accent = _rgb(sprite_pixel.BODY)  # the sparkle reuses the body orange
    rows: list[list[tuple[int, int, int] | None]] = []
    for line in sprite_pixel._grid("idle"):
        cells: list[tuple[int, int, int] | None] = []
        for ch in line:
            if ch == ".":
                cells.append(None)
            elif ch == "a":
                cells.append(accent)
            else:
                cells.append(_rgb(sprite_pixel.COLORS[ch]))
        rows.append(cells)
    return rows


# --- live window icon ------------------------------------------------------
def make_photo(master: tk.Misc, px: int = 2) -> tk.PhotoImage:
    """A transparent-background PhotoImage of the mascot (16*px square)."""
    rows = _pixel_rows()
    h, w = len(rows) * px, len(rows[0]) * px
    img = tk.PhotoImage(master=master, width=w, height=h)
    for y, row in enumerate(rows):
        for x, cell in enumerate(row):
            if cell is None:
                continue
            img.put("#%02x%02x%02x" % cell, to=(x * px, y * px, (x + 1) * px, (y + 1) * px))
    return img


def apply(window: tk.Tk | tk.Toplevel) -> None:
    """Set the mascot as `window`'s icon (and the default for its children)."""
    try:
        photo = make_photo(window)
        window._app_icon = photo  # type: ignore[attr-defined]  # keep a ref alive
        window.iconphoto(True, photo)
    except tk.TclError:
        pass  # headless / unsupported — the widget still runs fine


# --- .ico file (for Windows shortcuts) -------------------------------------
def _ico_bytes(scale: int = 2) -> bytes:
    """A single-image 32-bit .ico (16*scale square) with an alpha channel."""
    rows = _pixel_rows()
    h, w = len(rows) * scale, len(rows[0]) * scale

    # Expand each cell `scale`x into a top-down BGRA grid.
    expanded: list[list[tuple[int, int, int, int]]] = []
    for row in rows:
        px_row: list[tuple[int, int, int, int]] = []
        for cell in row:
            bgra = (0, 0, 0, 0) if cell is None else (cell[2], cell[1], cell[0], 255)
            px_row.extend([bgra] * scale)
        expanded.extend([list(px_row) for _ in range(scale)])

    # XOR data is stored bottom-up; transparency comes from the alpha channel.
    xor = bytearray()
    for y in range(h - 1, -1, -1):
        for b, g, r, a in expanded[y]:
            xor += bytes((b, g, r, a))
    and_mask = bytes(((w + 31) // 32) * 4 * h)  # 1bpp, all zero

    header = struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    image = header + bytes(xor) + and_mask
    icondir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII", w & 0xFF, h & 0xFF, 0, 0, 1, 32, len(image), 6 + 16,
    )
    return icondir + entry + image


def ensure_ico(path: Path = ICON_PATH) -> Path:
    """Write the .ico (deriving it from the current sprite) and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_ico_bytes())
    return path
