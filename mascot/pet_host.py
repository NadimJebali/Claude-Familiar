"""The manager↔window contract, named (Deepen 5/6, #41).

The windows (:class:`~mascot.tkinter_app.MascotWindow`, :class:`~mascot.pet_window.PetWindow`)
used to depend on a loose bag of callback closures. ``PetHost`` names that contract:
what a window needs from whatever hosts it — read/persist the one global pet, celebrate
care on the cards, open the Pet window, and one ``pet_enabled`` flag that expresses
simple (hook-visualiser) mode. :class:`~mascot.manager.MascotManager` is the production
adapter (persisting through :class:`~mascot.pet_service.PetService`, the single writer);
the standalone Pet window and the tests supply their own.
"""
from __future__ import annotations

from typing import Any, Protocol


class PetHost(Protocol):
    """The services a window needs from its host (structural — no inheritance)."""

    @property
    def pet_enabled(self) -> bool: ...   # read-only: a plain attr or property both fit

    def get_pet(self) -> dict[str, Any]: ...
    def save_pet(self, pet: dict[str, Any]) -> dict[str, Any]: ...
    def notify_care(self) -> None: ...
    def open_pet(self) -> None: ...
