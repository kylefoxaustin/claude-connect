"""Tests for shared-resource lease handling: tag matching + orphan detection.

The tag-matching case is a regression guard. Conductor stores a session's tag
bracketed (``"[other:api]"``) while ``bus.sh`` writes lease owners bare
(``"other:api"``); comparing them directly silently never matches, which both
flagged every live owner as an orphan *and* stopped the offer wake from ever
finding a session to inject into.
"""

from __future__ import annotations

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
