"""Pure computation of the mascot's *effective* (displayed) state.

The raw state comes from the hook-written state file; on top of it the widget
layers several time-based overlays (dizzy, happy, sleeping, blink) and a stall
watchdog that falls a frozen busy state back to idle. Kept Tk-free and clock-free
(``now`` and the timers are passed in) so every branch is unit-testable;
``tkinter_app`` supplies the live values.
"""
from __future__ import annotations

# Pet mood (from pet_logic.mood) -> idle-face variant. Applied ONLY while the raw
# state is idle (and not dozing/blinking), so Claude-activity states always win. A
# face the sprite doesn't define falls back to plain "idle" at render time.
_MOOD_IDLE_FACE = {
    "happy": "idle_happy",     # sparkly — well cared for
    "hungry": "idle_hungry",   # droopy
    "sad": "idle_sad",
    "tired": "idle_tired",     # sleepy-eyed (low energy)
    "content": "idle",
}


def compute(
    raw: str,
    now: float,
    *,
    ts: float | None,
    dizzy_until: float,
    celebrate_until: float,
    waiting_since: float | None,
    idle_since: float | None,
    blink_until: float,
    sleep_after_idle_s: float,
    shake_after_s: float,
    thinking_stall_s: float,
    working_stall_s: float,
    mood: str = "content",
) -> str:
    """Return the effective state. Overlays apply in priority order:
      - `dizzy`         while a recent shake is still in effect (top priority),
      - `happy`         briefly after Claude finishes a turn, or on a pet,
      - `waiting_angry` once an unanswered prompt has waited long enough to shake,
      - stall watchdog  busy + stale heartbeat -> idle (turn died, no closing hook),
      - `sleeping`      after the raw state has been idle for sleep_after_idle_s,
      - `idle_blink`    a brief blink while idle (before dozing off).
    """
    if now < dizzy_until:
        return "dizzy"
    if now < celebrate_until:
        return "happy"
    # Glare (angry face) once an unanswered prompt has waited long enough that the
    # card starts shaking — same threshold as the attention shake.
    if (raw == "waiting" and waiting_since is not None
            and now - waiting_since >= shake_after_s):
        return "waiting_angry"
    # Don't sit frozen on a busy state if the turn died with no closing hook (e.g.
    # a usage/session-limit hit): after a long stale stretch with no new event,
    # fall the display back to idle. `working` gets a longer grace than `thinking`
    # so a single long-running tool isn't cut off early. Return idle *directly* —
    # not via `raw = "idle"` fall-through — so a stalled busy state can never reach
    # the idle->sleeping/blink overlay below and "doze off" mid-build.
    if ts is not None:
        stale = now - ts
        if (raw == "thinking" and stale > thinking_stall_s) or (
                raw == "working" and stale > working_stall_s):
            return "idle"
    if raw == "idle":
        # The idle rhythm — dozing and the occasional blink — outranks the mood tint.
        if idle_since is not None and now - idle_since >= sleep_after_idle_s:
            return "sleeping"
        if now < blink_until:
            return "idle_blink"
        # Otherwise the idle face reflects the pet's mood (default: plain idle).
        return _MOOD_IDLE_FACE.get(mood, "idle")
    return raw


# --- display face (the face DRAWN for an effective state) --------------------
# The effective state is semantic (it drives captions, emotes, animation); the
# display face is purely visual. While working, the face reflects what KIND of
# tool is running — the caption already names the tool, now the eyes match.
_TOOL_FACES = {
    "Read": "working_read", "Glob": "working_read", "Grep": "working_read",
    "NotebookRead": "working_read",
    "Edit": "working_edit", "Write": "working_edit", "MultiEdit": "working_edit",
    "NotebookEdit": "working_edit",
    "Bash": "working_run", "PowerShell": "working_run", "BashOutput": "working_run",
    "WebSearch": "working_web", "WebFetch": "working_web",
}


def working_face_for(tool: str | None) -> str:
    """The working-face variant for the active tool (exact hook `tool_name`).

    Unknown tools — and no tool at all — keep the classic focused-squint
    ``working`` face, so a brand-new tool name can never break the render.
    """
    return _TOOL_FACES.get(tool or "", "working")


def display_face(effective: str, *, tool: str | None = None,
                 permission_mode: str = "") -> str:
    """The face to DRAW for an effective state.

    Plan mode outranks the tool variants — while ``permission_mode == "plan"``
    a busy mascot wears the pondering ``planning`` face (in plan mode Claude only
    reads and searches, so "planning" says more than the tool kind). Otherwise
    the working face varies by tool; every other effective state is its own
    face. (The render falls back to the idle face for any unknown key, so a
    missing sprite can never crash a card.)
    """
    if permission_mode == "plan" and effective in ("thinking", "working"):
        return "planning"
    if effective == "working":
        return working_face_for(tool)
    return effective
