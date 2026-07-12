"""Autonomy windows — "for the next N hours, these Claudes may talk to each other".

The whole point is a *scoped, time-boxed* relaxation of ONE guard: a WAITING session
(parked at its prompt) is normally never woken, because Kyle may be typing at it. Since
WAITING is the resting state of every quiet session, that guard is what forces him to
hand-click "check msgs" 30+ times. A window is his permission slip.

These tests pin down exactly how far the relaxation goes — and, more importantly, how
far it does NOT: a BUSY session is still never interrupted, non-members are unaffected,
mail from a non-member never wakes a WAITING member, and the window expires.
"""

from __future__ import annotations

import asyncio
import time
import types

import pytest

from conductor.autonomy import (
    close_window,
    open_window,
    peers_in_window,
    read_windows,
    write_windows,
)
from conductor.main import AppState
from conductor.models import Status
from conductor.settings import load_settings


# --- the store ---------------------------------------------------------------
def test_open_read_close(tmp_path):
    assert read_windows(tmp_path) == []
    w = open_window(tmp_path, ["[other:a]", "[other:b]"], hours=2)
    got = read_windows(tmp_path)
    assert len(got) == 1 and got[0]["id"] == w["id"]
    assert close_window(tmp_path, w["id"]) is True
    assert read_windows(tmp_path) == []
    assert close_window(tmp_path, "nope") is False


def test_expired_windows_are_ignored(tmp_path):
    write_windows(tmp_path, [{
        "id": "old", "members": ["[other:a]", "[other:b]"],
        "expires": time.time() - 1, "created": 0,
    }])
    assert read_windows(tmp_path) == []          # the time-box IS the safety property


def test_lone_member_window_is_meaningless(tmp_path):
    write_windows(tmp_path, [{
        "id": "solo", "members": ["[other:a]"],
        "expires": time.time() + 999, "created": 0,
    }])
    assert read_windows(tmp_path) == []


def test_windows_compose(tmp_path):
    """The emulator crew and a qualcomm<->imx95 pair can run side by side."""
    open_window(tmp_path, ["[other:a]", "[other:b]"], hours=1)
    open_window(tmp_path, ["[other:c]", "[other:d]"], hours=1)
    wins = read_windows(tmp_path)
    assert len(wins) == 2
    assert peers_in_window(wins, "[other:a]") == {"b"}
    assert peers_in_window(wins, "[other:c]") == {"d"}
    assert peers_in_window(wins, "[other:zz]") == set()   # not in any window


def test_peers_normalizes_tag_spellings(tmp_path):
    open_window(tmp_path, ["[other:qualcomm]", "other:imx95", "docs"], hours=1)
    wins = read_windows(tmp_path)
    assert peers_in_window(wins, "qualcomm") == {"imx95", "docs"}
    assert peers_in_window(wins, "[other:imx95]") == {"qualcomm", "docs"}


# --- the guard (what actually changes) ---------------------------------------
@pytest.fixture
def state(tmp_path):
    s = AppState(load_settings())
    s.coord_root = tmp_path / "coord"
    s._wake_outstanding = {}
    return s


def _sess(tag, status):
    # Mirror the real SessionRecord: `last_activity_at` and `project_dir` are always there.
    return types.SimpleNamespace(tag=tag, status=status, pid=1, terminal_pid=2,
                                 title="t", window_title="w", project_dir="/p",
                                 last_activity_at=time.time())


def _run(state, monkeypatch):
    calls = []
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: calls.append(kw) or True)
    monkeypatch.setattr("conductor.main._read_last_seen", lambda sd, tag: "2026-07-11 10:00")
    asyncio.run(state._wake_unread_recipients())
    return calls


def _mail(sender="imx95"):
    return {"[other:qualcomm]": {"count": 1, "senders": [sender], "latest_ts": "2026-07-11 12:00"}}


def test_waiting_is_not_woken_without_a_window(state, monkeypatch):
    """The baseline that costs Kyle his afternoon: parked at a prompt => never woken."""
    state.sessions = {"q": _sess("[other:qualcomm]", Status.WAITING)}
    state._directed_unread = _mail()
    state._autonomy = []
    assert _run(state, monkeypatch) == []


def test_window_lets_a_peer_wake_a_waiting_session(state, monkeypatch):
    """THE UNLOCK: inside a window, a fellow member may wake a WAITING session."""
    state.sessions = {"q": _sess("[other:qualcomm]", Status.WAITING)}
    state._directed_unread = _mail(sender="imx95")
    state._autonomy = [{"id": "w", "members": ["[other:qualcomm]", "[other:imx95]"],
                        "expires": time.time() + 999, "created": 0}]
    assert len(_run(state, monkeypatch)) == 1


def test_window_does_NOT_interrupt_a_busy_session(state, monkeypatch):
    """The window lifts the *attended* guard, never the *working* one."""
    for status in (Status.ACTIVE, Status.WARM):
        state.sessions = {"q": _sess("[other:qualcomm]", status)}
        state._directed_unread = _mail(sender="imx95")
        state._autonomy = [{"id": "w", "members": ["[other:qualcomm]", "[other:imx95]"],
                            "expires": time.time() + 999, "created": 0}]
        state._wake_outstanding = {}
        assert _run(state, monkeypatch) == [], f"{status} must never be interrupted"


def test_mail_from_a_NON_member_does_not_wake_a_waiting_member(state, monkeypatch):
    """Being in a window doesn't make you wakeable by the whole world — only by peers."""
    state.sessions = {"q": _sess("[other:qualcomm]", Status.WAITING)}
    state._directed_unread = _mail(sender="stranger")          # not in the window
    state._autonomy = [{"id": "w", "members": ["[other:qualcomm]", "[other:imx95]"],
                        "expires": time.time() + 999, "created": 0}]
    assert _run(state, monkeypatch) == []


def test_non_member_waiting_session_unaffected(state, monkeypatch):
    state.sessions = {"q": _sess("[other:qualcomm]", Status.WAITING)}
    state._directed_unread = _mail(sender="imx95")
    state._autonomy = [{"id": "w", "members": ["[other:a]", "[other:b]"],   # qualcomm not in it
                        "expires": time.time() + 999, "created": 0}]
    assert _run(state, monkeypatch) == []


def test_expired_window_stops_waking(state, monkeypatch):
    """When the window closes, the guard comes straight back."""
    state.sessions = {"q": _sess("[other:qualcomm]", Status.WAITING)}
    state._directed_unread = _mail(sender="imx95")
    state._autonomy = []          # what read_windows() returns once it has expired
    assert _run(state, monkeypatch) == []


def test_idle_still_woken_with_no_window(state, monkeypatch):
    """Existing behaviour is untouched: IDLE was always wakeable."""
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _mail()
    state._autonomy = []
    assert len(_run(state, monkeypatch)) == 1
