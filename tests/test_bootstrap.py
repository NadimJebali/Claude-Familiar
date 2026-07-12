"""Tests for the installer's runtime bootstrap (the silent-launcher regression).

The bug: on a PEP 668 (externally-managed) distro the installer's pip step
fails, ``install.py`` plowed on with ``check=False``, and the ``.desktop``
launchers ended up pointing at an interpreter with no PySide6 — every launch
died on a silent ``ModuleNotFoundError`` behind ``Terminal=false``: "the app
never opens its window". These tests pin the fix: the installer proceeds only
with an interpreter that provably imports PySide6, provisioning a project
``.venv`` when the given one can't (including the Debian/Ubuntu no-ensurepip
fallback), and refusing cleanly — no launchers, no hooks — otherwise.

All subprocess I/O sits behind the injectable runner, so the flow is tested
pure: a scripted fake runner returns exit codes per command and records every
argv for assertions.
"""
from __future__ import annotations

import subprocess
import sys

from mascot import bootstrap

PY = "/opt/fake/python3"


class FakeRunner:
    """Scripted ``run(argv) -> exit code``: first matching rule wins, unmatched
    commands succeed. Records every argv (stringified) for assertions."""

    def __init__(self, *rules):
        self._rules = list(rules)          # (matcher(argv) -> bool, exit code)
        self.calls: list[list[str]] = []

    def __call__(self, argv) -> int:
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        for match, code in self._rules:
            if match(argv):
                return code
        return 0


def _is_import_check(argv):
    return argv[1] == "-c" and "PySide6" in argv[2]


def _is_pip_install(argv):
    return argv[1:4] == ["-m", "pip", "install"]


def _is_venv_create(argv):
    return argv[1:3] == ["-m", "venv"]


# --- runtime_ok: the "can this interpreter run the app?" probe --------------
def test_runtime_ok_true_when_import_check_passes():
    run = FakeRunner()
    assert bootstrap.runtime_ok(PY, run=run) is True
    assert len(run.calls) == 1 and run.calls[0][0] == PY
    assert _is_import_check(run.calls[0])


def test_runtime_ok_false_when_import_check_fails():
    run = FakeRunner((_is_import_check, 1))
    assert bootstrap.runtime_ok(PY, run=run) is False


# --- ensure_runtime: the decision flow ---------------------------------------
def test_keeps_given_python_when_runtime_imports(tmp_path):
    run = FakeRunner()
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) == PY
    # It still installed/refreshed the requirements first (the original step)...
    assert any(a[0] == PY and _is_pip_install(a) for a in run.calls)
    # ...and never touched venv machinery.
    assert not any(_is_venv_create(a) for a in run.calls)


def test_prefers_existing_healthy_project_venv(tmp_path):
    vpy = bootstrap.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.touch()
    run = FakeRunner()
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) == str(vpy)
    # Refreshed the requirements inside the venv, never ran the system pip.
    assert any(a[0] == str(vpy) and _is_pip_install(a) for a in run.calls)
    assert not any(a[0] == PY and _is_pip_install(a) for a in run.calls)


def test_refreshes_a_pipless_venv_through_the_outer_pip(tmp_path):
    """A ``--without-pip`` venv (the no-ensurepip fallback) has no inner pip:
    the reuse-time refresh must go through the outer ``pip --python`` too,
    or a new requirement would silently never install."""
    vpy = bootstrap.venv_python(tmp_path)
    vpy.parent.mkdir(parents=True)
    vpy.touch()
    run = FakeRunner(
        ((lambda a: a[0] == str(vpy) and a[1:4] == ["-m", "pip", "--version"]), 1),
    )
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) == str(vpy)
    outer = [a for a in run.calls if a[:3] == [PY, "-m", "pip"] and "--python" in a]
    assert outer and str(vpy) in outer[0] and "install" in outer[0]


def test_builds_venv_when_system_pip_is_blocked(tmp_path):
    """PEP 668 box: system pip fails, PySide6 missing -> provision .venv."""
    vpy = str(bootstrap.venv_python(tmp_path))
    run = FakeRunner(
        ((lambda a: a[0] == PY and _is_pip_install(a)), 1),      # externally managed
        ((lambda a: a[0] == PY and _is_import_check(a)), 1),     # no PySide6 there
    )
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) == vpy
    assert any(a[:3] == [PY, "-m", "venv"] and str(tmp_path / ".venv") in a
               for a in run.calls)
    assert any(a[0] == vpy and _is_pip_install(a) for a in run.calls)


def test_falls_back_to_outer_pip_when_ensurepip_missing(tmp_path):
    """Debian/Ubuntu without python3-venv: plain venv creation fails, the
    ``--without-pip`` + outer ``pip --python`` route provisions it instead."""
    vpy = str(bootstrap.venv_python(tmp_path))
    run = FakeRunner(
        ((lambda a: a[0] == PY and _is_pip_install(a)), 1),
        ((lambda a: a[0] == PY and _is_import_check(a)), 1),
        ((lambda a: _is_venv_create(a) and "--without-pip" not in a), 1),
        ((lambda a: a[0] == vpy and a[1:4] == ["-m", "pip", "--version"]), 1),
    )
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) == vpy
    assert any(_is_venv_create(a) and "--without-pip" in a for a in run.calls)
    outer = [a for a in run.calls if a[:3] == [PY, "-m", "pip"] and "--python" in a]
    assert outer and vpy in outer[0] and "install" in outer[0]


def test_gives_up_cleanly_when_nothing_works(tmp_path):
    run = FakeRunner(
        (_is_pip_install, 1),
        (_is_import_check, 1),
        (_is_venv_create, 1),
    )
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) is None


def test_gives_up_when_venv_python_still_lacks_pyside(tmp_path):
    """A venv materializes but the requirements install fails (offline box):
    never bless an interpreter the import probe hasn't passed."""
    run = FakeRunner(
        (_is_pip_install, 1),
        (_is_import_check, 1),
    )
    assert bootstrap.ensure_runtime(PY, tmp_path, run=run) is None


# --- the guidance + interpreter identity helpers -----------------------------
def test_dependency_help_gives_the_venv_recipe_on_linux(monkeypatch):
    monkeypatch.setattr(bootstrap.osplatform, "IS_WINDOWS", False)
    text = bootstrap.dependency_help()
    assert "python3 -m venv .venv" in text
    assert "install.py" in text
    assert "python3-venv" in text          # the Debian/Ubuntu ensurepip hint


def test_dependency_help_points_windows_at_pip(monkeypatch):
    monkeypatch.setattr(bootstrap.osplatform, "IS_WINDOWS", True)
    text = bootstrap.dependency_help()
    assert "pip install -r requirements.txt" in text
    assert "apt" not in text


def test_same_python_does_not_resolve_symlinks(tmp_path):
    """A venv python is usually a symlink to the base interpreter — resolving
    would erase exactly the distinction the installer re-execs over."""
    real = tmp_path / "python3"
    real.touch()
    link = tmp_path / "venv-python3"
    link.symlink_to(real)
    assert bootstrap.same_python(str(real), str(real)) is True
    assert bootstrap.same_python(str(link), str(real)) is False


# --- install.py wiring: never write launchers for a broken interpreter -------
def _no_subprocess(monkeypatch, install):
    calls: list[list[str]] = []

    def record(argv, **kwargs):
        calls.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(install.subprocess, "run", record)
    return calls


def test_install_stops_before_any_side_effect_when_runtime_missing(monkeypatch):
    import install

    calls = _no_subprocess(monkeypatch, install)
    monkeypatch.setattr(install.bootstrap, "ensure_runtime", lambda *a, **k: None)
    assert install.main() == 1
    assert calls == []                      # no icon, no hooks, no launchers


def test_install_reexecs_under_the_provisioned_venv(monkeypatch):
    import install

    calls = _no_subprocess(monkeypatch, install)
    monkeypatch.setattr(install.bootstrap, "ensure_runtime",
                        lambda *a, **k: "/opt/elsewhere/python3")
    assert install.main() == 0
    assert len(calls) == 1                  # the re-exec, nothing else
    assert calls[0][0] == "/opt/elsewhere/python3"
    assert calls[0][1].endswith("install.py")


def test_install_proceeds_natively_with_a_healthy_interpreter(monkeypatch):
    import install

    calls = _no_subprocess(monkeypatch, install)
    monkeypatch.setattr(install.bootstrap, "ensure_runtime",
                        lambda *a, **k: sys.executable)
    assert install.main() == 0
    # The original steps, in order: icon, hooks, launchers, settings panel.
    assert len(calls) == 4
    assert all(c[0] == sys.executable for c in calls)
