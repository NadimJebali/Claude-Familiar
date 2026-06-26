"""The launcher seam: one interface for 'make this app launchable', one fork.

'Making the app launchable' — registering it in the menu/desktop and managing the
run-at-login entry — is platform-specific (Windows ``.lnk`` files, freedesktop
``.desktop`` entries, eventually macOS LaunchAgents). Historically every caller
re-forked on ``IS_WINDOWS``. This module is the single place that fork lives: it
picks one :class:`~mascot.launchers.Launcher` adapter by platform, and every
caller goes through the small surface below instead of re-deriving the split.

A second adapter (Linux) already exists, so the seam is real, not hypothetical;
a macOS adapter slots in here without touching any caller.
"""
from __future__ import annotations

from pathlib import Path

from . import osplatform
from .launchers import Launcher


def _adapter() -> Launcher:
    """The launcher adapter for this platform — the one and only platform fork."""
    if osplatform.IS_WINDOWS:
        from .launchers.windows import WindowsLauncher
        return WindowsLauncher()
    from .launchers.linux import LinuxLauncher
    return LinuxLauncher()


def install(*, desktop: bool = True) -> list[Path]:
    """Register the app (menu entry always, desktop icon optional). Returns the
    launcher entries that now exist."""
    return _adapter().install(desktop=desktop)


def uninstall() -> None:
    """Remove the app's menu and desktop launcher entries."""
    _adapter().uninstall()


def is_installed() -> bool:
    """True if the app's menu entry exists (i.e. the app is 'installed')."""
    return _adapter().is_installed()


def set_autostart(enabled: bool) -> bool:
    """Enable or disable run-at-login (launches the widget). Returns success."""
    adapter = _adapter()
    return adapter.enable_autostart() if enabled else adapter.disable_autostart()


def autostart_enabled() -> bool:
    """True if the run-at-login entry exists."""
    return _adapter().autostart_enabled()
