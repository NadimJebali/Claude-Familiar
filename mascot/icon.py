"""App icon, rendered from the pixel mascot (single source of truth).

The same `sprite_pixel` idle grid that draws the on-screen creature also produces
the app icon, so they can never drift apart. Two outputs:

  * ``make_photo`` — a ``tk.PhotoImage`` for ``window.iconphoto`` (taskbar / title
    bar of the live windows).
  * ``ensure_ico`` — a Windows ``.ico`` file (for Start-up / desktop shortcuts),
    written as raw bytes so there are no external dependencies.
  * ``ensure_png`` — a ``.png`` file for Linux ``.desktop`` launchers, likewise
    written from scratch (zlib) with no third-party imaging library.

Use ``ensure_app_icon`` to get the right file for the current platform.
"""
from __future__ import annotations

import struct
import tkinter as tk
import zlib
from pathlib import Path

from . import osplatform, sprite_pixel

_ASSETS = Path(__file__).resolve().parent.parent / "assets"
ICON_PATH = _ASSETS / "claude_familiar.ico"
PNG_PATH = _ASSETS / "claude_familiar.png"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _pixel_rows() -> list[list[tuple[int, int, int] | None]]:
    """The idle mascot as a 16x16 grid of RGB tuples (``None`` = transparent)."""
    accent = _rgb(sprite_pixel.BODY)  # the sparkle reuses the body orange
    rows: list[list[tuple[int, int, int] | None]] = []
    for line in sprite_pixel.grid_for("baby", "idle"):
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
            box = (x * px, y * px, (x + 1) * px, (y + 1) * px)
            img.put("#{:02x}{:02x}{:02x}".format(*cell), to=box)
    return img


def apply(window: tk.Tk | tk.Toplevel) -> None:
    """Set the mascot as `window`'s icon (and the default for its children)."""
    try:
        photo = make_photo(window)
        window._app_icon = photo  # type: ignore[union-attr]  # keep a ref alive
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


# --- .png file (for Linux .desktop launchers) ------------------------------
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png_bytes(scale: int = 8) -> bytes:
    """A 32-bit RGBA PNG of the mascot (16*scale square), built with zlib only."""
    rows = _pixel_rows()
    h, w = len(rows) * scale, len(rows[0]) * scale

    raw = bytearray()
    for row in rows:
        line = bytearray()
        for cell in row:
            px = bytes((0, 0, 0, 0)) if cell is None else bytes((*cell, 255))
            line += px * scale  # horizontal scale
        for _ in range(scale):   # vertical scale
            raw.append(0)        # PNG filter type 0 (none) per scanline
            raw += line

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit, color type 6 (RGBA)
    return (sig + _png_chunk(b"IHDR", ihdr)
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _png_chunk(b"IEND", b""))


def ensure_png(path: Path = PNG_PATH) -> Path:
    """Write the .png (deriving it from the current sprite) and return its path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_bytes())
    return path


def ensure_app_icon() -> Path:
    """Write and return the app-icon file for the current OS (.ico / .png)."""
    return ensure_ico() if osplatform.IS_WINDOWS else ensure_png()
