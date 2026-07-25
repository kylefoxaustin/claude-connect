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
