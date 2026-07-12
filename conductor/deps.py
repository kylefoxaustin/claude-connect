"""Who is blocked on whom — the fleet's wait-for graph.

Kyle's original ask, and the last piece of the coordination arc: *"a view which shows
which Claude is dependent on another for something, or is waiting on something."* With
30+ sessions cross-talking, he could see WHAT everyone was doing and never see WHO WAS
STUCK ON WHOM.

The nice part: **every input already exists.** Nothing new has to be collected —

  * **directed mail**  — B has unread mail addressed to it from A  ⇒  A waits on B.
    (A asked something and hasn't been answered. This is the soft, most common edge.)
  * **service queue**  — A queued a job with image_gen             ⇒  A waits on image_gen.
  * **resource queue** — A is queued for a board held by H         ⇒  A waits on H.

An edge ``A -> B`` always means **"A is blocked on B"**: B is the one holding A up.

Two things make this more than a pretty picture:

**Cycles.** If A waits on B and B waits on A, nobody moves. We distinguish honestly
between two kinds, because they are not the same animal:

  * a **DEADLOCK** — every edge in the cycle is a *resource* hold. This is the classic
    one (A holds board1 wanting board2, B holds board2 wanting board1) and it will
    **never** resolve on its own. It needs a human.
  * a **mutual stall** — the cycle runs through mail or service queues. Each side is
    waiting for the other to speak. It's not fatal (either could just reply), but on a
    fast fleet it means two sessions are politely waiting each other out forever.

Calling both "deadlock" would be the kind of plausible-but-wrong label this fleet has
spent a lot of energy learning to hate.

**Bottlenecks.** Rank by *in-degree*: if five sessions are all waiting on qualcomm, then
qualcomm is the fleet's critical path and that's where a human minute is worth most.
"""

from __future__ import annotations

import time
from typing import Any


def _plain(tag: str) -> str:
    """``[other:qualcomm]`` == ``other:qualcomm`` == ``qualcomm``."""
    t = (tag or "").strip().strip("[]")
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()


def _ts_to_epoch(ts: str, now: float) -> float:
    """Bus timestamps are minute-resolution local time (``YYYY-MM-DD HH:MM``)."""
    try:
        return time.mktime(time.strptime(ts.strip(), "%Y-%m-%d %H:%M"))
    except (ValueError, TypeError):
        return now


def _find_cycles(adj: dict[str, set[str]]) -> list[list[str]]:
    """Every simple cycle in the wait-for graph (DFS with a colour marking).

    Fleet-sized graphs are tiny (tens of nodes), so a plain exhaustive walk is fine and
    far easier to trust than anything clever. Cycles are de-duplicated by their node set
    rotated to a canonical start, so A->B->A and B->A->B are reported once.
    """
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def canon(path: list[str]) -> tuple[str, ...]:
        i = path.index(min(path))
        return tuple(path[i:] + path[:i])

    def walk(node: str, stack: list[str], onstack: set[str]) -> None:
        for nxt in sorted(adj.get(node, ())):
            if nxt in onstack:                       # closed a loop
                cyc = stack[stack.index(nxt):]
                key = canon(cyc)
                if key not in seen:
                    seen.add(key)
                    cycles.append(list(key))
                continue
            if len(stack) > 12:                      # pathological safety valve
                continue
            walk(nxt, stack + [nxt], onstack | {nxt})

    for start in sorted(adj):
        walk(start, [start], {start})
    return cycles


def build_wait_graph(
    *,
    directed_unread: dict[str, dict[str, Any]],
    services: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    live_tags: set[str],
    now: float | None = None,
) -> dict[str, Any]:
    """The fleet's wait-for graph. Edge ``A -> B`` == "A is blocked on B"."""
    now = time.time() if now is None else now
    edges: list[dict[str, Any]] = []

    # 1. Directed mail. B has unread mail from A -> A is waiting on B to read/answer.
    for tag, info in (directed_unread or {}).items():
        if not info or not info.get("count"):
            continue
        dst = _plain(tag)
        since = _ts_to_epoch(info.get("latest_ts", ""), now)
        for sender in info.get("senders") or []:
            src = _plain(sender)
            if src == dst:
                continue
            edges.append({
                "src": src, "dst": dst, "kind": "mail",
                "why": f"{info['count']} unread message(s) — hasn't replied",
                "since": since, "age": max(0.0, now - since),
            })

    # 2. Service queue. A job with image_gen -> the requester is waiting on the service.
    for svc in services or []:
        name = _plain(svc.get("name", ""))
        serving = svc.get("serving")
        if serving and serving.get("requester"):
            src = _plain(serving["requester"])
            started = float(serving.get("started") or serving.get("epoch") or now)
            if src != name:
                edges.append({
                    "src": src, "dst": name, "kind": "service",
                    "why": f"job in progress: {(serving.get('text') or '')[:70]}",
                    "since": started, "age": max(0.0, now - started),
                })
        for job in svc.get("queue") or []:
            src = _plain(job.get("requester", ""))
            if not src or src == name:
                continue
            since = float(job.get("epoch") or now)
            edges.append({
                "src": src, "dst": name, "kind": "service",
                "why": f"queued job: {(job.get('text') or '')[:70]}",
                "since": since, "age": max(0.0, now - since),
            })

    # 3. Resource queue. A waits for a board -> A is blocked on whoever HOLDS it. We
    #    point the edge at the HOLDER, not the board: a board can't unblock you, and the
    #    holder is the one a human would actually go and talk to.
    for res in resources or []:
        lease = res.get("lease") or {}
        holder = _plain(lease.get("owner", ""))
        if not holder or lease.get("offered"):
            continue                                  # an offer isn't a block: it's your turn
        acquired = float(lease.get("acquired_epoch") or now)
        for waiter in lease.get("queue") or []:
            src = _plain(waiter)
            if not src or src == holder:
                continue
            edges.append({
                "src": src, "dst": holder, "kind": "resource",
                "why": f"waiting for {res.get('name', '?')} (held by {holder})",
                "since": acquired, "age": max(0.0, now - acquired),
                "resource": res.get("name", ""),
            })

    # --- analysis -----------------------------------------------------------
    adj: dict[str, set[str]] = {}
    for e in edges:
        adj.setdefault(e["src"], set()).add(e["dst"])

    kinds: dict[tuple[str, str], set[str]] = {}
    for e in edges:
        kinds.setdefault((e["src"], e["dst"]), set()).add(e["kind"])

    cycles_out: list[dict[str, Any]] = []
    for cyc in _find_cycles(adj):
        pairs = [(cyc[i], cyc[(i + 1) % len(cyc)]) for i in range(len(cyc))]
        all_kinds: set[str] = set()
        for p in pairs:
            all_kinds |= kinds.get(p, set())
        # Only a cycle made ENTIRELY of resource holds is a true deadlock — it cannot
        # resolve itself. A cycle through mail/services is a mutual stall: annoying and
        # invisible, but either side could break it by simply answering.
        deadlock = all_kinds == {"resource"}
        cycles_out.append({
            "nodes": cyc,
            "kinds": sorted(all_kinds),
            "deadlock": deadlock,
            "label": "DEADLOCK — neither can proceed, this will never resolve itself"
                     if deadlock else
                     "mutual stall — each is waiting for the other to speak",
        })

    # Bottlenecks: who is holding up the most sessions. This is where a human minute
    # buys the most, so rank it and put the worst first.
    blocking: dict[str, list[str]] = {}
    for e in edges:
        blocking.setdefault(e["dst"], []).append(e["src"])
    bottlenecks = sorted(
        (
            {
                "tag": tag,
                "blocking": sorted(set(srcs)),
                "count": len(set(srcs)),
                "live": tag in {_plain(t) for t in live_tags},
                "worst_age": max((e["age"] for e in edges if e["dst"] == tag), default=0.0),
            }
            for tag, srcs in blocking.items()
        ),
        key=lambda b: (-b["count"], -b["worst_age"]),
    )

    edges.sort(key=lambda e: -e["age"])          # longest-suffering first
    return {
        "edges": edges,
        "cycles": cycles_out,
        "bottlenecks": bottlenecks,
        "blocked_count": len({e["src"] for e in edges}),
    }
