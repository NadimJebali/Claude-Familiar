"""Qt Pet window (issue #60) — the dashboard + shop over the PetHost seam.

The Tamagotchi dashboard in Qt: the pet sprite at its stage (wearing its hat), the
three need bars, coins, level, an editable name, and Shop / Items tabs with Buy /
Feed / Play. Every action goes through the pure :mod:`mascot.pet_actions` layer
over a :class:`~mascot.pet_host.PetHost`, which checks the move with the tested
``shop`` core and persists through the host (the single writer) — so the whole care
flow reuses the same logic the Tk window did, only re-skinned in Qt.

Runs **standalone** (``python -m mascot.qt_pet_window``, read-modify-writing
pet.json via ``pet_store``) or **in-process** against any PetHost. The window is a
fixed size, so rebuilding the shop/items lists on each action never shrinks-and-
grows it.

Still on the #60 list (kept open): the wardrobe tab (pairs with the card hat in
#57), a live per-second cooldown countdown, and pixel-art item icons; in-process
hosting from the Qt manager pairs with the pet-push wiring in #57.
"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import config, pet_actions, pet_logic, pet_store, shop
from .pet_host import PetHost
from .pet_view import pet_view
from .sprite_qt import QtPixmapRenderer, SpriteRenderer, SpriteSpec

PET_PX = 6
_BG = "#15161d"
_PANEL = "#1d1f29"
_FG = "#e8e6ef"
_SUB = "#8b8fa3"


def _hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def _clear(box: QVBoxLayout) -> None:
    """Remove and delete every item from a layout (rows are widgets)."""
    while box.count():
        item = box.takeAt(0)
        if item is None:
            break
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()


class QtPetWindow(QWidget):
    """The pet dashboard. Reads/persists the pet through its :class:`PetHost`."""

    def __init__(self, host: PetHost, *, renderer: SpriteRenderer | None = None,
                 on_close=None) -> None:
        super().__init__()
        self._host = host
        self._renderer = renderer or QtPixmapRenderer()
        self._on_close = on_close
        self.setWindowTitle("Claude Familiar — Pet")
        self.setStyleSheet(f"background:{_BG}; color:{_FG};")

        root = QVBoxLayout(self)

        header = QHBoxLayout()
        self._sprite = QLabel()
        self._sprite.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._sprite)
        info = QVBoxLayout()
        self._name = QLineEdit()
        self._name.setMaxLength(16)
        self._name.setPlaceholderText("Name your pet")
        self._name.editingFinished.connect(self._rename)
        self._level = QLabel()
        self._coins = QLabel()
        self._coins.setStyleSheet("font-weight:bold")
        info.addWidget(self._name)
        info.addWidget(self._level)
        info.addWidget(self._coins)
        info.addStretch()
        header.addLayout(info)
        root.addLayout(header)

        self._bars: dict[str, QProgressBar] = {}
        for need in pet_logic.NEED_STATS:
            row = QHBoxLayout()
            label = QLabel(need.capitalize())
            label.setFixedWidth(74)
            label.setStyleSheet(f"color:{_SUB}")
            bar = QProgressBar()
            bar.setRange(0, pet_logic.MAX_STAT)
            bar.setTextVisible(False)
            bar.setFixedHeight(12)
            bar.setStyleSheet(
                f"QProgressBar{{background:{_PANEL};border:none;border-radius:6px}}"
                f"QProgressBar::chunk{{background:{config.NEED_COLORS[need]};border-radius:6px}}")
            row.addWidget(label)
            row.addWidget(bar)
            root.addLayout(row)
            self._bars[need] = bar

        self._shop_box, shop_scroll = self._scroll_list()
        self._items_box, items_scroll = self._scroll_list()
        tabs = QTabWidget()
        tabs.addTab(shop_scroll, "Shop")
        tabs.addTab(items_scroll, "Items")
        root.addWidget(tabs)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{_SUB}")
        root.addWidget(self._status)

        self.setFixedSize(340, 560)   # pinned so list rebuilds never resize the window
        self._refresh()

    def _scroll_list(self) -> tuple[QVBoxLayout, QScrollArea]:
        host = QWidget()
        box = QVBoxLayout(host)
        box.setContentsMargins(2, 2, 2, 2)
        scroll = QScrollArea()
        scroll.setWidget(host)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        return box, scroll

    # --- actions (through the pure pet_actions layer) --------------------
    def _rename(self) -> None:
        pet = self._host.get_pet()
        pet["name"] = self._name.text().strip()
        self._host.save_pet(pet)

    def _buy(self, item: dict[str, Any]) -> None:
        self._status.setText(pet_actions.buy(self._host, item))
        self._refresh()

    def _feed(self, item: dict[str, Any]) -> None:
        self._status.setText(pet_actions.feed(self._host, item))
        self._refresh()

    def _play(self, item: dict[str, Any]) -> None:
        self._status.setText(pet_actions.play(self._host, item, time.time()))
        self._refresh()

    # --- render ----------------------------------------------------------
    def _refresh(self) -> None:
        pet = self._host.get_pet()
        now = time.time()
        view = pet_view(pet, now=now)
        level = pet_logic.level_for_xp(pet.get("xp", 0))

        self._sprite.setPixmap(self._renderer.creature(
            SpriteSpec(stage=view.stage, state="idle", accent=_hex(config.STATE_COLORS["idle"]),
                       hat=view.hat, flourish=view.flourish), PET_PX))
        if not self._name.hasFocus():
            self._name.setText(str(pet.get("name", "")))
        self._level.setText(f"Level {level} · {view.stage}")
        self._coins.setText(f"{pet.get('coins', 0)} coins")
        for need, bar in self._bars.items():
            bar.setValue(int(max(0, min(pet_logic.MAX_STAT, pet.get(need, 0)))))

        self._rebuild_shop(pet, level)
        self._rebuild_items(pet, level, now)

    def _rebuild_shop(self, pet: dict[str, Any], level: int) -> None:
        _clear(self._shop_box)
        for item in shop.CATALOG:
            ok, reason = shop.can_buy(pet, item, level)
            button = QPushButton("Buy" if ok else (reason or "Buy"))
            button.setEnabled(ok)
            button.clicked.connect(lambda _checked=False, it=item: self._buy(it))
            self._shop_box.addWidget(
                self._row(item["name"], f"{item['price']}c · {item['desc']}", button))
        self._shop_box.addStretch()

    def _rebuild_items(self, pet: dict[str, Any], level: int, now: float) -> None:
        _clear(self._items_box)
        any_owned = False
        for item in shop.CATALOG:
            count = shop.owned(pet, item)
            if count < 1:
                continue
            any_owned = True
            if item["type"] == shop.FOOD:
                button = QPushButton("Feed")
                button.clicked.connect(lambda _checked=False, it=item: self._feed(it))
                sub = f"×{count}"
            else:
                ok, reason = shop.can_play(pet, item, now)
                button = QPushButton("Play" if ok else reason)
                button.setEnabled(ok)
                button.clicked.connect(lambda _checked=False, it=item: self._play(it))
                sub = "toy"
            self._items_box.addWidget(self._row(item["name"], sub, button))
        if not any_owned:
            hint = QLabel("No items yet — visit the Shop.")
            hint.setStyleSheet(f"color:{_SUB}")
            self._items_box.addWidget(hint)
        self._items_box.addStretch()

    def _row(self, name: str, sub: str, button: QPushButton) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 2, 0, 2)
        text = QVBoxLayout()
        title = QLabel(name)
        title.setStyleSheet("font-weight:bold")
        desc = QLabel(sub)
        desc.setStyleSheet(f"color:{_SUB}; font-size:11px")
        text.addWidget(title)
        text.addWidget(desc)
        row.addLayout(text)
        row.addStretch()
        row.addWidget(button)
        return widget

    def closeEvent(self, event) -> None:
        if self._on_close is not None:
            self._on_close()
        super().closeEvent(event)


class QtStandaloneHost:
    """PetHost for the standalone window: read-modify-writes pet.json each action,
    so it never clobbers the manager's concurrent decay/awards. No cards to
    celebrate and it can't open itself, so those are no-ops; the pet is enabled."""

    pet_enabled = True

    def get_pet(self) -> dict[str, Any]:
        return pet_store.load(pet_store.PET_PATH, time.time())

    def save_pet(self, pet: dict[str, Any]) -> dict[str, Any]:
        return pet_store.save(pet_store.PET_PATH, pet, time.time())

    def notify_care(self) -> None:
        pass

    def open_pet(self) -> None:
        pass


def main() -> None:
    """Standalone entry point (e.g. from Settings), persisting straight to pet.json."""
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = QtPetWindow(QtStandaloneHost())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
