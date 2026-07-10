"""Qt Pet window (issue #60) — the dashboard + shop over the PetHost seam.

The Tamagotchi dashboard in Qt: the pet sprite at its stage (wearing its hat), the
three need bars, coins, level, an editable name, and Shop / Items / Wardrobe tabs
with Buy / Feed / Play (a live per-second cooldown countdown) and Wear / remove.
Shop and item rows carry pixel-art icons (``item_art`` grids) and wardrobe rows the
hat icon. Every action goes through the pure :mod:`mascot.pet_actions` layer over a
:class:`~mascot.pet_host.PetHost`, which checks the move with the tested ``shop`` /
``cosmetics`` cores and persists through the host (the single writer) — so the whole
care flow reuses the same logic the Tk window did, only re-skinned in Qt.

Runs **standalone** (``python -m mascot.qt_pet_window``, read-modify-writing
pet.json via ``pet_store``) or **in-process** against any PetHost. A once-a-second
poll drives the cooldown countdown and picks up an external edit (the manager's
decay/awards, or the other surface) without a restart; the scrollable lists rebuild
only when the shop-relevant state changes, and the window is a fixed size, so a
rebuild never shrinks-and-grows it.
"""
from __future__ import annotations

import time
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
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

from . import config, cosmetics, item_art, pet_actions, pet_logic, pet_store, shop, sprite_pixel
from .pet_host import PetHost
from .pet_view import pet_view
from .pixel_qt import grid_pixmap
from .sprite_qt import QtPixmapRenderer, SpriteRenderer, SpriteSpec

PET_PX = 6
ICON_PX = 2             # pixel size for the 12x12 shop-item / hat icons
POLL_MS = 1000          # live tick: cooldown countdown + external-change pickup
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
        self._wardrobe_box, wardrobe_scroll = self._scroll_list()
        tabs = QTabWidget()
        tabs.addTab(shop_scroll, "Shop")
        tabs.addTab(items_scroll, "Items")
        tabs.addTab(wardrobe_scroll, "Wardrobe")
        root.addWidget(tabs)

        self._status = QLabel("")
        self._status.setStyleSheet(f"color:{_SUB}")
        root.addWidget(self._status)

        # Live state: the last-seen pet, the list-rebuild signature (so the scrollable
        # lists only rebuild when the shop-relevant state actually changes, not every
        # tick), and the owned toys whose Play button counts down each second.
        self._pet: dict[str, Any] = {}
        self._sig: tuple | None = None
        self._cooldowns: dict[str, tuple[dict[str, Any], QPushButton]] = {}

        self.setFixedSize(340, 560)   # pinned so list rebuilds never resize the window
        self._poll()

        # One tick drives both the cooldown countdown and picking up an external edit
        # (the manager's decay/awards, or the other surface) without a restart.
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

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
        self._poll()

    def _feed(self, item: dict[str, Any]) -> None:
        self._status.setText(pet_actions.feed(self._host, item))
        self._poll()

    def _play(self, item: dict[str, Any]) -> None:
        self._status.setText(pet_actions.play(self._host, item, time.time()))
        self._poll()

    def _wear(self, piece_id: str | None) -> None:
        self._status.setText(pet_actions.wear(self._host, piece_id))
        self._poll()

    def _buy_cosmetic(self, piece: dict[str, Any]) -> None:
        self._status.setText(pet_actions.buy_cosmetic(self._host, piece))
        self._poll()

    # --- render ----------------------------------------------------------
    def _poll(self) -> None:
        """The live tick: always refresh the sprite / bars / cooldowns, but rebuild
        the scrollable lists only when the shop-relevant state changes — so an
        external edit (manager decay/awards, or the other surface) shows without a
        restart, while the lists don't churn under the pointer every second."""
        pet = self._host.get_pet()
        now = time.time()
        level = pet_logic.level_for_xp(pet.get("xp", 0))
        self._pet = pet
        self._sync_live(pet, level, now)

        sig = (level, pet.get("coins", 0),
               tuple(sorted(pet.get("inventory", {}).items())),
               tuple(pet.get("wardrobe", [])), cosmetics.equipped_head(pet))
        if sig != self._sig:
            self._sig = sig
            self._rebuild_shop(pet, level)
            self._rebuild_items(pet, level, now)
            self._rebuild_wardrobe(pet, level)
        self._update_cooldowns(now)

    def _sync_live(self, pet: dict[str, Any], level: int, now: float) -> None:
        """The bits that update every tick: sprite, name, level, coins, need bars."""
        view = pet_view(pet, now=now)
        self._sprite.setPixmap(self._renderer.creature(
            SpriteSpec(stage=view.stage, state="idle", accent=_hex(config.STATE_COLORS["idle"]),
                       hat=view.hat, flourish=view.flourish), PET_PX))
        if not self._name.hasFocus():
            self._name.setText(str(pet.get("name", "")))
        self._level.setText(f"Level {level} · {view.stage}")
        self._coins.setText(f"{pet.get('coins', 0)} coins")
        for need, bar in self._bars.items():
            bar.setValue(int(max(0, min(pet_logic.MAX_STAT, pet.get(need, 0)))))

    def _rebuild_shop(self, pet: dict[str, Any], level: int) -> None:
        _clear(self._shop_box)
        for item in shop.CATALOG:
            ok, reason = shop.can_buy(pet, item, level)
            button = QPushButton("Buy" if ok else (reason or "Buy"))
            button.setEnabled(ok)
            button.clicked.connect(lambda _checked=False, it=item: self._buy(it))
            self._shop_box.addWidget(
                self._row(item["name"], f"{item['price']}c · {item['desc']}", button,
                          self._item_icon(item["id"])))
        self._shop_box.addStretch()

    def _rebuild_items(self, pet: dict[str, Any], level: int, now: float) -> None:
        _clear(self._items_box)
        self._cooldowns = {}
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
                button = QPushButton("Play")
                button.clicked.connect(lambda _checked=False, it=item: self._play(it))
                # The label/enabled state is set live by _update_cooldowns each second.
                self._cooldowns[item["id"]] = (item, button)
                sub = "toy"
            self._items_box.addWidget(
                self._row(item["name"], sub, button, self._item_icon(item["id"])))
        if not any_owned:
            hint = QLabel("No items yet — visit the Shop.")
            hint.setStyleSheet(f"color:{_SUB}")
            self._items_box.addWidget(hint)
        self._items_box.addStretch()

    def _rebuild_wardrobe(self, pet: dict[str, Any], level: int) -> None:
        _clear(self._wardrobe_box)
        worn = cosmetics.equipped_head(pet)
        for piece in cosmetics.CATALOG:
            if cosmetics.owns(pet, piece):
                wearing = worn == piece["id"]
                button = QPushButton("Wearing ✓" if wearing else "Wear")
                button.clicked.connect(
                    lambda _checked=False, pid=piece["id"], w=wearing:
                    self._wear(None if w else pid))
                sub = piece["desc"]
            elif cosmetics.is_milestone(piece):
                button = QPushButton("Locked")
                button.setEnabled(False)
                got = min(pet.get("days_active", 0), piece["days_active"])
                sub = f"{cosmetics.requirement_text(piece)} ({got}/{piece['days_active']})"
            else:
                ok, _reason = cosmetics.can_buy(pet, piece, level)
                button = QPushButton("Buy")
                button.setEnabled(ok)
                button.clicked.connect(
                    lambda _checked=False, pc=piece: self._buy_cosmetic(pc))
                sub = (f"{piece['price']} coins" if level >= piece.get("min_level", 1)
                       else f"Unlocks at level {piece['min_level']}")
            self._wardrobe_box.addWidget(
                self._row(piece["name"], sub, button, self._hat_icon(piece["id"])))
        self._wardrobe_box.addStretch()

    def _update_cooldowns(self, now: float) -> None:
        """Tick each owned toy's Play button + countdown live, so the cooldown counts
        down without rebuilding the Items list every second."""
        for item, button in self._cooldowns.values():
            ok, reason = shop.can_play(self._pet, item, now)
            button.setEnabled(ok)
            button.setText("Play" if ok else reason)

    # --- pixel-art icons -------------------------------------------------
    def _item_icon(self, item_id: str) -> QLabel | None:
        if not item_art.has_art(item_id):
            return None
        return self._icon_label(grid_pixmap(item_art._ITEMS[item_id], item_art.PALETTE, ICON_PX))

    def _hat_icon(self, piece_id: str) -> QLabel | None:
        hat = sprite_pixel._HATS.get(piece_id)
        if hat is None:
            return None
        return self._icon_label(grid_pixmap(hat["grid"], hat["colors"], ICON_PX))

    def _icon_label(self, pixmap: QPixmap) -> QLabel:
        label = QLabel()
        label.setPixmap(pixmap)
        label.setFixedWidth(pixmap.width())
        return label

    def _row(self, name: str, sub: str, button: QPushButton,
             icon: QLabel | None = None) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 2, 0, 2)
        if icon is not None:
            row.addWidget(icon)
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
        self._timer.stop()
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
