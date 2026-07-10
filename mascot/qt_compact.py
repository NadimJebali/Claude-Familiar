"""The Compact theme window — one panel listing every session as a row (#75).

The Rust widget's shape: instead of one mascot card per session, a single
frameless always-on-top panel holds a slim row per live session (effort dot ·
state text · model · sub-agent count · context ring), the account-global usage
bars once at the bottom, and no mascot, no jostle, no popup bubbles (notify
text rides inline in its row).

This module lands with the presentation seam (#74) as a skeleton — the app
routes sessions/usage/context here when ``theme == "compact"`` — and the rows,
effort backdrops, inline notify and bottom bars arrive in #75. The pet layer is
orthogonal: PetService keeps earning and the tray "Pet…" window works; only the
card-side pet expressions have no home here.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


class CompactWindow(QWidget):
    """The single compact panel. Skeleton (#74): stores what the app pushes —
    ``sessions`` / ``usage`` / ``context`` — so the seam is real and testable;
    the rendering lands in #75."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.sessions: dict[str, dict[str, Any]] = {}
        self._usage: dict[str, Any] | None = None
        self._context: dict[str, float] = {}

    def set_sessions(self, live: dict[str, dict[str, Any]]) -> None:
        """Adopt this poll's live snapshots (the roster-equivalent for rows)."""
        self.sessions = dict(live)

    def set_usage(self, snapshot: dict[str, Any] | None) -> None:
        """Adopt the account-global usage snapshot for the bottom bars."""
        self._usage = snapshot

    def set_context(self, results: dict[str, float]) -> None:
        """Adopt the per-session context percentages for the row rings."""
        self._context = dict(results)
