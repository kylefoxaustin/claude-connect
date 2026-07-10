"""Tests for shared-resource lease handling: tag matching + orphan detection.

The tag-matching case is a regression guard. Conductor stores a session's tag
bracketed (``"[other:api]"``) while ``bus.sh`` writes lease owners bare
(``"other:api"``); comparing them directly silently never matches, which both
flagged every live owner as an orphan *and* stopped the offer wake from ever
finding a session to inject into.
"""

from __future__ import annotations

import asyncio
import time
import types

import pytest

from conductor.main import AppState, _bare_tag
from conductor.models import Status
from conductor.settings import load_settings


def _session(tag, status=Status.ACTIVE):
    return types.SimpleNamespace(tag=tag, status=status)


def _lease(owner, offered=False):
    return {"owner": owner, "mode": "offer" if offered else "hard", "offered": offered}


@pytest.mark.parametrize(
    "conductor_tag, lease_owner",
    [("[other:qualcomm]", "other:qualcomm"), ("[backend]", "backend"), ("other:x", "other:x")],
)
def test_bare_tag_matches_bracketed_and_bare(conductor_tag, lease_owner):
    assert _bare_tag(conductor_tag) == _bare_tag(lease_owner)


def test_bare_tag_handles_none():
    assert _bare_tag(None) == ""


@pytest.fixture
def state():
    return AppState(load_settings())


def test_live_owner_is_not_flagged(state):
    """A bracketed session tag must match a bare lease owner (the regression)."""
    state.sessions = {"a": _session("[other:qualcomm]")}
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _lease("other:qualcomm")}]}
    state._annotate_orphans()
    lease = state.resources["resources"][0]["lease"]
    assert lease["owner_live"] is True
    assert lease["orphan_suspect"] is False


def test_offline_owner_flagged_only_after_threshold(state):
    state.sessions = {}
    state.resources = {"resources": [{"name": "orin-agx", "lease": _lease("other:ghost")}]}

    state._annotate_orphans()  # just noticed -> not yet a suspect
    lease = state.resources["resources"][0]["lease"]
    assert lease["owner_live"] is False
    assert lease["orphan_suspect"] is False

    # backdate the "missing since" past the threshold
    key = "orin-agx\x00other:ghost"
    state._owner_missing_since[key] = time.time() - state.settings.bus.orphan_flag_seconds - 1
    state.resources = {"resources": [{"name": "orin-agx", "lease": _lease("other:ghost")}]}
    state._annotate_orphans()
    assert state.resources["resources"][0]["lease"]["orphan_suspect"] is True


def test_ended_session_does_not_count_as_live(state):
    state.sessions = {"a": _session("[other:zombie]", Status.ENDED)}
    state.resources = {"resources": [{"name": "gpu", "lease": _lease("other:zombie")}]}
    state._annotate_orphans()
    assert state.resources["resources"][0]["lease"]["owner_live"] is False


def test_offers_are_skipped(state):
    """An offer auto-passes on its own; don't nag about its owner being offline."""
    state.sessions = {}
    state.resources = {"resources": [{"name": "gpu", "lease": _lease("other:ghost", offered=True)}]}
    state._annotate_orphans()
    assert "orphan_suspect" not in state.resources["resources"][0]["lease"]


def test_missing_since_is_pruned_when_lease_disappears(state):
    state.sessions = {}
    state._owner_missing_since["stale\x00x"] = time.time()
    state.resources = {"resources": []}
    state._annotate_orphans()
    assert state._owner_missing_since == {}


# --- waking an idle holder when the watchdog nudges it ------------------------
# The nudge is a bus message, and bus messages only surface through a session's
# per-prompt hook — so the idle holder it's aimed at never reads it. Conductor
# injects /msg-check to close that loop.

def _wakeable_session(status=Status.IDLE):
    return types.SimpleNamespace(
        tag="[other:qualcomm]", status=status, pid=1, terminal_pid=2, title="t", window_title="w"
    )


def _nudged_lease(nudged=100, idle_since=100, offered=False):
    return {
        "owner": "other:qualcomm", "mode": "hard", "offered": offered,
        "nudged_epoch": nudged, "idle_since_epoch": idle_since,
    }


def _run_nudge_wake(state, monkeypatch):
    calls = []
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: calls.append(kw) or True)
    asyncio.run(state._wake_nudged_owners())
    return calls


def test_idle_owner_is_woken_once_per_idle_episode(state, monkeypatch):
    state.sessions = {"q": _wakeable_session()}
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _nudged_lease()}]}
    assert len(_run_nudge_wake(state, monkeypatch)) == 1
    # same episode -> no repeat wake (never spam focus on the 20m re-nudge cadence)
    assert len(_run_nudge_wake(state, monkeypatch)) == 0
    # a NEW idle episode (watchdog cleared + re-set idle_since) -> wake again
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _nudged_lease(500, 500)}]}
    assert len(_run_nudge_wake(state, monkeypatch)) == 1


@pytest.mark.parametrize("status", [Status.ACTIVE, Status.WARM])
def test_busy_owner_is_never_interrupted(state, monkeypatch, status):
    state.sessions = {"q": _wakeable_session(status)}
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _nudged_lease()}]}
    assert _run_nudge_wake(state, monkeypatch) == []
    assert state._nudge_woken == set()  # not marked -> retried once it goes quiet


def test_no_wake_before_the_watchdog_has_nudged(state, monkeypatch):
    state.sessions = {"q": _wakeable_session()}
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _nudged_lease(nudged=None)}]}
    assert _run_nudge_wake(state, monkeypatch) == []


def test_dead_owner_is_left_to_the_orphan_path(state, monkeypatch):
    state.sessions = {}
    state.resources = {"resources": [{"name": "iq9-evk", "lease": _nudged_lease()}]}
    assert _run_nudge_wake(state, monkeypatch) == []


# --- activity-as-heartbeat ----------------------------------------------------
# A remote board has no telemetry, so "idle" means "no /keep". But a Claude deep in
# a long build never stops to /keep, and the busy guard rightly won't interrupt it
# to say so — so a working holder's board looked abandoned. Conductor heartbeats for
# a demonstrably-busy owner. A *quiet* owner is left to look idle, honestly.

def _board(tmp_path, name, owner, last_active_age, smi=None):
    d = tmp_path / name
    d.mkdir(exist_ok=True)
    now = int(time.time())
    (d / "lease").write_text(
        f"owner={owner}\nmode=hard\nexpires_epoch={now + 9000}\n"
        f"last_active_epoch={now - last_active_age}\nqueue=\n"
    )
    return {"name": name, "smi": smi,
            "lease": {"owner": owner, "mode": "hard", "offered": False,
                      "last_active_epoch": now - last_active_age, "idle": last_active_age}}


def _last_active(tmp_path, name):
    for ln in (tmp_path / name / "lease").read_text().splitlines():
        if ln.startswith("last_active_epoch="):
            return int(ln.split("=", 1)[1])
    return 0


def test_busy_owner_gets_a_heartbeat(state, tmp_path):
    state.res_root = tmp_path
    state.sessions = {"o": _wakeable_session(Status.WARM)}
    state.resources = {"resources": [_board(tmp_path, "orin-agx", "other:qualcomm", 9000)]}
    state._refresh_active_leases()
    assert int(time.time()) - _last_active(tmp_path, "orin-agx") < 5
    assert state.resources["resources"][0]["lease"]["idle"] == 0  # broadcast payload is truthful


def test_quiet_owner_is_left_looking_idle(state, tmp_path):
    state.res_root = tmp_path
    state.sessions = {"o": _wakeable_session(Status.IDLE)}
    state.resources = {"resources": [_board(tmp_path, "iq9-evk", "other:qualcomm", 9000)]}
    state._refresh_active_leases()
    assert int(time.time()) - _last_active(tmp_path, "iq9-evk") > 8000


def test_gpu_is_excluded_it_has_real_telemetry(state, tmp_path):
    state.res_root = tmp_path
    state.sessions = {"o": _wakeable_session(Status.ACTIVE)}
    state.resources = {"resources": [_board(tmp_path, "gpu", "other:qualcomm", 9000, smi={"util": 3})]}
    state._refresh_active_leases()
    assert int(time.time()) - _last_active(tmp_path, "gpu") > 8000


def test_heartbeat_is_throttled(state, tmp_path):
    state.res_root = tmp_path
    state.sessions = {"o": _wakeable_session(Status.WARM)}
    state.resources = {"resources": [_board(tmp_path, "imx95-frdm", "other:qualcomm", 5)]}
    before = _last_active(tmp_path, "imx95-frdm")
    state._refresh_active_leases()
    assert _last_active(tmp_path, "imx95-frdm") == before  # < _HEARTBEAT_MIN_AGE, no rewrite


def test_dead_owner_gets_no_heartbeat(state, tmp_path):
    """Otherwise Conductor would keep an abandoned lease looking alive forever."""
    state.res_root = tmp_path
    state.sessions = {}
    state.resources = {"resources": [_board(tmp_path, "orin-agx", "other:ghost", 9000)]}
    state._refresh_active_leases()
    assert int(time.time()) - _last_active(tmp_path, "orin-agx") > 8000
