"""The /msg-check storm. Third recurrence of one bug; this time it gets pinned down.

Overnight, Conductor fired ~450 keystroke injections and one session accumulated **16 queued
/msg-checks**. Kyle found them stacked in the terminal in the morning.

THE FACT THAT WAS WRONG, and everything follows from it:

    A busy Claude Code session does NOT drop injected keystrokes. It QUEUES them.
    ("Press up to edit queued messages.")

So a re-injection is never a repair — it is another identical command stacked behind the
first. And ONE /msg-check drains the entire backlog, so a second can only ever be noise.

The watermark dedup was right: *once woken, stay quiet until the recipient actually reads.*
But a 10-minute "re-arm anyway" escape hatch — added for the corner case of a session that
never writes a last-seen — defeated it, and re-broke the exact bug the dedup existed to fix.
Over seven hours that is 42 re-wakes into a session that was simply busy.

The tell was always available: **a session grinding through a long tool call stops writing
its transcript** — which is precisely why its status decays to IDLE and it looks wakeable in
the first place. A frozen transcript means our check is still QUEUED. Only a transcript that
has MOVED while the watermark has NOT is evidence a keystroke was actually lost.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from conductor.main import _WAKE_RETRY_SECONDS, AppState, _unpack_wake
from conductor.models import Status
from conductor.settings import load_settings

NOW = 1_800_000_000.0


@pytest.fixture
def app(tmp_path, monkeypatch):
    a = AppState(load_settings())
    a.coord_root = tmp_path / "coord"
    a._wake_outstanding = {}
    a._directed_unread = {"[other:x]": {"count": 3, "senders": ["y"], "latest_ts": "2026-07-12 02:00"}}
    monkeypatch.setattr("conductor.main._read_last_seen", lambda sd, tag: "2026-07-11 20:00")
    monkeypatch.setattr("conductor.main.write_wake_state", lambda *a, **k: None)
    return a


def _sess(status=Status.IDLE, activity=NOW):
    return types.SimpleNamespace(
        tag="[other:x]", status=status, pid=1, terminal_pid=2, title="t",
        window_title="w", project_dir="/p", last_activity_at=activity)


def _run(app, monkeypatch, sess):
    app.sessions = {"/p": sess}
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw["text"]) or True)
    monkeypatch.setattr("conductor.main.time", types.SimpleNamespace(time=lambda: NOW))
    asyncio.run(app._wake_unread_recipients())
    return sent


def test_an_unread_session_is_woken_once(app, monkeypatch):
    assert _run(app, monkeypatch, _sess()) == ["/msg-check"]


def test_a_BUSY_session_whose_transcript_is_FROZEN_is_never_re_woken(app, monkeypatch):
    """THE STORM. It is deep in a long tool call, so its transcript hasn't moved — which is
    exactly why it decayed to IDLE and looked wakeable. Our /msg-check is QUEUED behind that
    work. A second one would just stack, and 42 of them is what Kyle woke up to.
    """
    app._wake_outstanding = {
        # woken an hour ago; transcript hasn't advanced a millisecond since
        "[other:x]": ("2026-07-11 20:00", NOW - _WAKE_RETRY_SECONDS - 1, NOW - 7200),
    }
    assert _run(app, monkeypatch, _sess(activity=NOW - 7200)) == []


def test_a_lost_keystroke_IS_retried(app, monkeypatch):
    """The one case a retry is legitimate. The session has been visibly ALIVE (its transcript
    moved) since we typed, and it still hasn't read — so the keystroke never landed."""
    app._wake_outstanding = {
        "[other:x]": ("2026-07-11 20:00", NOW - _WAKE_RETRY_SECONDS - 1, NOW - 7200),
    }
    assert _run(app, monkeypatch, _sess(activity=NOW - 60)) == ["/msg-check"]


def test_no_retry_before_the_timeout_even_if_it_has_been_active(app, monkeypatch):
    app._wake_outstanding = {
        "[other:x]": ("2026-07-11 20:00", NOW - 60, NOW - 7200),
    }
    assert _run(app, monkeypatch, _sess(activity=NOW - 5)) == []


def test_once_it_READS_the_backlog_clears_and_it_re_arms(app, monkeypatch):
    """The normal path: the watermark advances, so the entry is dropped and a future message
    can wake it again."""
    app._wake_outstanding = {"[other:x]": ("2026-07-10 09:00", NOW - 10, NOW)}
    # _read_last_seen now returns a NEWER watermark than the one we recorded
    assert _run(app, monkeypatch, _sess()) == ["/msg-check"]


# --- the persisted state survives the format change --------------------------
def test_legacy_two_tuple_wake_state_cannot_trigger_a_retry():
    """coord/wake-state.json persists across restarts, so the first run after this change
    reads the OLD 2-tuples. If a legacy entry defaulted its activity stamp to 0, every one of
    them would immediately look 'active since we typed' and re-prod the whole fleet — which is
    precisely the storm we're ending. Default to +inf instead."""
    seen, woke, act = _unpack_wake(("2026-07-11 20:00", 123.0))
    assert (seen, woke) == ("2026-07-11 20:00", 123.0)
    assert act == float("inf")           # no transcript can ever exceed this -> no retry


def test_new_three_tuple_round_trips():
    assert _unpack_wake(("s", 1.0, 2.0)) == ("s", 1.0, 2.0)


def test_garbage_wake_state_is_inert():
    assert _unpack_wake(None) == ("", 0.0, float("inf"))
