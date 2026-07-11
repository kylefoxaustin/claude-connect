"""Token auth for the API + WebSocket (mobile/remote access, Phase 0).

Off by default (localhost-only stays frictionless); when a token is configured,
every ``/api/*`` call and the ``/ws`` handshake must present it, while the public
PWA shell (``/``, ``/static``, manifest, service worker) stays reachable.

The integration tests drive the real ``app`` **without** its lifespan (a fake
``cond`` is set by hand) so the scanner / wake loops never start — we're testing
the gate, not booting the fleet.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from conductor.auth import path_requires_auth, resolved_token, token_ok
from conductor.main import app
from conductor.settings import ServerSettings, Settings


# --- pure logic --------------------------------------------------------------
def test_token_ok_disabled_when_unconfigured():
    # Empty configured token == auth off: anything (even None) passes.
    assert token_ok("", None) is True
    assert token_ok("", "whatever") is True


def test_token_ok_requires_exact_match_when_configured():
    assert token_ok("s3cret", "s3cret") is True
    assert token_ok("s3cret", "wrong") is False
    assert token_ok("s3cret", "") is False
    assert token_ok("s3cret", None) is False


def test_path_requires_auth():
    assert path_requires_auth("/api/sessions") is True
    assert path_requires_auth("/api/push/x/approve") is True
    assert path_requires_auth("/ws") is True
    # public shell + version probe
    assert path_requires_auth("/") is False
    assert path_requires_auth("/api/health") is False
    assert path_requires_auth("/static/app.js") is False
    assert path_requires_auth("/sw.js") is False
    assert path_requires_auth("/manifest.webmanifest") is False


def test_resolved_token_env_wins_and_strips(monkeypatch):
    s = Settings(server=ServerSettings(auth_token="from-file"))
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)
    assert resolved_token(s) == "from-file"
    monkeypatch.setenv("CONDUCTOR_AUTH_TOKEN", "  from-env  ")
    assert resolved_token(s) == "from-env"      # env wins, and is stripped


# --- integration through the real app (no lifespan) --------------------------
def _client(monkeypatch, token=""):
    monkeypatch.delenv("CONDUCTOR_AUTH_TOKEN", raising=False)
    app.state.cond = SimpleNamespace(settings=Settings(server=ServerSettings(auth_token=token)))
    return TestClient(app)


def test_no_token_configured_everything_open(monkeypatch):
    c = _client(monkeypatch, token="")
    assert c.get("/api/auth/check").status_code == 200
    assert c.get("/api/health").status_code == 200
    assert c.get("/").status_code == 200


def test_token_configured_gates_the_api(monkeypatch):
    c = _client(monkeypatch, token="letmein")
    assert c.get("/api/auth/check").status_code == 401                       # no token
    assert c.get("/api/auth/check", headers={"X-Conductor-Token": "nope"}).status_code == 401
    assert c.get("/api/auth/check", headers={"X-Conductor-Token": "letmein"}).status_code == 200
    assert c.get("/api/auth/check?token=letmein").status_code == 200         # query fallback (WS style)


def test_public_paths_open_even_with_token(monkeypatch):
    c = _client(monkeypatch, token="letmein")
    assert c.get("/api/health").status_code == 200   # version probe stays public
    assert c.get("/").status_code == 200             # PWA shell stays public


def test_ws_rejected_without_token(monkeypatch):
    c = _client(monkeypatch, token="letmein")
    with pytest.raises(Exception):                   # server closes 1008 before accept
        with c.websocket_connect("/ws"):
            pass


def test_ws_rejected_with_wrong_token(monkeypatch):
    c = _client(monkeypatch, token="letmein")
    with pytest.raises(Exception):
        with c.websocket_connect("/ws?token=wrong"):
            pass
