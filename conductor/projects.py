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
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


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
