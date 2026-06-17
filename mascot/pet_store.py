"""Thin persistence wrapper that owns ``pet.json`` for Tamagotchi mode.

The single source of truth for the one global pet on disk. Mirrors the hook
emitter's I/O wrapper (``hooks/emit.py``): all the logic lives in the pure core
(:mod:`mascot.pet_logic`); this module only does file I/O, stamps ``last_seen``,
and applies **decay-on-load** so real elapsed time across restarts is honored.

The widget process (:mod:`mascot.manager`) is the *single writer* — the Pet
window (a later phase) reads/writes through it, so there are no cross-process
races on the file.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import config, pet_logic

# One global pet, next to the per-session state dir: ~/.claude/mascot/pet.json
PET_PATH = config.STATE_DIR.parent / "pet.json"


def default_pet(now: float) -> dict[str, Any]:
    """A brand-new pet: full needs, no coins/XP, born and last-seen at `now`."""
    return {
        "name": "",
        "born": now,
        "last_seen": now,
        "hunger": pet_logic.MAX_STAT,
        "happiness": pet_logic.MAX_STAT,
        "energy": pet_logic.MAX_STAT,
        "coins": 0,
        "xp": 0,
        "coins_today": 0,
        "last_award_date": "",
        "last_prompt_date": "",   # for the daily first-prompt streak bonus
        "inventory": {},   # item_id -> count owned (food + toys)
        "cooldowns": {},   # item_id -> last-played timestamp (toys)
    }


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_atomic(path: Path, pet: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(pet, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic on the same filesystem


def load(path: Path, now: float, working: bool = False) -> dict[str, Any]:
    """Load the pet, applying decay for the time elapsed since `last_seen`.

    A missing or corrupt file yields a fresh :func:`default_pet`. An existing file
    is merged over defaults (so older files gain new fields cleanly), then decayed
    by ``now - last_seen``. The offline gap is treated as idle by default
    (``working=False``) — the widget wasn't running to track work — so energy
    recovers while away. The returned pet's ``last_seen`` is restamped to `now`.
    """
    raw = _read(path)
    if raw is None:
        return default_pet(now)
    pet = {**default_pet(now), **raw}   # raw overrides; missing keys filled
    elapsed = max(0.0, now - float(pet.get("last_seen", now)))
    pet = pet_logic.decay(pet, elapsed, working)
    pet["last_seen"] = now
    return pet


def save(path: Path, pet: dict[str, Any], now: float) -> dict[str, Any]:
    """Atomically write the pet, stamping `last_seen` to `now`. Returns what was
    written so the caller can keep its in-memory copy's stamp in sync."""
    out = dict(pet)
    out["last_seen"] = now
    _write_atomic(path, out)
    return out
