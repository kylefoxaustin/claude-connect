"""Remote prompt routing — `@tag message` delivers your words into a session as a prompt.

The endpoint queues; the drain injects once the target is QUIET (a busy session eats
keystrokes), attributed to the human in the provenance ledger.
"""

from __future__ import annotations

import asyncio
import types

from starlette.testclient import TestClient

import conductor.main as m
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


def _sess(tag="[other:claude-connect]", status=Status.IDLE):
    return types.SimpleNamespace(tag=tag, status=status, pid=100, terminal_pid=101,
                                 title="t", window_title="w", project_dir="/p", session_id="s1")


def test_route_to_live_session_queues_it(tmp_path, monkeypatch):
    st = _st(); st.sessions = {"k": _sess()}
    r = _client(st, monkeypatch).post("/api/prompt-route",
                                      json={"tag": "@claude-connect", "message": "do X please"})
    assert r.status_code == 200
    assert r.json()["queued"] is True
    assert len(st._remote_prompts) == 1
    rp = next(iter(st._remote_prompts.values()))
    assert rp["message"] == "do X please"
    assert rp["actor"].startswith("human")          # attributed to the operator, not conductor


def test_route_unknown_tag_404(tmp_path, monkeypatch):
    st = _st(); st.sessions = {}
    r = _client(st, monkeypatch).post("/api/prompt-route",
                                      json={"tag": "nobody", "message": "hi"})
    assert r.status_code == 404


def test_route_empty_message_400(tmp_path, monkeypatch):
    st = _st(); st.sessions = {"k": _sess()}
    r = _client(st, monkeypatch).post("/api/prompt-route",
                                      json={"tag": "claude-connect", "message": "   "})
    assert r.status_code == 400


def test_drain_injects_when_idle_and_attributes_human(monkeypatch):
    st = _st(); st.sessions = {"k": _sess(status=Status.IDLE)}
    sent = []

    async def fake_inject(rec, text, why, *, actor="conductor"):
        sent.append((text, actor)); return True
    monkeypatch.setattr(st, "_inject_text", fake_inject)

    st._remote_prompts = {"claude-connect:1": {
        "tag": "claude-connect", "message": "hello there", "queued": __import__("time").time(),
        "source": "human:1.2.3.4", "actor": "human:1.2.3.4"}}
    asyncio.run(st._deliver_remote_prompts())
    assert sent == [("hello there", "human:1.2.3.4")]
    assert st._remote_prompts == {}                 # delivered → drained


def test_drain_holds_when_busy(monkeypatch):
    st = _st(); st.sessions = {"k": _sess(status=Status.ACTIVE)}   # busy
    called = []

    async def fake_inject(rec, text, why, *, actor="conductor"):
        called.append(text); return True
    monkeypatch.setattr(st, "_inject_text", fake_inject)

    st._remote_prompts = {"claude-connect:1": {
        "tag": "claude-connect", "message": "later", "queued": __import__("time").time(),
        "source": "human", "actor": "human"}}
    asyncio.run(st._deliver_remote_prompts())
    assert called == []                             # busy → not injected
    assert len(st._remote_prompts) == 1             # kept for retry when quiet


def test_drain_route_files_enqueues_and_removes(tmp_path):
    """The hook drops a route file; Conductor's drain turns it into a queued remote prompt."""
    import json as _json
    st = _st()
    st.coord_root = tmp_path / "coord"
    rdir = st.coord_root / "prompt-routes"; rdir.mkdir(parents=True)
    (rdir / "1.json").write_text(_json.dumps(
        {"target": "qualcomm", "message": "rerun it", "source_session": "abc12345", "ts": 1.0}))
    st._drain_prompt_route_files()
    assert len(st._remote_prompts) == 1
    rp = next(iter(st._remote_prompts.values()))
    assert rp["tag"] == "qualcomm" and rp["message"] == "rerun it"
    assert rp["actor"] == "human"
    assert not list(rdir.glob("*.json"))          # file consumed


def test_drain_bad_route_file_is_removed_not_crashing(tmp_path):
    st = _st()
    st.coord_root = tmp_path / "coord"
    rdir = st.coord_root / "prompt-routes"; rdir.mkdir(parents=True)
    (rdir / "bad.json").write_text("not json")
    st._drain_prompt_route_files()                # must not raise
    assert st._remote_prompts == {}
    assert not list(rdir.glob("*.json"))          # garbage cleaned up
