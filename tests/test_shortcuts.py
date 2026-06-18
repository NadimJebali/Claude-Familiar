"""Tests for app-launcher shortcut creation (#20).

The ``.lnk`` path is Windows + pywin32 COM I/O, so these are gated: they skip
off-Windows (``pytestmark``) and skip when pywin32 is missing (``importorskip``).
They create a real shortcut in a temp dir and read it back through the same
WScript.Shell COM object to confirm the fields round-trip.
"""
import sys
from pathlib import Path

import pytest

from mascot import shortcuts

pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="Windows .lnk shortcuts only")


def test_create_shortcut_writes_a_lnk_with_round_tripping_fields(tmp_path):
    pytest.importorskip("win32com.client")
    lnk = tmp_path / "Claude Familiar Test.lnk"
    target = Path(sys.executable)  # a real exe, so TargetPath round-trips exactly

    ok = shortcuts.create_shortcut(lnk, target=target,
                                   arguments="-m mascot.control_panel", description="Test")
    assert ok and lnk.exists()

    from win32com.client import Dispatch
    link = Dispatch("WScript.Shell").CreateShortcut(str(lnk))
    assert link.TargetPath.lower() == str(target).lower()
    assert "control_panel" in link.Arguments
    assert link.WorkingDirectory == str(shortcuts.PROJECT_ROOT)


def test_remove_shortcut_deletes_the_lnk(tmp_path):
    pytest.importorskip("win32com.client")
    lnk = tmp_path / "ToRemove.lnk"
    shortcuts.create_shortcut(lnk, target=Path(sys.executable))
    assert lnk.exists()

    assert shortcuts.remove_shortcut(lnk) is True
    assert not lnk.exists()


def test_remove_shortcut_is_ok_when_absent(tmp_path):
    # Removing a shortcut that isn't there is a success (idempotent uninstall).
    assert shortcuts.remove_shortcut(tmp_path / "nope.lnk") is True
