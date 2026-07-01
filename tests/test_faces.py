"""Tests for the display-face seam: the face DRAWN for an effective state.

The effective state stays semantic (captions, emotes, animation); the display
face is purely visual — while working it reflects the kind of tool running.
Pure functions in ``mascot.effective_state`` + sprite composition checks.
"""
from __future__ import annotations

import pytest

from mascot import effective_state, sprite_pixel


# --- working_face_for: tool name -> working face variant --------------------
@pytest.mark.parametrize(("tool", "face"), [
    ("Read", "working_read"),
    ("Glob", "working_read"),
    ("Grep", "working_read"),
    ("Edit", "working_edit"),
    ("Write", "working_edit"),
    ("MultiEdit", "working_edit"),
    ("Bash", "working_run"),
    ("PowerShell", "working_run"),
    ("WebSearch", "working_web"),
    ("WebFetch", "working_web"),
])
def test_working_face_for_maps_known_tools(tool, face):
    assert effective_state.working_face_for(tool) == face


def test_working_face_for_falls_back_for_unknown_and_none():
    # A brand-new tool name (or no tool at all) keeps the classic working face.
    assert effective_state.working_face_for("SomeFutureTool") == "working"
    assert effective_state.working_face_for(None) == "working"
    assert effective_state.working_face_for("") == "working"


# --- display_face ------------------------------------------------------------
def test_display_face_varies_working_by_tool():
    assert effective_state.display_face("working", tool="Read") == "working_read"
    assert effective_state.display_face("working", tool="Bash") == "working_run"
    assert effective_state.display_face("working", tool=None) == "working"


def test_display_face_leaves_other_states_alone():
    for state in ("idle", "thinking", "waiting", "sleeping", "dizzy", "happy",
                  "dead", "idle_hungry"):
        assert effective_state.display_face(state, tool="Read") == state


# --- the new sprite faces render at every stage ------------------------------
@pytest.mark.parametrize("face", ["working_read", "working_edit", "working_run",
                                  "working_web"])
@pytest.mark.parametrize("stage", ["egg", "baby", "teen", "adult"])
def test_new_working_faces_compose_at_every_stage(face, stage):
    assert face in sprite_pixel._FACES
    grid = sprite_pixel.grid_for(stage, face)
    assert len(grid) == sprite_pixel.GRID_H
    assert all(len(row) == sprite_pixel.GRID_W for row in grid)
