#!/usr/bin/env python3
"""Evidence harvest — mine the objective record for the paper's evaluation RQs (docs/PAPER.md §V).

The thesis is evaluated by a longitudinal deployment case study, and most of the evidence already
exists in the record: the git history (mechanism-landing cutpoints, failure modes closed) and the
cross-session bus log (coordination volume, directed vs broadcast mail). This pulls the OBJECTIVE
metrics into one structured dataset (and flags the ones that still need human/agent CODING —
classifying a defect as bystander-found, a message as a courier event — which no script can decide).

    python scripts/evidence-harvest.py                 # human summary
    python scripts/evidence-harvest.py --json           # structured dataset (for the paper tables)
    python scripts/evidence-harvest.py --bus DIR        # bus-log dir (default ~/Documents/claude-bus)

Read-only. Chain of evidence: git history + bus logs, triangulated (Runeson & Höst case-study rigor).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HDR = re.compile(r'^## (\d{4})-(\d{2})-\d{2} \d{2}:\d{2}(?::\d{2})? \[([^\]]+)\]\s*$')
TO = re.compile(r'\bto:(\S+)')


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(REPO), *args],
                           capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def git_evidence() -> dict:
    """Deployment window, commit mix (feat=built / fix=failure-modes-closed / docs), and the tag
    timeline (version releases = the before/after cutpoints RQ1 needs)."""
    dates = [ln for ln in _git("log", "--reverse", "--format=%cs").splitlines() if ln]
    window = {"first": dates[0] if dates else None, "last": dates[-1] if dates else None,
              "commits": len(dates)}
    kinds = Counter()
    fixes: list[str] = []
    for ln in _git("log", "--format=%s").splitlines():
        m = re.match(r'^(feat|fix|docs|test|refactor|chore)(\([^)]*\))?[:!]', ln)
        k = m.group(1) if m else "other"
        kinds[k] += 1
        if k == "fix":                      # each fix ≈ a failure mode closed (RQ2/RQ3 candidate)
            fixes.append(ln)
    tags = []
    for t in _git("tag", "--sort=creatordate", "--format=%(refname:short)\t%(creatordate:short)").splitlines():
        parts = t.split("\t")
        if len(parts) == 2:
            tags.append({"tag": parts[0], "date": parts[1]})
    return {"window": window, "commit_kinds": dict(kinds),
            "failure_fixes_count": len(fixes), "failure_fixes": fixes,
            "mechanism_landings": tags, "mechanism_landing_count": len(tags)}


def _concentration(per_sender: Counter) -> dict:
    """Gini + cumulative-share of the sender distribution (division of labour), 'system' excluded.
    The MEASURED instrument behind draft §V's 'spread but with a real head, not a power law' claim —
    so that number is produced by this script, not hand-asserted (panel fix B2)."""
    vals = sorted(v for s, v in per_sender.items() if s != "system")
    n, tot = len(vals), sum(vals)
    if n == 0 or tot == 0:
        return {}
    cum = sum(i * v for i, v in enumerate(vals, 1))          # vals ascending
    gini = (2 * cum) / (n * tot) - (n + 1) / n
    desc = sorted(vals, reverse=True)
    run = 0
    s50 = s80 = None
    for i, v in enumerate(desc, 1):
        run += v
        if s50 is None and run >= tot * 0.5:
            s50 = i
        if s80 is None and run >= tot * 0.8:
            s80 = i
    return {
        "n_senders": n,
        "total_msgs_excl_system": tot,
        "gini": round(gini, 3),
        "top1_share": round(desc[0] / tot, 3),
        "top3_share": round(sum(desc[:3]) / tot, 3),
        "top5_share": round(sum(desc[:5]) / tot, 3),
        "senders_for_50pct": s50,
        "senders_for_80pct": s80,
    }


def bus_evidence(bus_dir: Path) -> dict:
    """Coordination volume from the bus: total messages, per-sender, directed vs broadcast (RQ1 —
    directed auto-delivered mail is the courier-eliminated proxy), and monthly throughput."""
    files = sorted(bus_dir.glob("messages*.md"))
    per_sender = Counter()
    by_month = Counter()
    directed = broadcast = announcement = 0     # ≤4 recipients=directed, >4=announcement, none=broadcast
    participants = set()
    total = 0
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        cur_sender = None
        pending_addr = False
        for ln in lines:
            m = HDR.match(ln)
            if m:
                total += 1
                yr, mo, sender = m.group(1), m.group(2), m.group(3)
                per_sender[sender] += 1
                by_month[f"{yr}-{mo}"] += 1
                if sender != "system":
                    participants.add(sender)
                cur_sender = sender
                pending_addr = True
                continue
            if pending_addr and ln.strip():     # first non-blank body line carries addressing
                pending_addr = False
                head = ln.split("—", 1)[0]
                tos = TO.findall(head)
                if ln.strip().startswith("@to "):
                    tos = re.findall(r'\[([^\]]+)\]', ln)
                if not tos:
                    broadcast += 1
                elif len(tos) <= 4:
                    directed += 1
                else:
                    announcement += 1
    return {
        "log_files": [f.name for f in files],
        "total_messages": total,
        "unique_participants": len(participants),
        "participants": sorted(participants),
        "by_sender_top": per_sender.most_common(20),
        "concentration": _concentration(per_sender),
        "by_month": dict(sorted(by_month.items())),
        "addressing": {"directed_le4": directed, "broadcast": broadcast,
                       "announcement_gt4": announcement},
        "directed_share": round(directed / total, 3) if total else 0.0,
    }


NEEDS_CODING = {
    "RQ1_autonomy": "Directed-mail volume below is the courier-eliminated PROXY; true courier "
                    "events (a human relaying by hand) need coding from the operator's own record.",
    "RQ2_robustness": "fix-commit count is a proxy for failure-modes-closed; classify each as "
                      "coordination vs. non-coordination, and pair the load-bearing ones with an "
                      "ablation (disable mechanism → failure returns).",
    "RQ3_defect_discovery": "For each fix, code author-found vs. bystander-found (needs the review "
                            "threads + FAILURE_MODES.md — no script can decide this).",
    "RQ4_convergence": "Count independent re-derivations of a mechanism/finding (rule-of-three); "
                       "the PROJECT_LAYER 4-reviewer convergence is a worked example — code it.",
    "RQ5_baseline": "Design + run one task under orchestrator-vs-substrate; not in the passive record.",
}


def _human(n: int) -> str:
    return f"{n:,}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Harvest paper-evaluation evidence from the record.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--bus", default=os.path.expanduser("~/Documents/claude-bus"))
    args = ap.parse_args()

    data = {
        "git": git_evidence(),
        "bus": bus_evidence(Path(args.bus)),
        "needs_coding": NEEDS_CODING,
    }
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    g, b = data["git"], data["bus"]
    w = g["window"]
    print("EVIDENCE HARVEST — objective backbone for docs/PAPER.md §V\n")
    print(f"Deployment window : {w['first']} → {w['last']}  ({_human(w['commits'])} commits)")
    print(f"Mechanism landings: {g['mechanism_landing_count']} version tags (the RQ1 before/after cutpoints)")
    ck = g["commit_kinds"]
    print(f"Commit mix        : {ck.get('feat',0)} feat (built) · {ck.get('fix',0)} fix "
          f"(≈ failure modes closed) · {ck.get('docs',0)} docs")
    print()
    print(f"Bus coordination  : {_human(b['total_messages'])} messages, "
          f"{b['unique_participants']} sessions, over {', '.join(b['by_month'].keys())}")
    a = b["addressing"]
    print(f"Addressing        : {a['directed_le4']} directed (≤4) · {a['broadcast']} broadcast · "
          f"{a['announcement_gt4']} announcement (>4)  →  directed share {b['directed_share']:.0%}")
    print(f"  (directed auto-delivered mail = the RQ1 courier-eliminated proxy)")
    print()
    print("RQ readiness:")
    print(f"  RQ1 autonomy       : ✅ objective backbone here (directed-mail volume + timeline); "
          "true courier count needs coding")
    print(f"  RQ2 robustness     : ⚙ {g['failure_fixes_count']} fix-commits as candidates; needs "
          "coord-vs-not coding + ablations")
    print(f"  RQ3 defect discovery: ⚙ same fix list; needs author-vs-bystander coding")
    print(f"  RQ4 convergence    : ⚙ needs coding (PROJECT_LAYER review = a ready worked example)")
    print(f"  RQ5 baseline       : ✍ not in the passive record — must be run")
    print("\nRun --json for the full dataset (per-sender, monthly, fix list, tag timeline).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
