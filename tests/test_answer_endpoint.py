"""Answering a decision for a DEAD session must not type into the void (#4).

If the asking session died while its picker was up, the answer endpoint must refuse with a
distinct, actionable signal — code ``session_not_running`` plus the parked project — so the
UI offers a relaunch instead of a false "Already answered".
"""

from __future__ import annotations

import os

from starlette.testclient import TestClient

from conductor.main import AppState, app
from conductor.models import ParkedSession
from conductor.settings import load_settings


def _st() -> AppState:
    s = load_settings()
    s.server.auth_token = ""       # disable auth for the test (the real settings.toml has one)
    return AppState(s)


def _client(st, monkeypatch) -> TestClient:
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)  # env wins over settings
    app.state.cond = st
    return TestClient(app)


def _decision(cwd, sid="dead1"):
    return {"session_id": sid, "cwd": cwd,
            "questions": [{"question": "Reboot?", "header": "H", "multiSelect": False,
                           "options": [{"label": "Yes", "description": ""}]}]}


def test_answer_dead_session_returns_relaunchable_409(tmp_path, monkeypatch):
    cwd = str(tmp_path / "proj")
    os.makedirs(cwd)
    st = _st()
    st.decisions = [_decision(cwd)]
    st.sessions = {}               # nothing live → _session_for_decision returns None
    st.parked = [ParkedSession(project="encoded-proj", project_dir=cwd, title="t",
                               tag="[x]", session_id="dead1", last_activity_at=0.0,
                               message_count=0)]
    r = _client(st, monkeypatch).post("/api/decisions/dead1", json={"answers": [["Yes"]]})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "session_not_running"
    assert d["project"] == "encoded-proj"     # the UI can offer a one-tap relaunch


def test_answer_dead_session_without_parked_still_says_not_running(tmp_path, monkeypatch):
    cwd = str(tmp_path / "gone")   # never created / no parked entry
    st = _st()
    st.decisions = [_decision(cwd)]
    st.sessions = {}
    st.parked = []
    r = _client(st, monkeypatch).post("/api/decisions/dead1", json={"answers": [["Yes"]]})
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "session_not_running"
    assert d["project"] is None


def test_answer_already_gone_decision_is_distinct_code(tmp_path, monkeypatch):
    st = _st()
    st.decisions = []              # already answered at the keyboard / reaped
    st.sessions = {}
    st.parked = []
    r = _client(st, monkeypatch).post("/api/decisions/whatever", json={"answers": [["Yes"]]})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "already_answered"
