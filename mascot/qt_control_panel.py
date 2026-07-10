"""Qt settings panel (issue #62) — the Qt port of :mod:`mascot.control_panel`.

Standalone-launchable (``python -m mascot.qt_control_panel``), it reads the existing
settings file as-is and Save & Apply writes it back with the same keys/semantics, so
the old Tk widget and the new Qt widget read each other's settings unchanged. Every
setting and action from the Tk panel is here: widget size, transparency, simple-mode
life stage, the home-monitor display picker (enumerated via Qt), the attention-shake
sliders, native notifications, the Tamagotchi toggle (live-greying the Pet + Reset
controls), reset-with-confirm, launch widget, Start-menu shortcuts, autostart, and
the Claude Code hooks install status. The shortcut / autostart / hooks / reset logic
is the same platform ``setup`` seam the Tk panel calls — not rewritten. Icons are the
pixel-art grids (no emoji).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import config, qt_screens, setup, ui_icons
from . import settings as settings_mod
from .pixel_qt import grid_pixmap
from .sprite_qt import QtPixmapRenderer, SpriteSpec

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_BG = "#15161d"
_PANEL = "#1d1f29"
_FG = "#e8e8ef"
_MUTED = "#9095a8"
_ACCENT = "#d9885a"
_OK = "#5fd08a"
_WARN = "#ed8936"
_DANGER = "#e06c75"

_SIZES = [("Small", "small"), ("Medium", "medium"), ("Large", "large")]
_STAGES = [("Egg", "egg"), ("Baby", "baby"), ("Teen", "teen"), ("Adult", "adult")]
_PREVIEW_PX = {"small": 4, "medium": 5, "large": 6}


def _icon_label(pixmap: QPixmap) -> QLabel:
    label = QLabel()
    label.setPixmap(pixmap)
    label.setFixedWidth(pixmap.width())
    return label


class QtControlPanel(QWidget):
    """The settings window. Reads/writes the shared settings file via the same
    ``settings`` + ``setup`` seams the Tk panel uses."""

    def __init__(self) -> None:
        super().__init__()
        self._renderer = QtPixmapRenderer()
        s = settings_mod.load_settings()
        self.setWindowTitle("Claude Familiar — Settings")
        self.setStyleSheet(
            f"QWidget{{background:{_BG}; color:{_FG};}}"
            f"QLabel{{background:transparent;}}"
            f"QTabWidget::pane{{border:1px solid #2f3242; background:{_PANEL};}}"
            f"QTabBar::tab{{background:{_BG}; padding:6px 12px;}}"
            f"QTabBar::tab:selected{{background:{_PANEL}; color:{_ACCENT};}}")

        root = QVBoxLayout(self)
        root.addLayout(self._build_header())

        tabs = QTabWidget()
        tabs.addTab(self._tab_appearance(s), "Appearance")
        tabs.addTab(self._tab_behavior(s), "Behavior")
        tabs.addTab(self._tab_setup(), "Setup")
        root.addWidget(tabs)

        root.addLayout(self._build_footer())
        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{_MUTED}")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self.setFixedWidth(440)
        self._refresh_pet_controls()
        self._refresh_install()
        self._refresh_hooks()
        self._draw_preview()

    # --- layout ----------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.addWidget(_icon_label(grid_pixmap(ui_icons._ICONS["paw"], ui_icons.PALETTE, 2)))
        title = QLabel("Claude Familiar")
        title.setStyleSheet(f"font-size:16px; font-weight:bold; color:{_ACCENT}")
        header.addWidget(title)
        sub = QLabel("settings")
        sub.setStyleSheet(f"color:{_MUTED}")
        header.addWidget(sub)
        header.addStretch()
        return header

    def _tab_appearance(self, s: dict) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(_section("WIDGET SIZE"))
        self._size = _combo(_SIZES, s["widget_size"], self._draw_preview)
        left.addWidget(self._size)

        left.addWidget(_section("MASCOT LOOK"))
        left.addWidget(_muted("Used when the Tamagotchi pet is off — which life stage "
                              "the mascot shows."))
        self._stage = _combo(_STAGES, s["simple_stage"], self._draw_preview)
        left.addWidget(self._stage)
        left.addStretch()
        body.addLayout(left)

        self._preview = QLabel()
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setFixedSize(132, 150)
        self._preview.setStyleSheet(f"background:{_PANEL}; border-radius:12px")
        body.addWidget(self._preview)
        box.addLayout(body)

        box.addWidget(_section("CARD"))
        self._transparent = QCheckBox("Transparent background — floating card (Windows only)")
        self._transparent.setChecked(bool(s["transparent_bg"]))
        box.addWidget(self._transparent)

        box.addWidget(_section("DISPLAY"))
        box.addWidget(_muted("Which monitor the cards spawn on."))
        self._monitor = QComboBox()
        self._monitor.addItem("Auto (primary)", -1)
        for i in range(len(qt_screens.work_areas())):     # enumerated via Qt
            self._monitor.addItem(f"Monitor {i + 1}", i)
        self._monitor.setCurrentIndex(max(0, int(s["home_monitor"]) + 1))
        box.addWidget(self._monitor)
        box.addStretch()
        return tab

    def _tab_behavior(self, s: dict) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)
        box.addWidget(_section("ATTENTION SHAKE"))
        box.addWidget(_muted("When an unanswered prompt makes the card shake — and how "
                             "hard it gets the longer you ignore it."))

        self._shake_after, self._shake_after_label, after_row = _slider_row(
            "Start shaking after", 5, 120, int(s["shake_after_s"]), self._sync_labels)
        box.addLayout(after_row)
        self._shake_amp, self._shake_amp_label, amp_row = _slider_row(
            "How violent", 4, 40, int(s["shake_max_amp_px"]), self._sync_labels)
        box.addLayout(amp_row)

        box.addWidget(_section("NOTIFICATIONS"))
        self._notify = QCheckBox("Show native system notifications")
        self._notify.setChecked(bool(s["native_notifications"]))
        box.addWidget(self._notify)

        box.addWidget(_section("TAMAGOTCHI PET"))
        self._pet_enabled = QCheckBox("Enable the Tamagotchi pet")
        self._pet_enabled.setChecked(bool(s["tamagotchi_enabled"]))
        self._pet_enabled.toggled.connect(self._refresh_pet_controls)
        box.addWidget(self._pet_enabled)
        box.addWidget(_muted("Off = a simple hook-state visualiser: the same live faces, "
                             "but no pet, coins, mood, or popups. Progress is kept."))
        box.addStretch()
        self._sync_labels()
        return tab

    def _tab_setup(self) -> QWidget:
        tab = QWidget()
        box = QVBoxLayout(tab)

        box.addWidget(_section("INSTALL"))
        srow = QHBoxLayout()
        self._install_label = QLabel("")
        self._install_btn = QPushButton("")
        self._install_btn.clicked.connect(self._toggle_install)
        srow.addWidget(self._install_label)
        srow.addStretch()
        srow.addWidget(self._install_btn)
        box.addLayout(srow)

        self._autostart = QCheckBox("Run automatically when Windows starts")
        self._autostart.setChecked(setup.autostart_enabled())
        box.addWidget(self._autostart)

        box.addWidget(_section("CLAUDE CODE HOOKS"))
        hrow = QHBoxLayout()
        self._hooks_label = QLabel("")
        hooks_btn = QPushButton("Install / update")
        hooks_btn.clicked.connect(self._install_hooks)
        hrow.addWidget(self._hooks_label)
        hrow.addStretch()
        hrow.addWidget(hooks_btn)
        box.addLayout(hrow)

        box.addWidget(_section("PET"))
        prow = QHBoxLayout()
        prow.addWidget(_muted("Start over with a brand-new egg — clears coins, XP, level, "
                              "needs, name & items."), stretch=1)
        self._reset_btn = QPushButton("Reset progress")
        self._reset_btn.setStyleSheet(f"color:{_DANGER}")
        self._reset_btn.clicked.connect(self._reset_pet)
        prow.addWidget(self._reset_btn)
        box.addLayout(prow)

        danger = _section("DANGER ZONE")
        danger.setStyleSheet(f"color:{_DANGER}; font-weight:bold; font-size:11px")
        box.addWidget(danger)
        drow = QHBoxLayout()
        drow.addWidget(_muted("Remove hooks, shortcuts, settings & icon — reset to "
                              "original."), stretch=1)
        uninstall_btn = QPushButton("Uninstall")
        uninstall_btn.setStyleSheet(f"color:{_DANGER}")
        uninstall_btn.clicked.connect(self._uninstall)
        drow.addWidget(uninstall_btn)
        box.addLayout(drow)
        box.addStretch()
        return tab

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        save = QPushButton("Save & Apply")
        save.setStyleSheet(f"background:{_ACCENT}; color:#1c1e26; font-weight:bold; padding:6px")
        save.clicked.connect(self._save)
        launch = QPushButton("Launch widget")
        launch.clicked.connect(self._launch)
        self._pet_btn = QPushButton("Pet")
        self._pet_btn.clicked.connect(self._open_pet)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        footer.addWidget(save)
        footer.addWidget(launch)
        footer.addWidget(self._pet_btn)
        footer.addStretch()
        footer.addWidget(close)
        return footer

    # --- preview + live sync ---------------------------------------------
    def _draw_preview(self) -> None:
        pet_on = self._pet_enabled.isChecked() if hasattr(self, "_pet_enabled") else True
        size = self._size.currentData()
        stage = "baby" if pet_on else self._stage.currentData()
        r, g, b = config.STATE_COLORS["idle"]
        self._preview.setPixmap(self._renderer.creature(
            SpriteSpec(stage=stage, state="idle", accent=f"#{r:02x}{g:02x}{b:02x}"),
            _PREVIEW_PX.get(size, 5)))

    def _sync_labels(self) -> None:
        self._shake_after_label.setText(f"{self._shake_after.value()}s")
        amp = self._shake_amp.value()
        self._shake_amp_label.setText(
            "gentle" if amp <= 8 else "medium" if amp <= 18
            else "rough" if amp <= 28 else "violent")

    def _refresh_pet_controls(self) -> None:
        """Grey the pet-management controls (Pet + Reset) when the pet is off; the
        simple-stage picker is the inverse (only meaningful with the pet off)."""
        pet_on = self._pet_enabled.isChecked()
        self._pet_btn.setEnabled(pet_on)
        self._reset_btn.setEnabled(pet_on)
        self._stage.setEnabled(not pet_on)
        self._draw_preview()

    def _refresh_install(self) -> None:
        if setup.shortcuts_installed():
            self._install_label.setText("Added to Start menu")
            self._install_label.setStyleSheet(f"color:{_OK}")
            self._install_btn.setText("Remove")
        else:
            self._install_label.setText("Not in Start menu")
            self._install_label.setStyleSheet(f"color:{_WARN}")
            self._install_btn.setText("Add to Start menu")

    def _refresh_hooks(self) -> None:
        if setup.hooks_installed():
            self._hooks_label.setText("Installed")
            self._hooks_label.setStyleSheet(f"color:{_OK}")
        else:
            self._hooks_label.setText("Not installed")
            self._hooks_label.setStyleSheet(f"color:{_WARN}")

    # --- actions (same setup / settings seams as the Tk panel) -----------
    def _save(self) -> None:
        settings_mod.save_settings({
            "widget_size": self._size.currentData(),
            "simple_stage": self._stage.currentData(),
            "transparent_bg": self._transparent.isChecked(),
            "shake_after_s": self._shake_after.value(),
            "shake_max_amp_px": self._shake_amp.value(),
            "home_monitor": int(self._monitor.currentData()),
            "tamagotchi_enabled": self._pet_enabled.isChecked(),
            "native_notifications": self._notify.isChecked(),
        })
        self._autostart.setChecked(setup.set_autostart(self._autostart.isChecked()))
        self._status.setText("Saved. Restart the widget for these changes to take effect.")

    def _toggle_install(self) -> None:
        _installed, msg = setup.toggle_shortcuts()
        self._status.setText(msg)
        self._refresh_install()

    def _install_hooks(self) -> None:
        _ok, msg = setup.install_hooks()
        self._refresh_hooks()
        self._status.setText(msg)

    def _launch(self) -> None:
        try:
            subprocess.Popen([sys.executable, "-m", "mascot.qt_app"], cwd=str(PROJECT_ROOT))
            self._status.setText("Widget launched.")
        except OSError as exc:
            self._status.setText(f"Could not launch widget: {exc}")

    def _open_pet(self) -> None:
        try:
            subprocess.Popen([sys.executable, "-m", "mascot.qt_pet_window"],
                             cwd=str(PROJECT_ROOT))
            self._status.setText("Opened the Pet window.")
        except OSError as exc:
            self._status.setText(f"Could not open Pet window: {exc}")

    def _reset_pet(self) -> None:
        if QMessageBox.question(
            self, "Reset pet progress",
            "Start over with a brand-new egg?\n\nThis clears the pet's coins, XP, "
            "level, needs, name, and inventory, and can't be undone.",
        ) != QMessageBox.StandardButton.Yes:
            return
        _ok, msg = setup.reset_pet()
        self._status.setText(msg)   # a running widget picks it up via external reload

    def _uninstall(self) -> None:
        if QMessageBox.question(
            self, "Uninstall Claude Familiar",
            "This removes the Claude Code hooks, shortcuts, saved settings and session "
            "state, and the generated app icon — resetting everything.\n\nContinue?",
        ) != QMessageBox.StandardButton.Yes:
            return
        actions = setup.uninstall()
        QMessageBox.information(self, "Claude Familiar uninstalled",
                                "Done:\n\n" + "\n".join(f"• {a}" for a in actions))
        self.close()


# --- small widget builders -------------------------------------------------
def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{_ACCENT}; font-weight:bold; font-size:11px")
    return label


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setStyleSheet(f"color:{_MUTED}; font-size:11px")
    label.setWordWrap(True)
    return label


def _combo(options: list[tuple[str, str]], current: str, on_change) -> QComboBox:
    combo = QComboBox()
    for label, value in options:
        combo.addItem(label, value)
    idx = next((i for i, (_, v) in enumerate(options) if v == current), 0)
    combo.setCurrentIndex(idx)
    combo.currentIndexChanged.connect(lambda _i: on_change())
    return combo


def _slider_row(label: str, lo: int, hi: int, value: int,
                on_change) -> tuple[QSlider, QLabel, QHBoxLayout]:
    row = QHBoxLayout()
    row.addWidget(QLabel(label))
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(lo, hi)
    slider.setValue(value)
    slider.valueChanged.connect(lambda _v: on_change())
    row.addWidget(slider, stretch=1)
    read_out = QLabel("")
    read_out.setStyleSheet(f"color:{_MUTED}")
    read_out.setFixedWidth(56)
    read_out.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    row.addWidget(read_out)
    return slider, read_out, row


def main() -> None:
    app = QApplication(sys.argv)
    panel = QtControlPanel()
    panel.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
