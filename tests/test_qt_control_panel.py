"""Tests for the Qt settings panel (issue #62).

The settings + setup logic is the shared, tested seams (settings_mod / setup); here
we check the panel builds from a settings dict, Save writes the same keys back, the
pet toggle greys its dependent controls, the display picker enumerates via Qt, and
Reset routes through the setup seam after confirmation. Offscreen; skips without
PySide6. Every external seam is faked so no test touches real settings / hooks / pet.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from mascot import qt_control_panel

_SETTINGS = {
    "widget_size": "medium", "simple_stage": "teen", "transparent_bg": True,
    "shake_after_s": 30, "shake_max_amp_px": 16, "home_monitor": -1,
    "tamagotchi_enabled": True, "native_notifications": False,
    "usage_api_enabled": False,
}


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _panel(monkeypatch, *, settings=None, screens=None):
    """A panel with every external seam faked (no real settings/hooks/pet access)."""
    monkeypatch.setattr(qt_control_panel.settings_mod, "load_settings",
                        lambda: dict(settings or _SETTINGS))
    monkeypatch.setattr(qt_control_panel.setup, "autostart_enabled", lambda: False)
    monkeypatch.setattr(qt_control_panel.setup, "shortcuts_installed", lambda: False)
    monkeypatch.setattr(qt_control_panel.setup, "hooks_installed", lambda: False)
    monkeypatch.setattr(qt_control_panel.qt_screens, "work_areas",
                        lambda: screens if screens is not None else [(0, 0, 1920, 1080)])
    return qt_control_panel.QtControlPanel()


def test_panel_builds_from_the_settings_dict(app, monkeypatch):
    panel = _panel(monkeypatch)
    assert panel._size.currentData() == "medium"
    assert panel._stage.currentData() == "teen"
    assert panel._transparent.isChecked()
    assert panel._shake_after.value() == 30
    assert panel._shake_amp.value() == 16
    assert panel._pet_enabled.isChecked()
    assert not panel._notify.isChecked()
    panel.close()


def test_save_persists_every_current_value(app, monkeypatch):
    panel = _panel(monkeypatch)
    captured: dict = {}
    monkeypatch.setattr(qt_control_panel.settings_mod, "save_settings",
                        lambda d: captured.update(d))
    monkeypatch.setattr(qt_control_panel.setup, "set_autostart", lambda e: e)

    panel._notify.setChecked(True)
    panel._usage_api.setChecked(True)      # opt in to the live-usage poller (#70)
    panel._save()

    assert captured["widget_size"] == "medium"
    assert captured["native_notifications"] is True
    assert captured["usage_api_enabled"] is True
    assert set(captured) == {
        "widget_size", "simple_stage", "transparent_bg", "shake_after_s",
        "shake_max_amp_px", "home_monitor", "tamagotchi_enabled", "native_notifications",
        "usage_api_enabled"}
    panel.close()


def test_pet_toggle_greys_dependent_controls(app, monkeypatch):
    panel = _panel(monkeypatch)
    panel._pet_enabled.setChecked(True)          # pet on
    assert panel._pet_btn.isEnabled() and panel._reset_btn.isEnabled()
    assert not panel._stage.isEnabled()          # simple-stage picker only when off

    panel._pet_enabled.setChecked(False)         # pet off
    assert not panel._pet_btn.isEnabled() and not panel._reset_btn.isEnabled()
    assert panel._stage.isEnabled()
    panel.close()


def test_display_picker_enumerates_monitors_via_qt(app, monkeypatch):
    panel = _panel(monkeypatch, screens=[(0, 0, 800, 600), (800, 0, 800, 600)])
    assert panel._monitor.count() == 3           # Auto + two monitors
    assert panel._monitor.itemData(0) == -1      # Auto (primary)
    assert panel._monitor.itemData(2) == 1
    panel.close()


def test_reset_routes_through_the_setup_seam_after_confirm(app, monkeypatch):
    panel = _panel(monkeypatch)
    called: list[bool] = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(qt_control_panel.setup, "reset_pet",
                        lambda: (called.append(True), (True, "Reset done."))[1])
    panel._reset_pet()
    assert called == [True]
    assert "Reset" in panel._status.text()
    panel.close()
