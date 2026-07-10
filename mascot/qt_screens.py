"""Monitor work areas via Qt (issue #62), retiring the Win32 ``osplatform``
enumeration for the Qt path.

The home-monitor setting is an integer index; the settings picker (which lists the
monitors) and the card placement (which reads the setting) must agree on what index
*N* means. Both now enumerate through :class:`QGuiApplication` screens, in
``screens()`` order, so they stay in sync on any platform.
"""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication, QScreen

Area = tuple[int, int, int, int]


def _rect(screen: QScreen) -> Area:
    g = screen.availableGeometry()
    return (g.x(), g.y(), g.width(), g.height())


def work_areas() -> list[Area]:
    """Every screen's usable work area ``(x, y, width, height)``, in ``screens()``
    order — the index space the ``home_monitor`` setting and the picker share."""
    return [_rect(s) for s in QGuiApplication.screens()]


def choose(home_monitor: object, areas: list[Area]) -> Area | None:
    """The work area to anchor cards to for the ``home_monitor`` setting: an in-range
    index selects that monitor; anything else (the -1/"auto" sentinel, an out-of-range
    or unplugged index, a non-int) falls back to the primary screen (``None`` only if
    there is no screen at all)."""
    if isinstance(home_monitor, int) and 0 <= home_monitor < len(areas):
        return areas[home_monitor]
    primary = QGuiApplication.primaryScreen()
    return _rect(primary) if primary is not None else None
