"""The permission-prompt guard — Conductor must never type a confirming Return into a
session that is blocked on a tool-permission prompt.

The live danger, found by watching it: a session sitting on ``Dangerous rm … — 1. Yes /
2. No`` (cursor on Yes) STOPS writing its transcript, so its status decays to IDLE/WAITING
and it looks wakeable. An auto-delivery or a ping button then types ``/msg-check`` + Return
into it — and Return confirms the highlighted default, which is *Yes*. Conductor can approve
a destructive command merely by trying to deliver mail.

The prompt is invisible in the transcript (Claude Code doesn't flush the tool until it
completes — the same reason ask-capture.sh exists), so the guard keys on a marker the
tool-inflight hook writes at PreToolUse, self-clearing once the transcript advances past it.
"""

from __future__ import annotations

import os
import asyncio
import types

import pytest

from conductor.coord import read_inflight
from conductor.main import AppState
from conductor.models import Status
from conductor.settings import load_settings

NOW = 1_800_000_000.0


def _write_marker(coord_root, *, cwd, started, sid="s1", tool="Bash", name=None):
    d = coord_root / "inflight"
    d.mkdir(parents=True, exist_ok=True)
    (d / (name or sid)).write_text(
        f"session_id={sid}\ncwd={cwd}\ntool={tool}\nstarted_epoch={started}\ntranscript=/t.jsonl\n",
        encoding="utf-8",
    )


# --- read_inflight -----------------------------------------------------------
def test_read_inflight_parses_and_keys_by_realpath(tmp_path):
    # A REAL path, not a fictional "/home/kyle/proj". read_inflight keys by realpath, and
    # realpath is platform-dependent -- on Windows a rooted POSIX path gains a drive, so
    # the fixture and the assertion named two different strings. A tmp_path child realpaths
    # to itself on both platforms, so the test states what it means: the key is the cwd.
    proj = str(tmp_path / "proj")
    _write_marker(tmp_path, cwd=proj, started=int(NOW))
    out = read_inflight(tmp_path, now=NOW)
    assert proj in out
    assert out[proj]["started_epoch"] == int(NOW)
    assert out[proj]["tool"] == "Bash"


def test_read_inflight_newest_marker_for_a_cwd_wins(tmp_path):
    p = str(tmp_path / "p")
    _write_marker(tmp_path, cwd=p, started=int(NOW) - 100, sid="old", name="old")
    _write_marker(tmp_path, cwd=p, started=int(NOW), sid="new", name="new")
    out = read_inflight(tmp_path, now=NOW)
    assert out[p]["started_epoch"] == int(NOW)
    assert out[p]["session_id"] == "new"


def test_read_inflight_drops_ancient_ttl(tmp_path):
    _write_marker(tmp_path, cwd="/p", started=int(NOW) - 25 * 3600)
    assert read_inflight(tmp_path, now=NOW) == {}


def test_read_inflight_ignores_tmp_and_malformed(tmp_path):
    d = tmp_path / "inflight"
    d.mkdir(parents=True)
    (d / "half.tmp").write_text("session_id=x\ncwd=/p\nstarted_epoch=1\n", encoding="utf-8")
    (d / "nocwd").write_text("session_id=x\nstarted_epoch=1\n", encoding="utf-8")
    (d / "nostart").write_text("session_id=x\ncwd=/p\n", encoding="utf-8")
    assert read_inflight(tmp_path, now=NOW) == {}


def test_read_inflight_missing_dir(tmp_path):
    assert read_inflight(tmp_path, now=NOW) == {}


# --- _tool_in_flight logic ---------------------------------------------------

# _tool_in_flight looks the session up by REALPATH of its project_dir, so the fixture's key
# and the session's dir have to survive that round trip identically. "/p" does not: on
# Windows realpath gives it a drive, the lookup misses, and _tool_in_flight returns False.
#
# Worth naming because it is not just a red test: the miss makes
# test_safe_when_transcript_advanced_past_the_marker PASS for the wrong reason -- "no marker
# found" and "marker is satisfied" are both False, so it was green on Windows while
# exercising nothing.
_P = os.path.realpath("/p")

@pytest.fixture
def app():
    a = AppState(load_settings())
    return a


def _sess(activity):
    return types.SimpleNamespace(
        tag="[other:x]", status=Status.IDLE, pid=1, terminal_pid=2, title="t",
        window_title="w", project_dir=_P, last_activity_at=activity)


def test_blocked_when_transcript_frozen_behind_the_marker(app):
    app._inflight = {_P: {"started_epoch": int(NOW), "session_id": "s1"}}
    # transcript last moved BEFORE the tool started ⇒ still pending ⇒ blocked
    assert app._tool_in_flight(_sess(activity=NOW - 30)) is True


def test_safe_when_transcript_advanced_past_the_marker(app):
    app._inflight = {_P: {"started_epoch": int(NOW) - 30, "session_id": "s1"}}
    # transcript moved AFTER the tool started ⇒ tool resolved ⇒ safe
    assert app._tool_in_flight(_sess(activity=NOW)) is False


def test_safe_when_no_marker(app):
    app._inflight = {}
    assert app._tool_in_flight(_sess(activity=NOW)) is False


def test_marker_for_a_different_cwd_does_not_block(app):
    app._inflight = {"/other": {"started_epoch": int(NOW), "session_id": "s1"}}
    assert app._tool_in_flight(_sess(activity=NOW - 30)) is False


# --- the choke point actually refuses ----------------------------------------
def _wire(app, monkeypatch):
    sent, attested = [], []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw["text"]) or True)
    monkeypatch.setattr("conductor.main.attest", lambda *a, **k: attested.append(k))
    return sent, attested


def test_inject_text_REFUSES_when_tool_in_flight(app, monkeypatch):
    """The whole point: no keystroke, and — just as important — no attestation of one that
    never happened."""
    app._inflight = {_P: {"started_epoch": int(NOW), "session_id": "s1"}}
    sent, attested = _wire(app, monkeypatch)
    ok = asyncio.run(app._inject_text(_sess(activity=NOW - 30), "/msg-check", "test"))
    assert ok is False
    assert sent == []          # nothing typed into the permission prompt
    assert attested == []      # and we didn't record a keystroke we didn't send


def test_inject_text_TYPES_once_the_tool_resolved(app, monkeypatch):
    app._inflight = {_P: {"started_epoch": int(NOW) - 30, "session_id": "s1"}}
    sent, attested = _wire(app, monkeypatch)
    ok = asyncio.run(app._inject_text(_sess(activity=NOW), "/msg-check", "test"))
    assert ok is True
    assert sent == ["/msg-check"]
    assert len(attested) == 1


def test_inject_text_TYPES_when_nothing_in_flight(app, monkeypatch):
    app._inflight = {}
    sent, _ = _wire(app, monkeypatch)
    ok = asyncio.run(app._inject_text(_sess(activity=NOW), "/msg-check", "test"))
    assert ok is True
    assert sent == ["/msg-check"]
