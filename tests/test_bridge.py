"""Remote-control bridge state + reconnect (/rc), the phone feature.

2026-07-17: qualcomm wasn't on Kyle's phone. The tell was ~/.claude/sessions/<pid>.json →
bridgeSessionId: a bridged session has a `session_…` id, an un-bridged one has null. And an /rc
injected while the session was mid-turn queued in the TUI and silently never bridged — so the
reconnect must fire /rc only when the session is IDLE, and queue it otherwise.
"""

from __future__ import annotations

import asyncio
import json
import types

import pytest

from conductor.bridge import read_bridge
from conductor.main import AppState
from conductor.models import Status
from conductor.settings import load_settings


# --- read_bridge: the ground-truth signal ------------------------------------
def _write(sdir, pid, obj):
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{pid}.json").write_text(json.dumps(obj), encoding="utf-8")


def test_a_null_bridge_id_is_not_bridged(tmp_path):
    _write(tmp_path, 58822, {"pid": 58822, "bridgeSessionId": None, "status": "idle"})
    b = read_bridge(58822, tmp_path)
    assert b["bridged"] is False
    assert b["bridge_id"] is None
    assert b["cc_status"] == "idle"


def test_a_real_bridge_id_is_bridged(tmp_path):
    _write(tmp_path, 16811, {"bridgeSessionId": "session_01PJTSSDorCjhejNHJvUF9de", "status": "busy"})
    b = read_bridge(16811, tmp_path)
    assert b["bridged"] is True
    assert b["bridge_id"] == "session_01PJTSSDorCjhejNHJvUF9de"


def test_missing_or_garbage_file_defaults_to_not_bridged(tmp_path):
    assert read_bridge(999, tmp_path)["bridged"] is False        # no file
    (tmp_path / "5.json").write_text("{not json", encoding="utf-8")
    assert read_bridge(5, tmp_path)["bridged"] is False          # unreadable -> safe default
    assert read_bridge(None, tmp_path)["bridged"] is False       # no pid


# --- the queued-reconnect delivery: fire /rc only when idle -------------------
def _app(tmp_path):
    a = AppState(load_settings())
    a.coord_root = tmp_path / "coord"
    a._rc_pending = {}
    return a


def _sess(sid="s1", status=Status.IDLE, pid=1):
    return types.SimpleNamespace(
        tag="[other:x]", status=status, pid=pid, terminal_pid=2, title="t",
        window_title="w", project_dir="/p", session_id=sid, last_activity_at=0.0)


def _run(app, monkeypatch, sess, bridged=False):
    app.sessions = {"/p": sess}
    sent = []

    async def fake_inject(rec, text, why):
        sent.append(text)
        return True

    monkeypatch.setattr(app, "_inject_text", fake_inject)
    monkeypatch.setattr("conductor.main.read_bridge", lambda pid: {"bridged": bridged})
    monkeypatch.setattr("conductor.main.time", types.SimpleNamespace(time=lambda: 1000.0))
    asyncio.run(app._deliver_rc_reconnects())
    return sent


def test_a_queued_reconnect_fires_when_idle(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._rc_pending = {"s1": {"queued": 1000.0}}
    sent = _run(app, monkeypatch, _sess(status=Status.IDLE))
    assert sent == ["/rc"]
    assert "s1" not in app._rc_pending           # delivered -> dropped


def test_a_queued_reconnect_WAITS_while_busy(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._rc_pending = {"s1": {"queued": 1000.0}}
    sent = _run(app, monkeypatch, _sess(status=Status.WARM))
    assert sent == []                            # never inject /rc mid-turn
    assert "s1" in app._rc_pending               # still queued


def test_a_queued_reconnect_is_dropped_once_bridged(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._rc_pending = {"s1": {"queued": 1000.0}}
    sent = _run(app, monkeypatch, _sess(status=Status.IDLE), bridged=True)
    assert sent == []                            # it connected -> nothing to do
    assert "s1" not in app._rc_pending


def test_a_queued_reconnect_for_a_gone_session_is_dropped(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._rc_pending = {"GONE": {"queued": 1000.0}}
    sent = _run(app, monkeypatch, _sess(sid="s1", status=Status.IDLE))
    assert sent == []
    assert "GONE" not in app._rc_pending         # dead session is the relaunch path, not this


def test_a_queued_reconnect_expires(tmp_path, monkeypatch):
    app = _app(tmp_path)
    app._rc_pending = {"s1": {"queued": 1000.0 - app._RC_TTL_S - 1}}  # older than the TTL
    sent = _run(app, monkeypatch, _sess(status=Status.IDLE))
    assert sent == []
    assert "s1" not in app._rc_pending
