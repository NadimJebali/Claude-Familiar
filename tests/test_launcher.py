"""Tests for the launcher seam + platform adapters (#28).

The platform fork lives once in :mod:`mascot.launcher`; the adapters are
exercised cross-platform for adapter selection, destination-path selection, and
the freedesktop ``.desktop`` round-trip (writing into a temp dir, with the icon
stubbed so the real generated icon is never touched). The Windows ``.lnk`` COM
round-trip stays gated in ``test_shortcuts.py``.
"""
from __future__ import annotations

from mascot import autostart, desktop_entry, launcher, osplatform, shortcuts
from mascot.launchers.linux import LinuxLauncher
from mascot.launchers.windows import WindowsLauncher


# --- the one platform fork lives in the seam -------------------------------
def test_adapter_is_windows_launcher_on_windows(monkeypatch):
    monkeypatch.setattr(osplatform, "IS_WINDOWS", True)
    assert isinstance(launcher._adapter(), WindowsLauncher)


def test_adapter_is_linux_launcher_off_windows(monkeypatch):
    monkeypatch.setattr(osplatform, "IS_WINDOWS", False)
    assert isinstance(launcher._adapter(), LinuxLauncher)


# --- destinations match the historical (pre-seam) paths --------------------
def test_windows_destinations_match_shortcuts_paths():
    from mascot.launchers import windows
    assert windows.START_MENU_SHORTCUT == shortcuts.START_MENU_SHORTCUT
    assert windows.DESKTOP_SHORTCUT == shortcuts.DESKTOP_SHORTCUT
    # run-at-login lands in the Startup folder under Start menu / Programs.
    assert windows.STARTUP_SHORTCUT.parent.name == "Startup"
    assert windows.STARTUP_SHORTCUT.name.endswith(".lnk")


def test_linux_autostart_entry_is_under_xdg_config_autostart():
    from mascot.launchers import linux
    assert linux.AUTOSTART_ENTRY.name == shortcuts.DESKTOP_FILE_NAME
    assert linux.AUTOSTART_ENTRY.parent.name == "autostart"


# --- freedesktop .desktop round-trip (cross-platform, no side effects) -----
def _patch_linux_paths(monkeypatch, tmp_path):
    menu = tmp_path / "applications" / shortcuts.DESKTOP_FILE_NAME
    desk = tmp_path / "Desktop" / shortcuts.DESKTOP_FILE_NAME
    monkeypatch.setattr("mascot.launchers.linux.MENU_ENTRY", menu)
    monkeypatch.setattr("mascot.launchers.linux.DESKTOP_ENTRY", desk)
    # Never write the real generated icon during a test.
    monkeypatch.setattr("mascot.icon.ensure_png", lambda *a, **k: tmp_path / "i.png")
    return menu, desk


def test_linux_install_creates_menu_and_desktop_entries(monkeypatch, tmp_path):
    menu, desk = _patch_linux_paths(monkeypatch, tmp_path)
    adapter = LinuxLauncher()

    created = adapter.install()

    assert set(created) == {menu, desk}
    assert menu.exists() and desk.exists()
    assert "[Desktop Entry]" in menu.read_text(encoding="utf-8")
    assert adapter.is_installed() is True


def test_linux_install_without_desktop_creates_only_menu(monkeypatch, tmp_path):
    menu, desk = _patch_linux_paths(monkeypatch, tmp_path)

    created = LinuxLauncher().install(desktop=False)

    assert created == [menu]
    assert menu.exists() and not desk.exists()


def test_linux_uninstall_removes_both_entries(monkeypatch, tmp_path):
    menu, desk = _patch_linux_paths(monkeypatch, tmp_path)
    adapter = LinuxLauncher()
    adapter.install()
    assert menu.exists() and desk.exists()

    adapter.uninstall()

    assert not menu.exists() and not desk.exists()
    assert adapter.is_installed() is False


def test_linux_enable_autostart_launches_the_widget(monkeypatch, tmp_path):
    entry = tmp_path / "autostart" / shortcuts.DESKTOP_FILE_NAME
    monkeypatch.setattr("mascot.launchers.linux.AUTOSTART_ENTRY", entry)
    monkeypatch.setattr("mascot.icon.ensure_png", lambda *a, **k: tmp_path / "i.png")
    adapter = LinuxLauncher()

    assert adapter.enable_autostart() is True
    assert entry.exists()
    # The run-at-login entry launches the widget (run_mascot.py), not Settings.
    assert "run_mascot.py" in entry.read_text(encoding="utf-8")
    assert adapter.autostart_enabled() is True

    assert adapter.disable_autostart() is True
    assert not entry.exists()


# --- the .desktop text the adapter emits -----------------------------------
def test_desktop_entry_build_has_required_fields():
    text = desktop_entry.build(
        "Claude Familiar", '"py" -m mascot.control_panel',
        comment="Settings", icon="/i.png", path="/root")
    for needle in ("[Desktop Entry]", "Type=Application", "Name=Claude Familiar",
                   "Exec=", "Terminal=false", "Categories="):
        assert needle in text


# --- autostart is now a thin shim over the launcher seam -------------------
def test_autostart_shim_delegates_to_launcher(monkeypatch):
    calls: list[bool] = []
    monkeypatch.setattr(launcher, "set_autostart", lambda flag: (calls.append(flag), True)[1])
    monkeypatch.setattr(launcher, "autostart_enabled", lambda: True)

    assert autostart.enable() is True
    assert autostart.disable() is True
    assert autostart.set_enabled(True) is True
    assert autostart.is_enabled() is True
    assert calls == [True, False, True]
