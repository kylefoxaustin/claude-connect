"""Fleet-coordination Phase 1 — auto-delivery (Part A).

The point: stop Kyle from being the fleet's message courier. A message *addressed
to* a session (``to:<tag>``) that the session hasn't read should wake an idle
recipient on its own — but never a busy one, never a broadcast, and never twice for
the same batch.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from conductor.bus import _address_targets, _plain_name, directed_unread_all
from conductor.main import AppState, _WAKEABLE_STATUSES
from conductor.models import Status
from conductor.settings import load_settings


# --- addressing parse --------------------------------------------------------
def test_plain_name_normalizes():
    assert _plain_name("[other:qualcomm]") == "qualcomm"
    assert _plain_name("other:orb_slam") == "orb_slam"
    assert _plain_name("[backend]") == "backend"


def test_address_targets():
    assert _address_targets("to:qualcomm to:all — [x] hi") == frozenset({"qualcomm", "all"})
    assert _address_targets("to:other:orb_slam — [x] hi") == frozenset({"orb_slam"})
    assert _address_targets("just a broadcast, no address line") == frozenset()


# --- directed_unread_all -----------------------------------------------------
LOG = """\
## 2026-07-10 10:00 [other:alice]

to:bob — [alice] please run the thing

## 2026-07-10 10:05 [other:bob]

to:all — [bob] status update for everyone

## 2026-07-10 10:10 [other:carol]

to:bob to:dave — [carol] need both of you
"""


def _write(tmp_path, log=LOG, seen=None):
    msgs = tmp_path / "messages.md"
    msgs.write_text(log)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    for tag, ts in (seen or {}).items():
        (state / f"{tag}.last-seen").write_text(ts)
    return msgs, state


def test_directed_counts_only_addressed_messages(tmp_path):
    # bob and dave have a read-baseline (any live session does after its first prompt).
    seen = {"[other:bob]": "2026-01-01 00:00", "[other:dave]": "2026-01-01 00:00",
            "[other:alice]": "2026-01-01 00:00"}
    msgs, state = _write(tmp_path, seen=seen)
    r = directed_unread_all(msgs, state, ["[other:bob]", "[other:dave]", "[other:alice]"])
    assert r["[other:bob]"]["count"] == 2           # alice's + carol's, addressed to bob
    assert set(r["[other:bob]"]["senders"]) == {"alice", "carol"}
    assert r["[other:dave]"]["count"] == 1           # only carol's
    assert r["[other:alice]"]["count"] == 0          # nobody addressed alice


def test_never_checked_never_sent_has_no_unread_basis(tmp_path):
    """A brand-new session (no last-seen, never posted) must NOT get history dumped
    on it — same conservative baseline as the 📬 badge (v2.5.1)."""
    msgs, state = _write(tmp_path)  # no last-seen for anyone
    assert directed_unread_all(msgs, state, ["[other:dave]"])["[other:dave]"]["count"] == 0


def test_broadcast_does_not_count_as_directed(tmp_path):
    msgs, state = _write(tmp_path, seen={"[other:zed]": "2026-01-01 00:00"})
    # zed is on nobody's to: list, and bob's to:all broadcast must not count
    assert directed_unread_all(msgs, state, ["[other:zed]"])["[other:zed]"]["count"] == 0


def test_last_seen_baseline_excludes_read(tmp_path):
    msgs, state = _write(tmp_path, seen={"[other:bob]": "2026-07-10 10:07"})
    # bob read through 10:07 -> alice's 10:00 is read, carol's 10:10 is not
    assert directed_unread_all(msgs, state, ["[other:bob]"])["[other:bob]"]["count"] == 1


def test_own_messages_never_count(tmp_path):
    log = "## 2026-07-10 10:00 [other:bob]\n\nto:bob — [bob] note to self\n"
    msgs, state = _write(tmp_path, log=log, seen={"[other:bob]": "2026-01-01 00:00"})
    assert directed_unread_all(msgs, state, ["[other:bob]"])["[other:bob]"]["count"] == 0


# --- the wake ----------------------------------------------------------------
@pytest.fixture
def state():
    return AppState(load_settings())


def _sess(tag, status):
    return types.SimpleNamespace(tag=tag, status=status, pid=1, terminal_pid=2, title="t", window_title="w")


def _run_wake(state, monkeypatch):
    calls = []
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: calls.append(kw) or True)
    asyncio.run(state._wake_unread_recipients())
    return calls


def _directed(ts="2026-07-10 17:00", count=1):
    return {"[other:qualcomm]": {"count": count, "senders": ["imx95"], "latest_ts": ts}}


def test_idle_recipient_woken_once_per_batch(state, monkeypatch):
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert len(_run_wake(state, monkeypatch)) == 1
    assert len(_run_wake(state, monkeypatch)) == 0          # same batch, no re-nag
    state._directed_unread = _directed(ts="2026-07-10 17:30", count=2)
    assert len(_run_wake(state, monkeypatch)) == 1          # newer batch -> wake again


@pytest.mark.parametrize("status", [Status.ACTIVE, Status.WARM, Status.WAITING])
def test_busy_or_attended_recipient_never_woken(state, monkeypatch, status):
    state.sessions = {"q": _sess("[other:qualcomm]", status)}
    state._directed_unread = _directed()
    assert _run_wake(state, monkeypatch) == []
    assert status not in _WAKEABLE_STATUSES


def test_no_directed_unread_no_wake(state, monkeypatch):
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = {"[other:qualcomm]": {"count": 0, "senders": [], "latest_ts": ""}}
    assert _run_wake(state, monkeypatch) == []


def test_autodeliver_off_switch(state, monkeypatch):
    state.settings.bus.autodeliver = False
    state.sessions = {"q": _sess("[other:qualcomm]", Status.IDLE)}
    state._directed_unread = _directed()
    assert _run_wake(state, monkeypatch) == []
