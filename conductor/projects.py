"""Project Layer state Conductor reads from ``~/.claude/bus-state/coord/projects/``.

Slice 1 (docs/PROJECT_LAYER.md §10.1) is the project object + nomination handshake + the plan
gate — and the gate's operator side lives *here*: the lead submits a plan, it lands in
``plan_review``, and Conductor surfaces it so **Kyle approves it from his phone** rather than a
terminal. This module is read-only over the JSON `bus.sh project` writes; the approve/revise
actions shell back out to `bus.sh project` (main.py), the same one-writer discipline the push gate
and services use — Conductor never mutates coordination state directly.

The rich DAG/members/spend view is slice 4; here we read the record and flag the one thing that
needs a human: **a plan awaiting approval.**
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# A dispatched job whose ORDER hasn't moved in this long is stalled. Chosen because a real job
# either gets claimed within a working session or nobody is coming — measured on the live
# ieee-paper project, where two orders sat PLACED for 24 DAYS with nothing watching them.
_STALL_HOURS = 24.0
_QUIET_MULTIPLE = 3.0        # a CLAIMED/COOKING order gets more rope than an unclaimed one


def _load(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _deps_done(job: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    return all(by_id.get(d, {}).get("state") == "done" for d in job.get("deps", []))


def _stall_for(order: dict[str, Any], age_h: float) -> str | None:
    """Classify a dispatched job's order as stalled, or None if it's moving.

    The DAG only advances a job when its order reaches CLOSED — the requester accepting, which is
    right, because a producer must never grade its own delivery. But that means a DELIVERED order is
    parked on a human/lead decision, and until now NOTHING surfaced it: the live ieee-paper project
    had a delivery waiting 24 days while the project reported ``needs: None``.
    """
    st = (order.get("state") or "").upper()
    if st == "DELIVERED":
        return "awaiting-acceptance"      # the requester must accept; blocked on a decision
    if st == "REJECTED":
        return "rejected-awaiting-revise"
    if st == "PLACED" and age_h >= _STALL_HOURS:
        return "never-claimed"            # the assignee never picked it up
    if st in ("CLAIMED", "COOKING") and age_h >= _STALL_HOURS * _QUIET_MULTIPLE:
        return "claimed-but-quiet"
    return None


def annotate_jobs(p: dict[str, Any], coord_root: Path | None = None,
                  now: float | None = None) -> dict[str, Any]:
    """Compute per-job readiness (ready/blocked/dispatched/done) + DAG counts, matching bus.sh's
    own readiness rule. ``in_flight`` (dispatched, not yet done) is what the concurrency throttle
    caps; ``ready`` is what the lead can dispatch right now.

    When ``coord_root`` is given, each dispatched job is also joined to its ORDER so a stalled job
    can be seen: ``order_state``, ``order_age_hours`` and ``stall`` (see ``_stall_for``). The job
    record itself carries no dispatch timestamp — that is written by ``bus.sh`` — so age is derived
    from the order's own ``updated``/``created``, which is the timestamp that actually moves when
    the work does.
    """
    now = time.time() if now is None else now
    jobs = p.get("jobs") or []
    by_id = {j["id"]: j for j in jobs}
    counts = {"total": len(jobs), "ready": 0, "blocked": 0, "dispatched": 0, "done": 0}
    for j in jobs:
        st = j.get("state")
        if st == "done":
            r = "done"
        elif st == "dispatched":
            r = "dispatched"
        elif _deps_done(j, by_id):
            r = "ready"
        else:
            r = "blocked"
        j["readiness"] = r
        j["blocking_deps"] = ([d for d in j.get("deps", []) if by_id.get(d, {}).get("state") != "done"]
                              if r == "blocked" else [])
        counts[r] = counts.get(r, 0) + 1
        j.pop("stall", None)
        if r == "dispatched" and coord_root is not None and j.get("order_id"):
            o = _load(coord_root / "orders" / f"{j['order_id']}.json")
            if o:
                stamp = o.get("updated") or o.get("created") or 0
                age_h = max(0.0, (now - float(stamp)) / 3600.0) if stamp else 0.0
                j["order_state"] = o.get("state")
                j["order_age_hours"] = round(age_h, 1)
                st = _stall_for(o, age_h)
                if st:
                    j["stall"] = st
    p["job_counts"] = counts
    # Stalled dispatched jobs, worst-first. Empty list (not absent) so the UI can render "none".
    p["stalls"] = sorted(
        [{"id": j["id"], "stall": j["stall"], "to": j.get("to"),
          "order_state": j.get("order_state"), "order_age_hours": j.get("order_age_hours")}
         for j in jobs if j.get("stall")],
        key=lambda d: -(d.get("order_age_hours") or 0),
    )
    p["in_flight"] = counts["dispatched"]          # in-flight worker jobs, for the throttle
    p["ready_jobs"] = [j["id"] for j in jobs if j.get("readiness") == "ready"]
    return p


def _needs_operator(p: dict[str, Any]) -> str | None:
    """The one operator-actionable signal per project, or None. A plan awaiting approval is the
    only thing that hard-blocks the project on Kyle (Gate #1); a stalled nomination (declined with
    no re-nomination) is advisory — worth showing, not a page."""
    state = p.get("state")
    if state == "plan_review" and p.get("plan_status") == "submitted":
        return "approve-plan"
    if state == "draft" and p.get("nominations") and p.get("lead") is None:
        # a nominee declined or suggested another and the lead seat is empty — Kyle re-nominates.
        return "renominate"
    if state == "nominating":
        return "awaiting-nominee"      # the ball is in the nominee's court, but Kyle should see it
    # A project whose in-flight work has stopped moving. Not strictly Kyle's ACTION — a delivery is
    # the lead's to accept, an unclaimed order is the assignee's to take — but when nobody has moved
    # it for a day, he is the only one who can nudge, reassign or close it. Silence here is what let
    # ieee-paper sit with three stalled jobs for 24 days reporting ``needs: None``.
    if p.get("stalls"):
        return "stalled"
    return None


def read_projects(coord_root: Path) -> list[dict[str, Any]]:
    """Every project, newest-created first, each annotated with ``needs`` (see ``_needs_operator``)
    and a compact ``last_nomination`` so the UI can render the handshake without the full log."""
    pdir = coord_root / "projects"
    if not pdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(pdir.glob("*.json")):
        p = _load(f)
        if not p or "id" not in p:
            continue
        noms = p.get("nominations") or []
        annotate_jobs(p, coord_root)              # readiness + DAG counts + order-derived stalls
        es = p.get("escalations") or []           # decision shield (slice 3)
        p["open_kyle_escalations"] = sum(1 for e in es if e.get("state") == "open" and e.get("target") == "kyle")
        p["open_lead_escalations"] = sum(1 for e in es if e.get("state") == "open" and e.get("target") == "lead")
        p["needs"] = _needs_operator(p)
        p["last_nomination"] = noms[-1] if noms else None
        # Don't ship the whole plan text in the list payload — only whether one exists + its size.
        plan = p.get("plan")
        p["has_plan"] = bool(plan)
        p["plan_chars"] = len(plan) if isinstance(plan, str) else 0
        out.append(p)
    out.sort(key=lambda x: x.get("created_epoch", 0), reverse=True)
    return out


def projects_needing_operator(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The subset with a non-None ``needs`` — what the ops console/decision surface should raise."""
    return [p for p in projects if p.get("needs")]


def total_in_flight(projects: list[dict[str, Any]]) -> int:
    """Jobs dispatched-but-not-done across ALL projects — the fleet-global concurrency the throttle
    caps (§5b: the cap is global, since every project competes for the same overloaded ceiling)."""
    return sum(p.get("in_flight", 0) for p in projects)


def open_escalations(projects: list[dict[str, Any]], target: str | None = "kyle") -> list[dict[str, Any]]:
    """Open escalations across all projects, each enriched with its project id + goal. Default
    ``target='kyle'`` returns only the ones that are Kyle's to decide (the denylist + severity hatch,
    plus any the lead-timeout auto-escalated) — what the phone decision queue raises. ``target=None``
    returns all open ones (for the desktop view)."""
    out: list[dict[str, Any]] = []
    for p in projects:
        for e in p.get("escalations") or []:
            if e.get("state") != "open":
                continue
            if target is not None and e.get("target") != target:
                continue
            out.append({**e, "project": p["id"], "project_goal": p.get("goal", "")})
    # oldest first — a decision that has waited longest should surface first.
    out.sort(key=lambda e: e.get("created", 0))
    return out
