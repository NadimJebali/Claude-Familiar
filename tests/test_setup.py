"""Tests for the Tk-free setup seam behind the control panel (#29).

Everything here is exercised without a Tk root and with all real side effects
stubbed: the hook installer subprocess, the launcher, the full uninstall, and the
pet file are redirected to fakes / temp paths so no test touches the real
``~/.claude`` settings, shortcuts, or pet.
"""
from __future__ import annotations

import json
import subprocess

from mascot import pet_store, setup


# --- hooks_installed: the single app-side 'are the hooks installed?' notion -
def _settings_with_command(tmp_path, command: str):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": command}]}]}}),
        encoding="utf-8")
    return path


def test_hooks_installed_true_when_emit_referenced(tmp_path):
    settings = _settings_with_command(tmp_path, f'"py" "{setup.EMIT_PY}" SessionStart')
    assert setup.hooks_installed(settings) is True


def test_hooks_installed_false_when_other_hook_present(tmp_path):
    settings = _settings_with_command(tmp_path, "echo unrelated")
    assert setup.hooks_installed(settings) is False


def test_hooks_installed_false_when_missing_or_corrupt(tmp_path):
    assert setup.hooks_installed(tmp_path / "nope.json") is False
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json", encoding="utf-8")
    assert setup.hooks_installed(bad) is False


# --- install_hooks: shells out, maps the result to (ok, message) -----------
def test_install_hooks_reports_success(monkeypatch):
    monkeypatch.setattr(setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "", ""))
    ok, msg = setup.install_hooks()
    assert ok is True and "installed" in msg.lower()


def test_install_hooks_reports_failure(monkeypatch):
    monkeypatch.setattr(setup.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "boom"))
    ok, msg = setup.install_hooks()
    assert ok is False and "failed" in msg.lower()


# --- app shortcuts: routed through the launcher seam -----------------------
def test_toggle_shortcuts_installs_then_removes(monkeypatch):
    state = {"installed": False}

    def _install(*, desktop=True):
        state["installed"] = True
        return ["a", "b"]

    monkeypatch.setattr(setup.launcher, "is_installed", lambda: state["installed"])
    monkeypatch.setattr(setup.launcher, "install", _install)
    monkeypatch.setattr(setup.launcher, "uninstall",
                        lambda: state.__setitem__("installed", False))

    now, msg = setup.toggle_shortcuts()
    assert now is True and state["installed"] is True and "Added 2" in msg

    now, msg = setup.toggle_shortcuts()
    assert now is False and state["installed"] is False and "Removed" in msg


# --- run-at-login: delegates and returns the resulting state ---------------
def test_set_autostart_delegates_and_returns_state(monkeypatch):
    state = {"on": False}
    monkeypatch.setattr(setup.launcher, "set_autostart",
                        lambda enabled: state.__setitem__("on", enabled))
    monkeypatch.setattr(setup.launcher, "autostart_enabled", lambda: state["on"])

    assert setup.set_autostart(True) is True and state["on"] is True
    assert setup.set_autostart(False) is False and state["on"] is False


# --- reset_pet: writes a fresh egg to pet.json -----------------------------
def test_reset_pet_writes_fresh_egg(monkeypatch, tmp_path):
    pet_path = tmp_path / "pet.json"
    monkeypatch.setattr(pet_store, "PET_PATH", pet_path)

    ok, msg = setup.reset_pet()

    assert ok is True and "reset" in msg.lower()
    assert pet_path.exists()
    data = json.loads(pet_path.read_text(encoding="utf-8"))
    assert data["coins"] == 0 and data["xp"] == 0


# --- uninstall: delegates to the full-uninstall routine --------------------
def test_uninstall_delegates_to_full_uninstall(monkeypatch):
    from mascot import uninstall as uninstall_mod
    monkeypatch.setattr(uninstall_mod, "full_uninstall", lambda: ["removed everything"])
    assert setup.uninstall() == ["removed everything"]
