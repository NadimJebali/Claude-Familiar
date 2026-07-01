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


# --- planning (plan mode) -----------------------------------------------------
def test_display_face_is_planning_while_busy_in_plan_mode():
    assert effective_state.display_face("thinking", permission_mode="plan") == "planning"
    # In plan mode Claude only reads/searches — planning outranks the tool face.
    assert effective_state.display_face(
        "working", tool="Read", permission_mode="plan") == "planning"


def test_display_face_ignores_plan_mode_when_not_busy():
    for state in ("idle", "waiting", "sleeping", "dead", "happy"):
        assert effective_state.display_face(state, permission_mode="plan") == state


def test_display_face_ignores_other_permission_modes():
    assert effective_state.display_face(
        "thinking", permission_mode="acceptEdits") == "thinking"
    assert effective_state.display_face(
        "working", tool="Edit", permission_mode="default") == "working_edit"


# --- stumble (a turn died on a transient API error) ---------------------------
def test_display_face_shows_stumble_over_the_idle_family():
    for idle_face in ("idle", "idle_happy", "idle_hungry", "idle_sad", "idle_tired"):
        assert effective_state.display_face(
            idle_face, stumbled_recent=True) == "stumble"


def test_display_face_stumble_never_covers_busy_or_ladder_states():
    # Dozing/blink outrank it on purpose; busy states can't stumble.
    for state in ("sleeping", "idle_blink", "working", "thinking", "waiting", "dead"):
        assert effective_state.display_face(state, stumbled_recent=True) == state


def test_should_celebrate_only_on_a_clean_finish():
    assert effective_state.should_celebrate("working", "idle", False) is True
    assert effective_state.should_celebrate("thinking", "idle", False) is True
    assert effective_state.should_celebrate("working", "idle", True) is False   # stumble
    assert effective_state.should_celebrate("waiting", "idle", False) is False
    assert effective_state.should_celebrate("working", "dead", False) is False


# --- the pixel gravestone (the "dead" look) -----------------------------------
def test_grave_grid_is_valid_and_fully_paletted():
    assert len(sprite_pixel._GRAVE) == sprite_pixel.GRID_H
    for row in sprite_pixel._GRAVE:
        assert len(row) == sprite_pixel.GRID_W
        assert set(row) <= {*sprite_pixel.GRAVE_COLORS, "."}


# --- the new sprite faces render at every stage ------------------------------
@pytest.mark.parametrize("face", ["working_read", "working_edit", "working_run",
                                  "working_web", "planning", "stumble"])
@pytest.mark.parametrize("stage", ["egg", "baby", "teen", "adult"])
def test_new_working_faces_compose_at_every_stage(face, stage):
    assert face in sprite_pixel._FACES
    grid = sprite_pixel.grid_for(stage, face)
    assert len(grid) == sprite_pixel.GRID_H
    assert all(len(row) == sprite_pixel.GRID_W for row in grid)
