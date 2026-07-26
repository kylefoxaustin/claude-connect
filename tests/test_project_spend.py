"""Measured per-project token spend (Project Layer §5c). The meter attributes a project's spend from
the OUTPUT-token deltas of its members' sessions between dispatch and completion — measured, not
estimated. These pin the snapshot/freeze logic, the lead overhead, and the graceful cap."""

from __future__ import annotations

from conductor.project_spend import ProjectSpendMeter


def _proj(pid="p", state="active", lead="lead1", ceiling=0, jobs=None):
    return {"id": pid, "state": state, "lead": lead, "ceiling": ceiling, "jobs": jobs or [],
            "escalations": []}


def _job(jid, to, state="dispatched"):
    return {"id": jid, "to": to, "state": state}


def _tok(mapping):
    """token_of built from a {member: output_tokens} dict; missing member -> None (offline)."""
    return lambda m: mapping.get(m)


def test_no_ceiling_means_meter_only():
    m = ProjectSpendMeter()
    p = _proj(ceiling=0, jobs=[_job("a", "w1")])
    m.update([p], _tok({"lead1": 0, "w1": 100}))
    assert p["spend_pct"] is None
    assert p["over_budget"] is False and p["budget_warn"] is False


def test_job_spend_is_delta_from_dispatch_snapshot():
    m = ProjectSpendMeter()
    p = _proj(jobs=[_job("a", "w1")])
    # first sight: snapshot w1 at 1000 -> spend 0
    m.update([p], _tok({"lead1": 500, "w1": 1000}))
    assert p["jobs"][0]["spend"] == 0
    # w1 has since produced 300 more output tokens on the job
    m.update([p], _tok({"lead1": 500, "w1": 1300}))
    assert p["jobs"][0]["spend"] == 300
    assert p["spend"] == 300          # lead didn't move


def test_lead_overhead_counts():
    m = ProjectSpendMeter()
    p = _proj(jobs=[])
    m.update([p], _tok({"lead1": 2000}))      # snapshot lead at 2000
    m.update([p], _tok({"lead1": 2450}))      # lead burned 450 running the project
    assert p["lead_spend"] == 450
    assert p["spend"] == 450


def test_done_job_freezes_spend():
    m = ProjectSpendMeter()
    job = _job("a", "w1", state="dispatched")
    p = _proj(jobs=[job])
    m.update([p], _tok({"lead1": 0, "w1": 100}))     # snapshot 100
    m.update([p], _tok({"lead1": 0, "w1": 400}))     # spend 300 while dispatched
    job["state"] = "done"
    m.update([p], _tok({"lead1": 0, "w1": 900}))     # freeze at 300 (the 500 after is unrelated work)
    assert p["jobs"][0]["spend"] == 300
    m.update([p], _tok({"lead1": 0, "w1": 5000}))    # stays frozen
    assert p["jobs"][0]["spend"] == 300


def test_offline_worker_holds_last_known_spend():
    m = ProjectSpendMeter()
    p = _proj(jobs=[_job("a", "w1")])
    m.update([p], _tok({"lead1": 0, "w1": 100}))
    m.update([p], _tok({"lead1": 0, "w1": 250}))     # spend 150
    m.update([p], _tok({"lead1": 0}))                # w1 offline -> hold 150
    assert p["jobs"][0]["spend"] == 150


def test_pct_warn_and_over_budget_flags():
    m = ProjectSpendMeter()
    p = _proj(ceiling=1000, jobs=[_job("a", "w1")])
    m.update([p], _tok({"lead1": 0, "w1": 0}))       # snapshot 0
    m.update([p], _tok({"lead1": 0, "w1": 700}))     # 70% -> warn (WARN=65%)
    assert p["spend_pct"] == 70.0 and p["budget_warn"] is True and p["over_budget"] is False
    m.update([p], _tok({"lead1": 0, "w1": 1000}))    # 100% -> over
    assert p["over_budget"] is True


def test_would_exceed_holds_dispatch_near_the_cap():
    m = ProjectSpendMeter()
    p = _proj(ceiling=1000, jobs=[_job("a", "w1")])
    m.update([p], _tok({"w1": 0, "lead1": 0}))
    m.update([p], _tok({"w1": 500, "lead1": 0}))     # 50% -> dispatch allowed
    assert m.would_exceed(p)[0] is False
    m.update([p], _tok({"w1": 920, "lead1": 0}))     # 92% >= STOP(90%) -> held
    over, why = m.would_exceed(p)
    assert over is True and "budget cap" in why


def test_forget_drops_stale_projects():
    m = ProjectSpendMeter()
    p = _proj(pid="gone", jobs=[_job("a", "w1")])
    m.update([p], _tok({"w1": 100, "lead1": 0}))
    assert "gone" in m._marks
    m.update([], _tok({}))                            # project torn down
    assert "gone" not in m._marks
