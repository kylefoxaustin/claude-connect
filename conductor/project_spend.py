"""Measured per-project token spend (Project Layer §5c — the live meter + graceful cap).

The fleet's verdict on pre-run estimates was unanimous: **theater** (a "1 sprite, medium" job that
burned 1M+ tokens over five revise rounds). Cost is dominated by iteration depth, unknowable at t0.
So the only real control is a LIVE, MEASURED meter — and Conductor already tallies per-session
tokens, so it can attribute a project's spend from the output-token deltas of its members' sessions:

  * a JOB's cost = the assignee session's output tokens between the moment we first see the job
    dispatched and its completion (frozen at done, so the worker's later unrelated work doesn't
    keep counting);
  * the LEAD's own overhead (§5d — N workers' decisions serialized through one session fills its
    context and burns) = the lead session's output since the project went active.

Approximate — a worker does other things while a job is out — but MEASURED, not guessed, which is the
whole point. The unit is OUTPUT tokens (the stable "work done" measure; cache-reads dominate totals
and are ~free). The meter is Conductor-side state; the bus job record stays clean. The ceiling itself
lives on the project (`bus.sh project budget`) — the scope Kyle approves.
"""

from __future__ import annotations

from typing import Any, Callable


def _bare(t: str | None) -> str:
    t = (t or "").strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    if t.startswith("other:"):
        t = t[6:]
    return t.lower()


class ProjectSpendMeter:
    """Holds the dispatch-time token snapshots across scans and computes live spend per project.

    ``token_of(member) -> int | None`` returns a member's cumulative session output tokens, or None
    when it has no live session (offline). Call ``update(projects, token_of)`` each scan; it annotates
    each project in place with ``spend`` / ``lead_spend`` / ``spend_pct`` (None when no ceiling)."""

    #: stop admitting NEW dispatch once measured spend reaches this fraction of the ceiling — leaving
    #: headroom because in-flight jobs finish their uncancellable turn (tokens are spent, not reserved).
    STOP_FRACTION = 0.90
    #: surface a budget decision to Kyle at this fraction (§5c: warn at 60-70%, not 80% — by the time
    #: you see 80% + in-flight, you're past 100%).
    WARN_FRACTION = 0.65

    def __init__(self) -> None:
        # pid -> {"lead_start": int|None, "jobs": {jid: {"start": int, "frozen": int|None, "last": int}}}
        self._marks: dict[str, dict[str, Any]] = {}

    def forget(self, live_ids: set[str]) -> None:
        """Drop marks for projects that no longer exist (torn down), so state doesn't grow forever."""
        for pid in list(self._marks):
            if pid not in live_ids:
                del self._marks[pid]

    def update(self, projects: list[dict[str, Any]], token_of: Callable[[str], int | None]) -> None:
        self.forget({p["id"] for p in projects})
        for p in projects:
            m = self._marks.setdefault(p["id"], {"lead_start": None, "jobs": {}})

            # --- lead overhead (only accrues once the project is actively being run) ---
            lead = _bare(p.get("lead"))
            lead_spend = 0
            if p.get("state") == "active" and lead:
                lt = token_of(lead)
                if m["lead_start"] is None and lt is not None:
                    m["lead_start"] = lt
                if m["lead_start"] is not None:
                    cur = token_of(lead)
                    lead_spend = max(0, (cur if cur is not None else m["lead_start"]) - m["lead_start"])

            # --- per-job spend ---
            job_total = 0
            for j in p.get("jobs", []):
                who = _bare(j.get("to"))
                jm = m["jobs"].get(j["id"])
                st = j.get("state")
                if st == "dispatched":
                    cur = token_of(who)
                    if jm is None:
                        jm = {"start": cur if cur is not None else 0, "frozen": None, "last": 0}
                        m["jobs"][j["id"]] = jm
                    spend = max(0, (cur - jm["start"])) if cur is not None else jm.get("last", 0)
                    jm["last"] = spend
                elif st == "done":
                    if jm is None:
                        spend = 0                       # completed before we ever saw it dispatched
                    elif jm.get("frozen") is None:
                        # Freeze at the LAST delta measured WHILE dispatched — not the delta at this
                        # scan, which would fold in the worker's later unrelated work. (Scan-
                        # granularity: this misses at most one interval of on-job spend, which beats
                        # counting everything the worker does after the job closed.)
                        jm["frozen"] = jm.get("last", 0)
                        spend = jm["frozen"]
                    else:
                        spend = jm["frozen"]
                else:
                    spend = 0
                j["spend"] = spend
                job_total += spend

            spend = lead_spend + job_total
            ceiling = p.get("ceiling") or 0
            p["spend"] = spend
            p["lead_spend"] = lead_spend
            p["spend_pct"] = round(100 * spend / ceiling, 1) if ceiling else None
            p["over_budget"] = bool(ceiling and spend >= ceiling)
            p["budget_warn"] = bool(ceiling and spend >= ceiling * self.WARN_FRACTION)

    def would_exceed(self, project: dict[str, Any]) -> tuple[bool, str]:
        """Graceful cap: should a NEW dispatch be refused on budget grounds? Refuse once measured
        spend reaches STOP_FRACTION of the ceiling, so in-flight turns can still land under it."""
        ceiling = project.get("ceiling") or 0
        if not ceiling:
            return False, ""
        spend = project.get("spend") or 0
        if spend >= ceiling * self.STOP_FRACTION:
            return True, (
                f"budget cap: this project has spent {spend:,} of its {ceiling:,}-token ceiling "
                f"({project.get('spend_pct')}%). New dispatch is held so in-flight jobs finish under "
                f"the cap. Raise the ceiling (bus.sh project budget) or let it checkpoint.")
        return False, ""
