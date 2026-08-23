"""Project Layer — Conductor's read/classify side (conductor/projects.py).

bus.sh owns the state machine (tests/test-project.sh proves it); here we prove Conductor reads the
record correctly and raises the ONE thing that needs a human: a plan awaiting approval (Gate #1).
The rich DAG view is slice 4 — this is the operator-signal layer.
"""

from __future__ import annotations

import json
from pathlib import Path

from conductor.projects import (
    annotate_jobs,
    open_escalations,
    projects_needing_operator,
    read_projects,
    total_in_flight,
)


def _write(root: Path, rec: dict) -> None:
    pdir = root / "projects"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"{rec['id']}.json").write_text(json.dumps(rec), encoding="utf-8")


def _proj(pid: str, **over) -> dict:
    base = {"id": pid, "goal": "g", "created_by": "operator", "created_epoch": 100,
            "state": "draft", "lead": None, "lead_status": "unassigned", "nominations": [],
            "plan": None, "plan_status": "none", "plan_notes": None,
            "jobs": [], "issues": [], "log": []}
    base.update(over)
    return base


def test_no_dir_is_empty(tmp_path: Path):
    assert read_projects(tmp_path) == []


def test_plan_review_needs_approval(tmp_path: Path):
    _write(tmp_path, _proj("p1", state="plan_review", plan_status="submitted",
                           lead="95emulator", lead_status="accepted", plan="A -> B -> C"))
    ps = read_projects(tmp_path)
    assert len(ps) == 1
    assert ps[0]["needs"] == "approve-plan"
    assert ps[0]["has_plan"] is True and ps[0]["plan_chars"] == len("A -> B -> C")
    assert projects_needing_operator(ps) == ps


def test_active_project_needs_nothing(tmp_path: Path):
    _write(tmp_path, _proj("p2", state="active", plan_status="approved",
                           lead="95emulator", lead_status="accepted", plan="x"))
    ps = read_projects(tmp_path)
    assert ps[0]["needs"] is None
    assert projects_needing_operator(ps) == []


def test_nominating_is_advisory(tmp_path: Path):
    _write(tmp_path, _proj("p3", state="nominating", lead="95emulator", lead_status="nominated"))
    ps = read_projects(tmp_path)
    assert ps[0]["needs"] == "awaiting-nominee"


def test_declined_empty_seat_asks_for_renomination(tmp_path: Path):
    _write(tmp_path, _proj("p4", state="draft", lead=None,
                           nominations=[{"session": "image_gen", "response": "declined",
                                         "reason": "gpu busy", "ts": 1}]))
    ps = read_projects(tmp_path)
    assert ps[0]["needs"] == "renominate"
    assert ps[0]["last_nomination"]["response"] == "declined"


def test_submitted_but_not_plan_review_is_not_approvable(tmp_path: Path):
    # defensive: only plan_review + submitted counts, not a stray plan_status on a wrong state
    _write(tmp_path, _proj("p5", state="planning", plan_status="submitted", lead="x",
                           lead_status="accepted"))
    assert read_projects(tmp_path)[0]["needs"] is None


def test_newest_created_first_and_bad_json_skipped(tmp_path: Path):
    _write(tmp_path, _proj("old", created_epoch=100))
    _write(tmp_path, _proj("new", created_epoch=200))
    (tmp_path / "projects" / "junk.json").write_text("{not json", encoding="utf-8")
    ps = read_projects(tmp_path)
    assert [p["id"] for p in ps] == ["new", "old"]   # junk skipped, newest first


# --- slice 2: the DAG annotation + throttle ----------------------------------
def _job(jid, state="planned", deps=None, order_id=None):
    return {"id": jid, "to": "x", "desc": "", "deps": deps or [], "size": "",
            "accept": "", "path": "/d", "files": ["f"], "state": state, "order_id": order_id}


def test_dag_readiness():
    p = _proj("p", state="active", jobs=[
        _job("A"),                              # no deps -> ready
        _job("B", deps=["A"]),                  # A not done -> blocked
        _job("C", state="dispatched", order_id="o1"),
        _job("D", state="done"),
    ])
    annotate_jobs(p)
    by = {j["id"]: j for j in p["jobs"]}
    assert by["A"]["readiness"] == "ready"
    assert by["B"]["readiness"] == "blocked" and by["B"]["blocking_deps"] == ["A"]
    assert by["C"]["readiness"] == "dispatched"
    assert by["D"]["readiness"] == "done"
    assert p["job_counts"] == {"total": 4, "ready": 1, "blocked": 1, "dispatched": 1, "done": 1}
    assert p["in_flight"] == 1
    assert p["ready_jobs"] == ["A"]


def test_dependent_unblocks_when_dep_done():
    p = _proj("p", state="active", jobs=[_job("A", state="done"), _job("B", deps=["A"])])
    annotate_jobs(p)
    assert {j["id"]: j["readiness"] for j in p["jobs"]} == {"A": "done", "B": "ready"}


def test_total_in_flight_is_fleet_global(tmp_path: Path):
    _write(tmp_path, _proj("p1", state="active", jobs=[_job("A", state="dispatched", order_id="o")]))
    _write(tmp_path, _proj("p2", state="active",
                           jobs=[_job("B", state="dispatched", order_id="o"),
                                 _job("C", state="done")]))
    ps = read_projects(tmp_path)
    assert total_in_flight(ps) == 2      # one in p1, one in p2 (the done job doesn't count)


# --- slice 3: the decision shield -------------------------------------------
def _esc(eid, target="kyle", state="open", created=100, **over):
    e = {"id": eid, "raised_by": "qualcomm", "job": "", "question": f"q{eid}", "why": "",
         "options": [], "recommendation": "", "severity": "", "deny": "", "target": target,
         "state": state, "answer": "", "answered_by": "", "answered_epoch": 0, "created": created}
    e.update(over)
    return e


def test_open_escalations_kyle_only_by_default(tmp_path: Path):
    _write(tmp_path, _proj("p", state="active", escalations=[
        _esc("k1", target="kyle", deny="scope"),
        _esc("l1", target="lead"),                 # lead-bound -> not Kyle's
        _esc("k2", target="kyle", state="answered"),  # answered -> gone
    ]))
    ps = read_projects(tmp_path)
    kyle = open_escalations(ps, target="kyle")
    assert [e["id"] for e in kyle] == ["k1"]
    assert kyle[0]["project"] == "p"               # enriched with the project id
    # target=None returns ALL open (for the desktop): k1 + l1, not the answered k2
    assert sorted(e["id"] for e in open_escalations(ps, target=None)) == ["k1", "l1"]


def test_open_escalations_oldest_first(tmp_path: Path):
    _write(tmp_path, _proj("p", state="active", escalations=[
        _esc("new", created=200), _esc("old", created=100)]))
    ps = read_projects(tmp_path)
    assert [e["id"] for e in open_escalations(ps)] == ["old", "new"]


def test_escalation_counts_annotated(tmp_path: Path):
    _write(tmp_path, _proj("p", state="active", escalations=[
        _esc("k1", target="kyle"), _esc("l1", target="lead"), _esc("l2", target="lead"),
        _esc("done1", target="kyle", state="answered")]))
    p = read_projects(tmp_path)[0]
    assert p["open_kyle_escalations"] == 1
    assert p["open_lead_escalations"] == 2


# --------------------------------------------------------------------------
# Stall detection (docs/PROJECT_LAYER.md — the gap found 2026-08-19)
#
# The DAG only advances a job when its order reaches CLOSED — the requester accepting, which is
# correct, since a producer must never grade its own delivery. But that meant a DELIVERED order was
# parked on a decision that NOTHING surfaced: the live ieee-paper project had one delivery waiting
# 24 days and two orders never claimed, while reporting `needs: None`.
# --------------------------------------------------------------------------

import json as _json
import time as _time
from conductor.projects import annotate_jobs, read_projects, _stall_for, _STALL_HOURS


def _sorder(tmp_path, oid, state, age_hours, now):
    d = tmp_path / "orders"; d.mkdir(exist_ok=True)
    stamp = now - age_hours * 3600
    (d / f"{oid}.json").write_text(_json.dumps({
        "order_id": oid, "state": state, "created": stamp, "updated": stamp,
        "requester": "lead", "service": "worker",
    }))


def _sproj(jobs):
    return {"id": "p1", "state": "active", "lead": "lead", "jobs": jobs}


def test_delivered_order_is_awaiting_acceptance_immediately():
    """A delivery is blocked on a decision from the moment it lands — no grace period."""
    assert _stall_for({"state": "DELIVERED"}, 0.0) == "awaiting-acceptance"
    assert _stall_for({"state": "REJECTED"}, 0.0) == "rejected-awaiting-revise"


def test_placed_order_gets_a_grace_period_then_stalls():
    assert _stall_for({"state": "PLACED"}, _STALL_HOURS - 1) is None
    assert _stall_for({"state": "PLACED"}, _STALL_HOURS + 1) == "never-claimed"


def test_claimed_order_gets_more_rope_than_an_unclaimed_one():
    """Somebody picked it up — that deserves longer before we call it stalled."""
    assert _stall_for({"state": "CLAIMED"}, _STALL_HOURS + 1) is None
    assert _stall_for({"state": "COOKING"}, _STALL_HOURS * 3 + 1) == "claimed-but-quiet"


def test_moving_orders_are_never_flagged():
    for st in ("CONFIRMED", "CLOSED", ""):
        assert _stall_for({"state": st}, 9999) is None


def test_annotate_joins_the_order_and_lists_stalls(tmp_path):
    now = _time.time()
    _sorder(tmp_path, "o-del", "DELIVERED", 600, now)     # 25 days
    _sorder(tmp_path, "o-new", "PLACED", 1, now)          # 1 hour — fine
    _sorder(tmp_path, "o-old", "PLACED", 100, now)        # 4 days — stalled
    p = _sproj([
        {"id": "a", "state": "dispatched", "to": "w1", "order_id": "o-del", "deps": []},
        {"id": "b", "state": "dispatched", "to": "w2", "order_id": "o-new", "deps": []},
        {"id": "c", "state": "dispatched", "to": "w3", "order_id": "o-old", "deps": []},
        {"id": "d", "state": "done", "deps": []},
    ])
    annotate_jobs(p, tmp_path, now=now)
    stalls = {s["id"]: s["stall"] for s in p["stalls"]}
    assert stalls == {"a": "awaiting-acceptance", "c": "never-claimed"}, stalls
    assert p["stalls"][0]["id"] == "a", "worst (oldest) first"
    assert p["stalls"][0]["order_age_hours"] > 500
    assert "stall" not in p["jobs"][1], "a fresh order must not be flagged"


def test_annotate_without_coord_root_is_unchanged(tmp_path):
    """Callers that don't pass coord_root keep the old behaviour — no orders read, no stalls."""
    p = _sproj([{"id": "a", "state": "dispatched", "order_id": "o-x", "deps": []}])
    annotate_jobs(p)
    assert p["stalls"] == []
    assert p["in_flight"] == 1


def test_a_missing_order_file_does_not_crash_or_invent_a_stall(tmp_path):
    p = _sproj([{"id": "a", "state": "dispatched", "order_id": "nope", "deps": []}])
    annotate_jobs(p, tmp_path)
    assert p["stalls"] == []
    assert "order_state" not in p["jobs"][0]


def test_needs_operator_reports_stalled_but_never_over_the_plan_gate(tmp_path):
    now = _time.time()
    pdir = tmp_path / "projects"; pdir.mkdir()
    _sorder(tmp_path, "o-old", "PLACED", 100, now)
    base = {"id": "p1", "lead": "lead",
            "jobs": [{"id": "c", "state": "dispatched", "to": "w", "order_id": "o-old", "deps": []}]}

    (pdir / "p1.json").write_text(_json.dumps({**base, "state": "active"}))
    assert read_projects(tmp_path)[0]["needs"] == "stalled"

    # The plan gate HARD-blocks on Kyle, so it must still win over an advisory stall.
    (pdir / "p1.json").write_text(_json.dumps(
        {**base, "state": "plan_review", "plan_status": "submitted"}))
    assert read_projects(tmp_path)[0]["needs"] == "approve-plan"
