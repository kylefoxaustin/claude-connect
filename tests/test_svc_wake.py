"""A service Claude's wake is ONE-SHOT — and Conductor must re-deliver it.

image_gen, 2026-07-17: tipometer queued a sprite job and went back to work. The wake
that normally kicks a service into running ``/svc-next`` is posted by the requester at
request time and injected by auto-delivery — but Conductor was CRASHED when the job
landed, so the nudge was lost. There is no re-wake and the per-prompt hook carries no
service-queue line, so image_gen sat idle on the job for 28 minutes; from the phone it
looked "stuck". Kyle had no way to start it.

``_wake_stale_service_heads`` closes that: a queue HEAD older than ``_SVC_STALE_SECONDS``
in front of an idle service gets one /msg-check, once per job. The subtle bug this test
guards is the name↔tag mismatch — a service is registered as ``image_gen`` while the
session's tag normalizes to ``other:image_gen``, so a naive ``_live_session_for(name)``
never matches and the wake silently never fires.
"""

from __future__ import annotations

import asyncio
import types

import pytest

from conductor.main import AppState, _SVC_STALE_SECONDS
from conductor.models import Status
from conductor.settings import load_settings

NOW = 1_800_000_000.0
STALE = NOW - _SVC_STALE_SECONDS - 10   # a job that landed comfortably past the threshold
FRESH = NOW - 5                          # a job that just landed


@pytest.fixture
def app(tmp_path, monkeypatch):
    a = AppState(load_settings())
    a.coord_root = tmp_path / "coord"
    a._svc_woken = set()
    monkeypatch.setattr("conductor.main.time", types.SimpleNamespace(time=lambda: NOW))
    return a


def _svc(*, name="image_gen", queue_epoch=STALE, jid="job-1", serving=None, held=False):
    queue = [] if queue_epoch is None else [{"id": jid, "requester": "tipometer",
                                             "text": "sprites", "epoch": queue_epoch}]
    return {"name": name, "serving": serving, "queue": queue, "held": held, "hold_reason": ""}


def _sess(status=Status.IDLE, tag="[other:image_gen]"):
    return types.SimpleNamespace(
        tag=tag, status=status, pid=1, terminal_pid=2, title="t",
        window_title="w", project_dir="/p", last_activity_at=NOW, session_id="s1")


def _run(app, monkeypatch, svc, sess):
    app.services = {"services": [svc]} if svc else {"services": []}
    app.sessions = {"/p": sess} if sess else {}
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append((kw.get("text"))) or True)
    asyncio.run(app._wake_stale_service_heads())
    return sent


def test_idle_service_with_stale_head_is_woken(app, monkeypatch):
    # The whole point: the name/tag mismatch (image_gen vs other:image_gen) must still resolve.
    assert _run(app, monkeypatch, _svc(), _sess()) == ["/msg-check"]


def test_woken_only_once_per_job(app, monkeypatch):
    svc, sess = _svc(), _sess()
    assert _run(app, monkeypatch, svc, sess) == ["/msg-check"]
    assert _run(app, monkeypatch, svc, sess) == []          # same job id -> stays quiet


def test_a_new_job_head_re_arms(app, monkeypatch):
    assert _run(app, monkeypatch, _svc(jid="job-1"), _sess()) == ["/msg-check"]
    # tipometer's job cleared, a different requester's job is now the head
    assert _run(app, monkeypatch, _svc(jid="job-2"), _sess()) == ["/msg-check"]


def test_busy_service_is_not_woken(app, monkeypatch):
    # It's WARM — very possibly working this very job (a service can take it without /svc-next,
    # leaving the entry queued). Never prod a service mid-render; retry when it's idle.
    assert _run(app, monkeypatch, _svc(), _sess(status=Status.WARM)) == []
    assert _run(app, monkeypatch, _svc(), _sess(status=Status.ACTIVE)) == []


def test_held_service_is_not_woken(app, monkeypatch):
    # Kyle claimed the next opening; don't pull the queue.
    assert _run(app, monkeypatch, _svc(held=True), _sess()) == []


def test_already_serving_is_not_woken(app, monkeypatch):
    serving = {"id": "cur", "requester": "docs", "text": "x", "epoch": STALE}
    assert _run(app, monkeypatch, _svc(serving=serving), _sess()) == []


def test_fresh_job_gets_the_request_time_wake_first(app, monkeypatch):
    # Under the staleness threshold — the requester's own ping gets first crack.
    assert _run(app, monkeypatch, _svc(queue_epoch=FRESH), _sess()) == []


def test_empty_queue_no_wake(app, monkeypatch):
    assert _run(app, monkeypatch, _svc(queue_epoch=None), _sess()) == []


def test_no_live_session_no_crash(app, monkeypatch):
    # Service registered but its session isn't running — nothing to wake, must not raise.
    assert _run(app, monkeypatch, _svc(), None) == []


def test_autodeliver_off_disables_it(app, monkeypatch):
    app.settings.bus.autodeliver = False
    assert _run(app, monkeypatch, _svc(), _sess()) == []


def test_explicit_table_tag_also_matches_by_bare_name(app, monkeypatch):
    # A service whose session uses an explicit-table tag (no other: prefix) matches by bare name.
    assert _run(app, monkeypatch, _svc(name="backend"), _sess(tag="[backend]")) == ["/msg-check"]


# --- the manual phone control: POST /api/services/<name>/nudge ----------------
from conductor.main import service_action  # noqa: E402


def _req(app):
    return types.SimpleNamespace(app=types.SimpleNamespace(state=types.SimpleNamespace(cond=app)))


def _nudge(app, monkeypatch, sess):
    app.sessions = {"/p": sess} if sess else {}
    sent = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: sent.append(kw.get("text")) or True)
    out = asyncio.run(service_action("image_gen", "nudge", _req(app)))
    return out, sent


def test_nudge_injects_when_idle(app, monkeypatch):
    out, sent = _nudge(app, monkeypatch, _sess(status=Status.IDLE))
    assert out["ok"] is True and sent == ["/msg-check"]


def test_nudge_busy_does_not_inject(app, monkeypatch):
    out, sent = _nudge(app, monkeypatch, _sess(status=Status.WARM))
    # ok=True (it's fine, just working) but NO keystroke stacked behind its turn.
    assert out["ok"] is True and sent == [] and "working" in out["result"]


def test_nudge_no_live_session_reports_honestly(app, monkeypatch):
    out, sent = _nudge(app, monkeypatch, None)
    # The failure this whole session was about: never report a hollow success.
    assert out["ok"] is False and sent == [] and "no live session" in out["result"].lower()


def test_nudge_unknown_action_404(app):
    import pytest as _pytest
    from fastapi import HTTPException
    with _pytest.raises(HTTPException) as ei:
        asyncio.run(service_action("image_gen", "explode", _req(app)))
    assert ei.value.status_code == 404
