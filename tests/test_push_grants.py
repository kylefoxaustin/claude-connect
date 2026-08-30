"""Push approval: a durable grant, not a race.

The bug this guards: approving DELETED the pending request and armed a 30-minute token.
Kyle approves from his phone; the *session* is the one that has to notice and re-run the
push — and it may be asleep, mid-task, or unreachable because Conductor isn't running. If
the clock ran out first, the token expired and the request was already gone, so **the
approval vanished leaving no trace**. The next push filed a fresh request, and Kyle saw a
duplicate ask with no hint that he had already said yes.

The fix has two halves and BOTH are load-bearing:
  1. the grant is durable (24h) — it waits for the agent instead of racing it;
  2. the grant is VISIBLE and revocable — which is what makes a long-lived permission safe.
     A short fuse is not a safety property if its failure mode is losing the decision.
"""

from __future__ import annotations

import time

from conductor.coord import read_push_grants

NOW = 1_800_000_000.0


def _token(coord, key="repo_a", *, expires, name="repo", legacy=False):
    d = coord / "push-tokens"
    d.mkdir(parents=True, exist_ok=True)
    f = d / key
    if legacy:
        f.write_text(f"{int(expires)}\n")          # the pre-change bare-epoch format
    else:
        f.write_text(f"expires={int(expires)}\nrepo_name={name}\n"
                     f"approved={int(expires) - 86400}\napproved_at=2026-07-12 01:00\n")
    return f


def test_an_armed_grant_is_visible(tmp_path):
    """The state that used to have no representation at all: 'you said yes, and it hasn't
    been used yet'. Without this, a click that landed and a click that evaporated looked
    exactly the same."""
    _token(tmp_path, expires=NOW + 86400, name="claude-connect")
    g = read_push_grants(tmp_path, now=NOW)
    assert len(g) == 1
    assert g[0]["repo_name"] == "claude-connect"
    assert 86000 < g[0]["expires_in"] <= 86400


def test_a_grant_survives_the_session_not_retrying_for_an_hour(tmp_path):
    """THE REGRESSION. Under the old 30-minute TTL this grant would be dead and gone."""
    _token(tmp_path, expires=NOW + 86400)
    still_there = read_push_grants(tmp_path, now=NOW + 3600)   # an hour later
    assert len(still_there) == 1


def test_an_expired_grant_is_not_shown(tmp_path):
    _token(tmp_path, expires=NOW - 1)
    assert read_push_grants(tmp_path, now=NOW) == []


def test_a_legacy_bare_epoch_token_is_still_honoured(tmp_path):
    """A token written by the OLD code must still be readable. Failing closed here would
    look exactly like 'Kyle's approval didn't work' — on the one control he relies on."""
    _token(tmp_path, expires=NOW + 600, legacy=True)
    g = read_push_grants(tmp_path, now=NOW)
    assert len(g) == 1
    assert g[0]["expires_in"] == 600


def test_no_tokens_dir_is_just_empty(tmp_path):
    assert read_push_grants(tmp_path) == []


def test_garbage_token_is_ignored_not_fatal(tmp_path):
    d = tmp_path / "push-tokens"
    d.mkdir()
    (d / "junk").write_text("this is not a number\n")
    assert read_push_grants(tmp_path, now=NOW) == []


def test_grants_sorted_soonest_to_expire_first(tmp_path):
    _token(tmp_path, "late", expires=NOW + 80000, name="late")
    _token(tmp_path, "soon", expires=NOW + 100, name="soon")
    assert [g["repo_name"] for g in read_push_grants(tmp_path, now=NOW)] == ["soon", "late"]


# --- the approval ping must not be typed into a busy session ------------------
# Kyle approved on his phone. Conductor logged "woke [claude-connect] — push approved".
# The text landed in NO session's transcript. It was typed into the void.
#
# A session that was just DENIED a push is mid-turn and BUSY, and a busy Claude Code session
# SWALLOWS injected keystrokes. send_keys_to_session returned True because xdotool exited 0 —
# but xdotool succeeding is not the message arriving. The earlier pings only worked because
# the session happened to be idle at that moment. Luck, not design.
import asyncio
import types

from conductor.main import AppState
from conductor.models import Status
from conductor.settings import load_settings


def _app(tmp_path):
    a = AppState(load_settings())
    a.coord_root = tmp_path / "coord"
    a._wake_outstanding = {}
    return a


def _sess(status, project_dir):
    return types.SimpleNamespace(
        tag="[other:claude-connect]", status=status, pid=1, terminal_pid=2,
        title="t", window_title="w", project_dir=project_dir)


def _run(app, monkeypatch):
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw["text"]) or True)
    asyncio.run(app._deliver_push_notices())
    return sent


def test_a_busy_session_is_NOT_typed_at(tmp_path, monkeypatch):
    """THE REGRESSION. Injecting here 'succeeds' and delivers nothing."""
    app = _app(tmp_path)
    proj = str(tmp_path / "repo")
    app._push_notices = {"k": {"cwd": proj, "repo": "claude-connect", "queued": time.time()}}
    app.sessions = {proj: _sess(Status.WARM, proj)}       # mid-turn, reacting to the denial

    assert _run(app, monkeypatch) == []                   # nothing typed
    assert "k" in app._push_notices                       # and it is NOT forgotten


def test_it_is_delivered_once_the_session_goes_quiet(tmp_path, monkeypatch):
    app = _app(tmp_path)
    proj = str(tmp_path / "repo")
    app._push_notices = {"k": {"cwd": proj, "repo": "claude-connect", "queued": time.time()}}
    app.sessions = {proj: _sess(Status.IDLE, proj)}

    sent = _run(app, monkeypatch)
    assert len(sent) == 1
    # The notice is a DOORBELL now, not a sentence: bus.sh's hook expands it from the grant
    # file at read time. Assert the token and the repo, which is all the keystroke carries —
    # asserting prose here would just re-pin the thing we deliberately stopped typing.
    assert sent[0].startswith("push approved:") and "claude-connect" in sent[0]
    assert app._push_notices == {}                        # delivered -> forgotten


def test_an_undeliverable_notice_expires_instead_of_nagging_forever(tmp_path, monkeypatch):
    """If the session never goes quiet, no harm done: the grant is DURABLE, so the agent's
    next push succeeds whether or not it ever heard a word. The ping is a courtesy, not the
    channel — which is exactly what saved the live case."""
    app = _app(tmp_path)
    proj = str(tmp_path / "repo")
    app._push_notices = {"k": {"cwd": proj, "repo": "x",
                               "queued": time.time() - app._NOTICE_TTL_S - 1}}
    app.sessions = {proj: _sess(Status.IDLE, proj)}

    assert _run(app, monkeypatch) == []
    assert app._push_notices == {}


def test_a_dead_session_does_not_block_the_queue(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._push_notices = {"k": {"cwd": "/gone", "repo": "x", "queued": time.time()}}
    app.sessions = {}
    assert _run(app, monkeypatch) == []                   # no crash, nothing typed
