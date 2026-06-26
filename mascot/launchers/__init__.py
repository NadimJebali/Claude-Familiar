"""Per-platform launcher adapters behind the :mod:`mascot.launcher` seam.

Each adapter knows how *one* desktop makes an app launchable — Windows ``.lnk``
files, freedesktop ``.desktop`` entries, (and, eventually, macOS LaunchAgents).
They all expose the same small surface (see :class:`Launcher`) so the seam can
pick one by platform and never re-fork on ``IS_WINDOWS`` again.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Launcher(Protocol):
    """What every platform adapter provides to the launcher seam.

    ``install`` registers the app (menu entry always, desktop icon optional) and
    returns the entries that now exist; ``uninstall`` removes them. The autostart
    pair manages the run-at-login entry (which launches the widget, not Settings).
    """

    def install(self, *, desktop: bool = True) -> list[Path]: ...

    def uninstall(self) -> None: ...

    def is_installed(self) -> bool: ...

    def enable_autostart(self) -> bool: ...

    def disable_autostart(self) -> bool: ...

    def autostart_enabled(self) -> bool: ...
