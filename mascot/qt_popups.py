"""The Qt card's two satellite popups (issue #58): the speech bubble (shown while
Claude needs the user) and the pet hover tooltip (name, level, coins, need bars).

Both are frameless, always-on-top ``Tool`` windows that never steal focus
(``WA_ShowWithoutActivating``); their on-screen placement is delegated to the pure,
tested :mod:`mascot.popup_place` helpers so they stay on the card's own monitor and
can be positioned without a display. The Qt counterparts of ``mascot.popups``
(``BubbleWindow`` / ``StatsTooltip``).
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar, QVBoxLayout, QWidget

from . import config, pet_logic, popup_place

# --- speech bubble ---------------------------------------------------------
BUBBLE_W = 196
BUBBLE_GAP = 6
BUBBLE_MAX_CHARS = 160
BUBBLE_FILL = "#fdf6e3"
BUBBLE_TEXT = "#1c1e26"

_POPUP_FLAGS = (Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
                | Qt.WindowType.Tool)


class QtBubble(QWidget):
    """A speech bubble shown above a card while Claude needs the user."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.setWindowFlags(_POPUP_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._label = QLabel()
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(BUBBLE_W)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"background:{BUBBLE_FILL}; color:{BUBBLE_TEXT}; border:2px solid {BUBBLE_TEXT};"
            "border-radius:8px; padding:10px; font-size:12px;")
        layout.addWidget(self._label)
        self._message = ""
        self.set_message(message)

    def set_message(self, message: str) -> None:
        message = (message or "Claude needs your attention")[:BUBBLE_MAX_CHARS]
        if message == self._message:
            return
        self._message = message
        self._label.setText(message)
        self.adjustSize()

    def place_above(self, card_x: int, card_y: int, card_w: int,
                    bounds: tuple[int, int, int, int]) -> None:
        x, y = popup_place.above(card_x, card_y, card_w, self.width(), self.height(),
                                 bounds, BUBBLE_GAP)
        self.move(x, y)


# --- pet status tooltip ----------------------------------------------------
TIP_W = 160
TIP_FILL = "#1d1f29"
TIP_BORDER = "#2a2d3b"
TIP_FG = "#e8e8ef"
TIP_MUTED = "#9095a8"
TIP_GAP = 6
TIP_NEED_LABEL = {"hunger": "Food", "happiness": "Happy", "energy": "Energy"}


class QtStatsTooltip(QWidget):
    """A compact hover tooltip: the pet's name, level, coins, and three need bars,
    using the shared need colors; placed beside the card via the pure placement core."""

    def __init__(self, pet: dict | None) -> None:
        super().__init__()
        self.setWindowFlags(_POPUP_FLAGS)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setFixedWidth(TIP_W)
        self.setStyleSheet(
            f"QWidget{{background:{TIP_FILL}; border:1px solid {TIP_BORDER};}}"
            f"QLabel{{border:none; color:{TIP_FG};}}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        self._name = QLabel()
        self._name.setStyleSheet("font-weight:bold")
        self._sub = QLabel()
        self._sub.setStyleSheet(f"color:{TIP_MUTED}; font-size:11px")
        layout.addWidget(self._name)
        layout.addWidget(self._sub)

        self._bars: dict[str, QProgressBar] = {}
        for need in ("hunger", "happiness", "energy"):
            row = QVBoxLayout()
            row.setSpacing(1)
            label = QLabel(TIP_NEED_LABEL[need])
            label.setStyleSheet(f"color:{TIP_MUTED}; font-size:10px")
            bar = QProgressBar()
            bar.setRange(0, pet_logic.MAX_STAT)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            bar.setStyleSheet(
                f"QProgressBar{{background:{TIP_BORDER};border:none;border-radius:4px}}"
                f"QProgressBar::chunk{{background:{config.NEED_COLORS[need]};border-radius:4px}}")
            row.addWidget(label)
            row.addWidget(bar)
            layout.addLayout(row)
            self._bars[need] = bar

        self.set_pet(pet)

    def set_pet(self, pet: dict | None) -> None:
        pet = pet or {}
        self._name.setText((pet.get("name") or "Your Pet")[:16])
        level = pet_logic.level_for_xp(pet.get("xp", 0))
        self._sub.setText(f"Lv {level}  ·  {pet.get('coins', 0)} coins")
        for need, bar in self._bars.items():
            bar.setValue(int(max(0, min(pet_logic.MAX_STAT, pet.get(need, 0)))))
        self.adjustSize()

    def place_beside(self, card_x: int, card_y: int, card_w: int, card_h: int,
                     bounds: tuple[int, int, int, int]) -> None:
        x, y = popup_place.beside(card_x, card_y, card_w, card_h,
                                  self.width(), self.height(), bounds, gap=TIP_GAP)
        self.move(x, y)
