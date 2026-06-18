"""Tests for native OS notifications (#19).

The plyer call is thin I/O (verified live); the logic — edge-triggering across
polls and title/message formatting — is pure and tested here. ``emit`` takes an
injectable ``show`` so the routing is tested without touching plyer or threads.
"""
from mascot import notifier


def _state(notify):
    return {"state": "waiting", "notify": notify}


_PERM = {"message": "Approve edit?", "type": "permission"}
_LIMIT = {"message": "Claude usage limit reached", "type": "usage_limit"}


# --- fresh_notifications (edge detection across polls) ---------------------

def test_a_newly_appearing_notify_fires():
    out = notifier.fresh_notifications({}, {"s1": _state(_PERM)})
    assert out == [("s1", _PERM)]


def test_an_unchanged_notify_does_not_refire_on_the_next_poll():
    prev = {"s1": _state(_PERM)}
    assert notifier.fresh_notifications(prev, {"s1": _state(_PERM)}) == []


def test_a_changed_notify_message_fires_again():
    prev = {"s1": _state(_PERM)}
    changed = {"message": "Approve a different thing?", "type": "permission"}
    assert notifier.fresh_notifications(prev, {"s1": _state(changed)}) == [("s1", changed)]


def test_clearing_then_re_raising_a_notify_fires_again():
    # poll A: prompt up; poll B: answered (notify None); poll C: a new prompt.
    cleared = notifier.fresh_notifications({"s1": _state(_PERM)}, {"s1": _state(None)})
    assert cleared == []
    reraised = notifier.fresh_notifications({"s1": _state(None)}, {"s1": _state(_PERM)})
    assert reraised == [("s1", _PERM)]


def test_a_session_with_no_notify_never_fires():
    assert notifier.fresh_notifications({}, {"s1": _state(None)}) == []


def test_each_session_is_tracked_independently():
    prev = {"s1": _state(_PERM)}                      # s1 already toasted
    nxt = {"s1": _state(_PERM), "s2": _state(_LIMIT)}  # s2 is new
    assert notifier.fresh_notifications(prev, nxt) == [("s2", _LIMIT)]


# --- toast_for (title/message formatting) ---------------------------------

def test_toast_for_none_is_none():
    assert notifier.toast_for(None) is None


def test_toast_for_notify_without_a_message_is_none():
    assert notifier.toast_for({"type": "permission"}) is None
    assert notifier.toast_for({"message": "   ", "type": "permission"}) is None


def test_toast_for_permission_titles_needs_your_permission():
    title, message = notifier.toast_for(_PERM)
    assert "permission" in title.lower()
    assert message == "Approve edit?"


def test_toast_for_usage_limit_titles_usage_limit():
    title, _ = notifier.toast_for(_LIMIT)
    assert "usage limit" in title.lower()


def test_toast_for_other_death_types_also_read_as_limit():
    title, _ = notifier.toast_for({"message": "Billing problem", "type": "billing_error"})
    assert "usage limit" in title.lower()


def test_toast_for_untyped_attention_titles_needs_you():
    title, message = notifier.toast_for({"message": "Claude needs you", "type": ""})
    assert title == f"{notifier.APP_NAME} — needs you"
    assert message == "Claude needs you"


# --- emit (routing, with injected show) -----------------------------------

def test_emit_shows_a_formatted_toast():
    shown = []
    notifier.emit(_PERM, show=lambda title, msg: shown.append((title, msg)))
    assert len(shown) == 1
    assert shown[0][1] == "Approve edit?"


def test_emit_does_nothing_for_an_empty_or_missing_notify():
    shown = []
    record = lambda title, msg: shown.append((title, msg))  # noqa: E731
    notifier.emit(None, show=record)
    notifier.emit({"type": "permission"}, show=record)   # no message
    assert shown == []
