"""Reconstitute endpoints (GET plan + POST execute guards) via TestClient."""

from __future__ import annotations

import json
import os
import types

from starlette.testclient import TestClient

from conductor.main import AppState, app
from conductor.models import Status
from conductor.settings import load_settings


def _st() -> AppState:
    s = load_settings()
    s.server.auth_token = ""
    return AppState(s)


def _client(st, monkeypatch) -> TestClient:
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)
    app.state.cond = st
    return TestClient(app)


def _rec(cwd):
    return types.SimpleNamespace(project_dir=cwd, status=Status.IDLE, session_id="s1")


def _roster_file(tmp_path, sessions):
    p = tmp_path / "roster.json"
    p.write_text(json.dumps({"host": "h", "home": "/home/kyle", "sessions": sessions}))
    return str(p)


def _entry(cwd, **kw):
    e = {"tag": "[other:x]", "member": "x", "cwd": cwd, "is_repo": False,
         "git_remote": None, "git_branch": None, "git_head": None, "git_dirty": False,
         "last_active": 0.0, "tokens_out": 0, "transcript_bytes": 0, "transcript_paths": []}
    e.update(kw)
    return e


def test_get_plan_classifies_sessions(tmp_path, monkeypatch):
    present = tmp_path / "present"; present.mkdir()
    roster = _roster_file(tmp_path, [
        _entry(str(present)),
        _entry(str(tmp_path / "clone_me"), is_repo=True, git_remote="https://h/r.git"),
    ])
    st = _st(); st.sessions = {}
    r = _client(st, monkeypatch).get(f"/api/reconstitute?roster={roster}")
    assert r.status_code == 200
    data = r.json()
    assert data["session_count"] == 2
    assert data["counts"].get("present") == 1
    assert data["counts"].get("clone") == 1


def test_get_plan_marks_live(tmp_path, monkeypatch):
    live = tmp_path / "live"; live.mkdir()
    roster = _roster_file(tmp_path, [_entry(str(live))])
    st = _st(); st.sessions = {"k": _rec(str(live))}     # a live session there
    data = _client(st, monkeypatch).get(f"/api/reconstitute?roster={roster}").json()
    assert data["sessions"][0]["status"] == "live"


def test_execute_refuses_when_live(tmp_path, monkeypatch):
    live = tmp_path / "live"; live.mkdir()
    roster = _roster_file(tmp_path, [_entry(str(live))])
    st = _st(); st.sessions = {"k": _rec(str(live))}
    r = _client(st, monkeypatch).post("/api/reconstitute/execute",
                                      json={"cwd": str(live), "roster": roster})
    assert r.status_code == 409


def test_execute_404_when_cwd_not_in_roster(tmp_path, monkeypatch):
    roster = _roster_file(tmp_path, [_entry(str(tmp_path / "a"))])
    st = _st(); st.sessions = {}
    r = _client(st, monkeypatch).post("/api/reconstitute/execute",
                                      json={"cwd": str(tmp_path / "zzz"), "roster": roster})
    assert r.status_code == 404


def test_execute_409_when_blocked(tmp_path, monkeypatch):
    gone = str(tmp_path / "gone")           # no dir, no repo, no transcript → blocked
    roster = _roster_file(tmp_path, [_entry(gone)])
    st = _st(); st.sessions = {}
    r = _client(st, monkeypatch).post("/api/reconstitute/execute",
                                      json={"cwd": gone, "roster": roster})
    assert r.status_code == 409
