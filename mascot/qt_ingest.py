"""Event-driven session ingestion for the Qt widget (issue #56).

Replaces the Tk manager's 500ms UI-thread poll. A ``QFileSystemWatcher`` on the
state directory reacts to hook writes, and a slow backstop ``QTimer`` catches what
a watcher can't see — a session's owning process dying (no file event fires) and
any missed change. Each trigger runs the read + JSON parse + schema validation
**off the UI thread** on the global ``QThreadPool``; the result arrives back on the
owner thread via ``sessions_changed``, so the UI thread only ever receives ready
snapshots.

``read_live`` is the pure read the worker runs — plain enough to unit-test without
Qt. It reuses ``state_store.load_states`` (liveness/staleness) and drops any file
that fails the ``schema`` contract, so a malformed write can never reach a card.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import (
    QFileSystemWatcher,
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Signal,
)

from . import config, schema, state_store

State = dict[str, object]

# Backstop cadence: slow enough not to be a poll, quick enough that a dead-owner
# card (which fires no file event) is pruned within a couple of seconds.
BACKSTOP_MS = 2000


def read_live(state_dir: Path, now: float) -> dict[str, State]:
    """The live, schema-valid session snapshots — the work the pool thread runs.

    ``load_states`` already filters to sessions whose card belongs on screen
    (owner alive / not stale); this additionally drops any that fail the state-file
    contract, so ingestion never forwards a malformed payload.
    """
    live = state_store.load_states(state_dir, now)
    return {sid: st for sid, st in live.items() if schema.is_valid_session_state(st)}


class _ReadSignals(QObject):
    done = Signal(dict)


class _ReadTask(QRunnable):
    """Runs one read off the UI thread and emits the snapshots when done."""

    def __init__(self, state_dir: Path, signals: _ReadSignals) -> None:
        super().__init__()
        self._dir = state_dir
        self._signals = signals

    def run(self) -> None:  # executes on a pool thread
        try:
            snaps = read_live(self._dir, time.time())
        except Exception:  # noqa: BLE001 — a bad read must never take down the pool
            return
        self._signals.done.emit(snaps)


class SessionIngest(QObject):
    """Watches the state dir and emits ``sessions_changed`` with live snapshots."""

    sessions_changed = Signal(dict)

    def __init__(self, state_dir: Path | str | None = None, *,
                 backstop_ms: int = BACKSTOP_MS, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._dir = Path(state_dir) if state_dir is not None else config.STATE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pool = QThreadPool.globalInstance()

        # The worker emits on a pool thread; a queued signal->signal hop re-emits
        # sessions_changed on this object's (UI) thread, so slots run there.
        self._signals = _ReadSignals()
        self._signals.done.connect(self.sessions_changed)

        self._watcher = QFileSystemWatcher([str(self._dir)], self)
        self._watcher.directoryChanged.connect(self._on_dir_changed)

        self._timer = QTimer(self)
        self._timer.setInterval(backstop_ms)
        self._timer.timeout.connect(self.refresh)

    def start(self) -> None:
        """Paint once immediately, then let events + the backstop drive updates."""
        self.refresh()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def refresh(self) -> None:
        """Kick an off-thread read; the result arrives on ``sessions_changed``."""
        self._pool.start(_ReadTask(self._dir, self._signals))

    def read_now(self) -> dict[str, State]:
        """Read synchronously on the caller's thread, emit, and return the snapshots.

        The deterministic path for tests and any caller that wants the result
        inline; production uses the off-thread ``refresh``.
        """
        snaps = read_live(self._dir, time.time())
        self.sessions_changed.emit(snaps)
        return snaps

    def _on_dir_changed(self, _path: str) -> None:
        self.refresh()
