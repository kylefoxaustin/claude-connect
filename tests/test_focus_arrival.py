"""The focus guard must not refuse when it has already succeeded.

Kyle, 2026-08-05 — found live. ``_focus_session_input``'s tilix path samples the active window,
fires the async ``activate-terminal``, then polls for the active window to CHANGE. It treats
change as a proxy for arrival, and the two differ in exactly one case: **we were already on the
target**. Then nothing moves, the poll times out, and injection is refused precisely when focus
was already correct. Measured on a freshly-relaunched qualcomm whose new window had grabbed
focus — ``/rc`` could never be injected into it.

The counterpart risk is why the fix must be a POSITIVE title match: the moved-check was added to
close a real mis-delivery (a push verdict typed into the wrong session's terminal), so "can't
confirm" must never be read as "we're on target".
"""

from __future__ import annotations

import pytest

from conductor import x11 as w


@pytest.fixture
def no_human(monkeypatch):
    """The human-active guard defers injection outright; it is not what's under test here."""
    monkeypatch.setattr(w, "human_recently_active", lambda *a, **k: False)


@pytest.fixture
def tilix_session(monkeypatch):
    """A target session that lives in a tilix tile, with a working activate."""
    monkeypatch.setattr(w, "tilix_id_for_pid", lambda pid: "a813d796-6eb2-41e7-8a67-deb5c3b103ca")
    monkeypatch.setattr(w, "tilix_activate_terminal", lambda uuid: True)
    monkeypatch.setattr(w, "_TILE_SETTLE_S", 0)
    monkeypatch.setattr(w, "_FOCUS_POLL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(w, "_FOCUS_POLL_STEP_S", 0.01)


def test_accepts_when_already_focused_on_the_target(monkeypatch, no_human, tilix_session):
    """THE REGRESSION. Focus never moves because it is already right. The old code refused."""
    monkeypatch.setattr(w, "_active_window_id", lambda: 81825405)          # never changes
    monkeypatch.setattr(w, "_active_window_name", lambda: "✳ Project Qualcomm")

    assert w._focus_session_input(
        pid=66038, terminal_pid=43099, title="qualcomm", window_title="Project Qualcomm",
    ) is True


def test_still_accepts_when_focus_actually_moves(monkeypatch, no_human, tilix_session):
    """The ordinary path must be untouched by the fix."""
    ids = iter([111, 222, 222, 222])
    monkeypatch.setattr(w, "_active_window_id", lambda: next(ids, 222))
    monkeypatch.setattr(w, "_active_window_name", lambda: "✳ Project Qualcomm")

    assert w._focus_session_input(
        pid=66038, terminal_pid=43099, title="qualcomm", window_title="Project Qualcomm",
    ) is True


def test_refuses_when_focus_is_stuck_on_a_DIFFERENT_session(monkeypatch, no_human, tilix_session):
    """The guard's real job, and it must survive the fix: focus didn't move AND the window we
    are sitting on belongs to someone else -> do not type. This is the mis-delivery case."""
    monkeypatch.setattr(w, "_active_window_id", lambda: 999)              # never changes
    monkeypatch.setattr(w, "_active_window_name", lambda: "⠂ Project claude connect")

    assert w._focus_session_input(
        pid=66038, terminal_pid=43099, title="qualcomm", window_title="Project Qualcomm",
    ) is False


def test_refuses_when_focus_is_stuck_and_the_window_is_UNIDENTIFIABLE(
    monkeypatch, no_human, tilix_session
):
    """FAIL CLOSED. No active-window title means we cannot confirm we are on the target — and an
    unconfirmed guess types a keystroke into someone else's terminal, which is unrecoverable.
    This is exactly why the fix is a positive match and not `not _active_is_not_target(...)`:
    that helper returns False ("can't confirm a mismatch") here, which would have let it type."""
    monkeypatch.setattr(w, "_active_window_id", lambda: 999)
    monkeypatch.setattr(w, "_active_window_name", lambda: "")

    assert w._active_is_not_target("qualcomm", "Project Qualcomm") is False   # can't confirm...
    assert w._focus_session_input(                                            # ...still refuses
        pid=66038, terminal_pid=43099, title="qualcomm", window_title="Project Qualcomm",
    ) is False


def test_target_with_no_window_title_cannot_shortcut(monkeypatch, no_human, tilix_session):
    """A session with no known X11 title has nothing to match positively, so the already-there
    shortcut must not fire — it would degrade to 'assume we're on target', which is the hole."""
    monkeypatch.setattr(w, "_active_window_id", lambda: 999)
    monkeypatch.setattr(w, "_active_window_name", lambda: "⠂ Project claude connect")

    assert w._active_is_target(None) is False
    assert w._focus_session_input(
        pid=66038, terminal_pid=43099, title="qualcomm", window_title=None,
    ) is False


@pytest.mark.parametrize("active,target,expected", [
    ("✳ Project Qualcomm", "Project Qualcomm", True),
    ("project qualcomm — vim", "Project Qualcomm", True),      # case-insensitive substring
    ("⠂ Project claude connect", "Project Qualcomm", False),
    ("", "Project Qualcomm", False),                            # no evidence -> not confirmed
])
def test_active_is_target_requires_positive_evidence(monkeypatch, active, target, expected):
    monkeypatch.setattr(w, "_active_window_name", lambda: active)
    assert w._active_is_target(target) is expected
