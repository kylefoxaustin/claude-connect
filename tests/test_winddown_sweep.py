"""Wind-down orchestration: the self-sweep bug, the PID fallback, the honest label, the re-nudge.

All four come from the first live shakedown (Kyle, 2026-08-05, ~32 sessions):

  * "Close idle" closed the MANAGING claude-connect session — it was idle at tap-time, because
    orchestrating a wind-down means sitting at a prompt, so the sweep ate its own operator.
  * Close rides keystroke injection, so sessions whose window couldn't be resolved could not be
    closed at all (~2 of 25 reachable). A PID fallback fixes that, but ONLY where an ack proves
    the work is already persisted.
  * "flushing" covered both "actively persisting" and "woken and did nothing" — a lie in the
    reassuring direction.
  * Un-acked sessions had to be re-tapped by hand, one at a time.
"""

from __future__ import annotations

import time
import types

import pytest

from conductor.main import _WD_RENUDGE_BACKOFF_S, AppState
from conductor.scanner import Status


def _session(tag, *, status=Status.IDLE, pid=1234, activity=0.0):
    return types.SimpleNamespace(
        tag=tag, status=status, pid=pid, terminal_pid=99,
        title=tag.strip("[]"), window_title=f"Project {tag.strip('[]')}",
        project_dir=f"/repo/{tag}", preview="", session_id=tag, last_activity_at=activity,
    )


@pytest.fixture
def state(monkeypatch, tmp_path):
    """An AppState with just enough wired up to exercise the wind-down paths."""
    st = AppState.__new__(AppState)
    st.coord_root = tmp_path
    st.sessions = {}
    st._wd_nudges = {}
    st._wd_nudged_at = {}
    st.settings = types.SimpleNamespace(
        bus=types.SimpleNamespace(autodeliver_exempt=["[other:claude-connect]"]),
    )
    st._has_open_picker = lambda r: False
    return st


def _wd(active_epoch=1000.0, initiator="[other:claude-connect]", acks=None):
    return {"active": {"initiator": initiator, "created": "now", "epoch": str(active_epoch)},
            "acks": acks or {}}


# ── the manager set ───────────────────────────────────────────────────────────────────────

def test_manager_set_includes_initiator_and_operator_console(state):
    m = state._winddown_managers(_wd(initiator="[other:orchestrator]"))
    assert "orchestrator" in m, "the session that called `shutdown begin` must never be swept"
    assert "claude-connect" in m, "the configured operator console must never be swept"


def test_manager_set_survives_a_wind_down_begun_from_the_phone(state):
    """A phone-initiated wind-down records no session initiator, so the operator console is the
    only thing standing between the sweep and the session driving it."""
    m = state._winddown_managers({"active": {"initiator": "", "epoch": "1"}, "acks": {}})
    assert m == {"claude-connect"}


# ── the self-sweep bug ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_close_idle_never_closes_the_managing_session(state, monkeypatch):
    """THE REGRESSION. The manager is idle and un-acked — exactly the sweep's target profile —
    and must be skipped anyway."""
    state.sessions = {"a": _session("[other:claude-connect]"), "b": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd())
    typed: list[str] = []
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: typed.append(kw["title"]) or True)
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_idle_stragglers()
    assert "other:worker" in typed, "the ordinary straggler should still be closed"
    assert "other:claude-connect" not in typed, "the sweep closed the session running it"
    assert any(s.get("why") == "manager" for s in res["skipped"])


@pytest.mark.asyncio
async def test_verified_close_also_spares_the_manager(state, monkeypatch):
    """Even WITH an ack: closing the driver mid-wind-down ends the wind-down."""
    state.sessions = {"a": _session("[other:claude-connect]")}
    monkeypatch.setattr("conductor.main.read_winddown",
                        lambda root: _wd(acks={"claude-connect": {"summary": "done"}}))
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: True)
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_wound_down()
    assert res["closed"] == []
    assert any(s.get("why") == "manager" for s in res["refused"])


# ── the PID fallback ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pid_fallback_closes_an_acked_session_whose_window_is_unreachable(state, monkeypatch):
    """The 2026-08-05 case: the window can't be resolved, so /exit can never land. An ACKED
    session has been checked against disk, so terminating it loses nothing."""
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown",
                        lambda root: _wd(acks={"worker": {"summary": "done"}}))
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: False)  # unreachable
    killed: list[str] = []
    monkeypatch.setattr(AppState, "_terminate_session",
                        lambda self, r: killed.append(r.tag) or True)
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_wound_down()
    assert killed == ["[other:worker]"]
    assert res["closed"] == ["[other:worker]"]


@pytest.mark.asyncio
async def test_idle_sweep_NEVER_falls_back_to_the_pid(state, monkeypatch):
    """THE SAFETY LINE. An un-acked session has proved nothing about its working tree, so a
    failed /exit must stay a failure. Kyle's choice was 'PID-kill only if acked'; the sweep is
    exactly the path where that condition does not hold."""
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd())
    monkeypatch.setattr("conductor.main.send_keys_to_session", lambda **kw: False)
    monkeypatch.setattr(AppState, "_terminate_session",
                        lambda self, r: pytest.fail("killed an un-acked session"))
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_idle_stragglers()
    assert res["closed"] == []
    assert any(s.get("why") == "close-failed" for s in res["skipped"])


def test_terminate_refuses_a_pid_that_is_not_claude(state, monkeypatch):
    """The wrapper shell SURVIVES claude's death (v2.27.2), so a recycled or wrapper pid is a
    stranger. Refuse rather than kill something we did not identify."""
    class _Proc:
        def __init__(self, pid): pass
        def name(self): return "bash"
        def terminate(self): pytest.fail("terminated a non-claude process")
        def wait(self, timeout=None): pass
    monkeypatch.setattr("conductor.main.psutil.Process", _Proc)
    assert state._terminate_session(_session("[other:worker]")) is False


def test_terminate_reports_failure_rather_than_escalating(state, monkeypatch):
    """No SIGKILL. 'Could not close' is a state Kyle can act on; a forced kill is not undoable."""
    import psutil as _ps

    class _Proc:
        def __init__(self, pid): pass
        def name(self): return "claude"
        def terminate(self): pass
        def wait(self, timeout=None): raise _ps.TimeoutExpired(timeout)
    monkeypatch.setattr("conductor.main.psutil.Process", _Proc)
    assert state._terminate_session(_session("[other:worker]")) is False


# ── the honest label ──────────────────────────────────────────────────────────────────────

def test_flushing_vs_idle_unacked_are_distinguished(state, monkeypatch):
    """"flushing" used to cover both. A session that has done nothing since the wind-down began
    needs a nudge; one that is actively persisting needs patience. Same word for both is the lie."""
    state.sessions = {
        "a": _session("[other:working]", activity=2000.0),   # moved since the wind-down began
        "b": _session("[other:silent]", activity=500.0),     # nothing since
    }
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd(active_epoch=1000.0))

    rows = {r["member"]: r["state"] for r in state._winddown_payload()["sessions"]}
    assert rows["working"] == "flushing"
    assert rows["silent"] == "idle-unacked"


def test_closable_counts_exclude_the_manager(state, monkeypatch):
    """The number on the button must equal what the button will do."""
    state.sessions = {"a": _session("[other:claude-connect]"), "b": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown",
                        lambda root: _wd(acks={"claude-connect": {}, "worker": {}}))
    p = state._winddown_payload()
    assert p["closable"] == 1


# ── the backing-off re-nudge ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_renudge_backs_off_and_then_stops(state, monkeypatch):
    """Bounded by construction: the backoff list's length IS the attempt cap, so this can never
    become the v2.26.1 /msg-check storm."""
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd())
    sent: list[str] = []

    async def _inject(self, rec, why):
        sent.append(why)
    monkeypatch.setattr(AppState, "_inject_msg_check", _inject)

    now = [10_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    await state._renudge_unacked()
    assert len(sent) == 1, "first nudge fires immediately"

    await state._renudge_unacked()
    assert len(sent) == 1, "a second nudge must wait out the backoff"

    for delay in _WD_RENUDGE_BACKOFF_S:
        now[0] += delay + 1
        await state._renudge_unacked()
    assert len(sent) == len(_WD_RENUDGE_BACKOFF_S), "exactly the cap, then silence"

    now[0] += 100_000
    await state._renudge_unacked()
    assert len(sent) == len(_WD_RENUDGE_BACKOFF_S), "exhausted — it is Kyle's call now"


@pytest.mark.asyncio
async def test_renudge_skips_busy_asking_and_manager(state, monkeypatch):
    state.sessions = {
        "a": _session("[other:claude-connect]"),
        "b": _session("[other:busy]", status=Status.ACTIVE),
        "c": _session("[other:asking]"),
        "d": _session("[other:ok]"),
    }
    state._has_open_picker = lambda r: r.tag == "[other:asking]"
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd())
    sent: list[str] = []

    async def _inject(self, rec, why):
        sent.append(rec.tag)
    monkeypatch.setattr(AppState, "_inject_msg_check", _inject)

    await state._renudge_unacked()
    assert sent == ["[other:ok]"]


@pytest.mark.asyncio
async def test_renudge_forgets_a_session_once_it_acks(state, monkeypatch):
    """A stale counter would keep a re-acked session permanently exhausted."""
    state.sessions = {"a": _session("[other:worker]")}
    state._wd_nudges = {"worker": 2}
    state._wd_nudged_at = {"worker": 1.0}
    monkeypatch.setattr("conductor.main.read_winddown",
                        lambda root: _wd(acks={"worker": {"summary": "done"}}))
    monkeypatch.setattr(AppState, "_inject_msg_check",
                        lambda self, rec, why: pytest.fail("nudged an acked session"))

    await state._renudge_unacked()
    assert "worker" not in state._wd_nudges


@pytest.mark.asyncio
async def test_renudge_state_is_cleared_when_the_winddown_ends(state, monkeypatch):
    state._wd_nudges = {"worker": 2}
    state._wd_nudged_at = {"worker": 1.0}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: {"active": None, "acks": {}})
    await state._renudge_unacked()
    assert state._wd_nudges == {} and state._wd_nudged_at == {}


async def _async(v):
    return v


# ── a wind-down marker SURVIVES A REBOOT ──────────────────────────────────────────────────
# Found live 2026-08-05: yesterday's wind-down was still `active` with 12 .done files while the
# fleet had since been rebooted and partly recovered. A session that did not exist when the order
# was given cannot have obeyed or ignored it — but on paper it was a straggler wearing a .done
# from its previous incarnation.

@pytest.mark.asyncio
async def test_a_relaunched_session_is_not_closed_on_its_previous_incarnations_ack(state, monkeypatch):
    """THE LIVE FOOTGUN: "Close wound-down" offered to close a freshly-recovered qualcomm using an
    ack written by the process it replaced."""
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown",
                        lambda root: _wd(active_epoch=1000.0, acks={"worker": {"summary": "old"}}))
    monkeypatch.setattr(AppState, "_proc_start_epoch", staticmethod(lambda pid: 5000.0))  # after
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: pytest.fail("closed a restarted session"))
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_wound_down()
    assert res["closed"] == []
    assert any(x.get("why") == "restarted" for x in res["refused"])


@pytest.mark.asyncio
async def test_a_relaunched_session_is_not_swept_as_a_straggler(state, monkeypatch):
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd(active_epoch=1000.0))
    monkeypatch.setattr(AppState, "_proc_start_epoch", staticmethod(lambda pid: 5000.0))
    monkeypatch.setattr("conductor.main.send_keys_to_session",
                        lambda **kw: pytest.fail("swept a restarted session"))
    monkeypatch.setattr(AppState, "_winddown_snapshot", lambda self: _async(None))

    res = await state.close_idle_stragglers()
    assert res["closed"] == []


@pytest.mark.asyncio
async def test_recovery_is_not_turned_into_a_second_shutdown(state, monkeypatch):
    """The nastiest consequence of the stale marker: the new auto-re-nudge would have told every
    session restored by ⟳ Fleet recovery to wind down again."""
    state.sessions = {"a": _session("[other:worker]")}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd(active_epoch=1000.0))
    monkeypatch.setattr(AppState, "_proc_start_epoch", staticmethod(lambda pid: 5000.0))
    monkeypatch.setattr(AppState, "_inject_msg_check",
                        lambda self, rec, why: pytest.fail("nudged a recovered session"))

    await state._renudge_unacked()


def test_a_session_that_predates_the_winddown_is_still_governed_by_it(state, monkeypatch):
    """The guard must not exempt the whole fleet — only genuinely newer processes."""
    state.sessions = {"a": _session("[other:worker]", activity=500.0)}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd(active_epoch=1000.0))
    monkeypatch.setattr(AppState, "_proc_start_epoch", staticmethod(lambda pid: 200.0))  # before
    rows = {r["member"]: r["state"] for r in state._winddown_payload()["sessions"]}
    assert rows["worker"] == "idle-unacked"


def test_unknown_process_start_degrades_to_the_old_behaviour(state, monkeypatch):
    """If /proc can't be read we must NOT silently exempt everything — that would quietly disable
    the wind-down rather than fail visibly."""
    state.sessions = {"a": _session("[other:worker]", activity=500.0)}
    monkeypatch.setattr("conductor.main.read_winddown", lambda root: _wd(active_epoch=1000.0))
    monkeypatch.setattr(AppState, "_proc_start_epoch", staticmethod(lambda pid: 0.0))
    rows = {r["member"]: r["state"] for r in state._winddown_payload()["sessions"]}
    assert rows["worker"] == "idle-unacked"
