"""Runtime bootstrap behind the one-step installer (``install.py``).

The installer used to run ``pip install -r requirements.txt`` with
``check=False`` and plow on. On a PEP 668 externally-managed distro (every
modern Debian/Ubuntu/Fedora) that pip step fails, so the launchers it then
wrote pointed at an interpreter with no PySide6 — and every launch died on a
``ModuleNotFoundError`` hidden behind the ``.desktop`` entry's
``Terminal=false``: "the app never opens its window".

This module makes the installer prove its interpreter before anything is
written: install/refresh the requirements, probe that PySide6 actually
imports, and — when the given Python can't take the install (PEP 668) —
provision the project ``.venv`` pip itself recommends. Debian/Ubuntu boxes
without ``python3-venv`` can't even create a venv with pip in it (no
ensurepip), so a ``--without-pip`` venv driven by the *outer* pip's
``--python`` flag is the fallback. If no provable interpreter comes out of
that, the installer stops with the exact commands to run instead of
installing a broken app.

Stdlib-only on purpose: it runs before the requirements exist.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from . import osplatform

Runner = Callable[[Sequence[str]], int]

# Probe via find_spec so a missing PySide6 answers with an exit code, not a
# traceback splashed mid-install.
_IMPORT_CHECK = ("import importlib.util, sys; "
                 "sys.exit(0 if importlib.util.find_spec('PySide6') else 1)")

VENV_DIR_NAME = ".venv"


def _run(argv: Sequence[str]) -> int:
    """Run a command with inherited stdio (pip/venv progress stays visible);
    an unlaunchable command reads as failure, never as a crash."""
    try:
        return subprocess.run(list(argv), check=False).returncode
    except OSError:
        return 127


def venv_python(root: Path) -> Path:
    """The project venv's interpreter path (whether or not it exists yet)."""
    venv = root / VENV_DIR_NAME
    if osplatform.IS_WINDOWS:
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python3"


def runtime_ok(python: str | Path, run: Runner = _run) -> bool:
    """True if ``python`` can import the widget's view layer (PySide6)."""
    return run([str(python), "-c", _IMPORT_CHECK]) == 0


def same_python(a: str | os.PathLike[str], b: str | os.PathLike[str]) -> bool:
    """Same interpreter *path*. No symlink resolution: a venv python is often
    a symlink to the base interpreter, and resolving would erase exactly the
    venv-vs-system distinction the installer re-execs over."""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def ensure_runtime(python: str, root: Path, run: Runner = _run) -> str | None:
    """An interpreter path that provably runs the app, or ``None``.

    In order: a previously provisioned project venv (refreshed and reused);
    the given ``python`` once the requirements install into it; a fresh
    project venv. Every candidate must pass :func:`runtime_ok` — the caller
    never receives an interpreter the app is not known to import under.
    """
    reqs = root / "requirements.txt"
    vpy = venv_python(root)
    if vpy.exists() and runtime_ok(vpy, run):
        _venv_pip_install(python, str(vpy), reqs, run)             # refresh, best-effort
        return str(vpy)
    run([str(python), "-m", "pip", "install", "-r", str(reqs)])
    if runtime_ok(python, run):
        return str(python)
    print(f"[install] {python} cannot run the app (no PySide6); "
          f"provisioning {root / VENV_DIR_NAME} ...")
    if not _provision_venv(python, root, reqs, run):
        return None
    return str(vpy) if runtime_ok(vpy, run) else None


def _provision_venv(python: str, root: Path, reqs: Path, run: Runner) -> bool:
    """Create the project venv and install the requirements into it.

    Plain ``python -m venv`` first; when that fails (Debian/Ubuntu without
    ``python3-venv`` has no ensurepip) retry ``--without-pip``."""
    venv = root / VENV_DIR_NAME
    if run([python, "-m", "venv", str(venv)]) != 0:
        if run([python, "-m", "venv", "--without-pip", str(venv)]) != 0:
            return False
    return _venv_pip_install(python, str(venv_python(root)), reqs, run)


def _venv_pip_install(python: str, vpy: str, reqs: Path, run: Runner) -> bool:
    """Install the requirements into the venv: its own pip when it has one,
    else the outer interpreter's pip aimed at it (``--python``) — a
    ``--without-pip`` venv (the no-ensurepip fallback) carries no inner pip."""
    if run([vpy, "-m", "pip", "--version"]) == 0:
        return run([vpy, "-m", "pip", "install", "-r", str(reqs)]) == 0
    return run([python, "-m", "pip", "--python", vpy, "install", "-r", str(reqs)]) == 0


def dependency_help() -> str:
    """What to run by hand when no provable interpreter could be provisioned."""
    if osplatform.IS_WINDOWS:
        return (
            "\nClaude Familiar needs PySide6, and it could not be installed for this\n"
            "Python. Install the requirements yourself, then re-run the installer:\n\n"
            "    python -m pip install -r requirements.txt\n"
            "    python install.py\n"
        )
    return (
        "\nClaude Familiar needs PySide6, and it could not be installed for this\n"
        "Python (on Debian/Ubuntu the system Python is externally managed).\n"
        "Create the project venv yourself, then re-run the installer with it:\n\n"
        "    python3 -m venv .venv\n"
        "    .venv/bin/pip install -r requirements.txt\n"
        "    .venv/bin/python3 install.py\n\n"
        "If `python3 -m venv` reports that ensurepip is not available, install\n"
        "it first:    sudo apt install python3-venv\n"
    )
