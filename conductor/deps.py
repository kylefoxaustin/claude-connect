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

An edge ``A -> B`` means **"A is waiting on B"** — but *how badly* differs, and conflating
the two would make the alarm worthless:

  * **HARD** (``resource``, ``service``) — A genuinely **cannot proceed**. It is queued for
    a board someone else holds, or its job is sitting behind others in a service queue.
    It is trapped until something changes.
  * **SOFT** (``mail``) — A asked B a question and B hasn't read it. A is *awaiting a
    reply*, and may well be doing productive work meanwhile. On a fast fleet, twenty of
    these is just a conversation in flight, not a crisis.

Calling both "blocked" would make the dashboard shout on a healthy fleet — and a
dashboard that cries wolf is one you learn to ignore, which means it will not be believed
on the night something genuinely deadlocks. So the counts are kept separate and the
headline number is the HARD one.

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
from pathlib import Path
from typing import Any

from .bus import _HEADER_RE, _WAKE_MAX_RECIPIENTS, _address_targets


def open_ask_edges(
    markdown_path: Path,
    live_tags: set[str],
    *,
    now: float | None = None,
    window_h: float = 12.0,
) -> list[dict[str, Any]]:
    """Wait-for edges from OPEN ASKS, not unread counts (image_gen, 2026-07-13).

    An edge ``A -> B`` ("A is waiting on B") exists iff **A sent B a DIRECTED message (1..N named
    recipients, not a broadcast) containing a ``?`` that B has NOT REPLIED to** — B has not since
    posted a message addressing A. This is exactly ``bus.sh waiting``'s rule, so the stall graph and
    the glance-tool agree and *no phantom edge threads through a node that merely has unread cc'd
    mail*. "B has N unread" is "B is behind on reading," never "B owes A a reply."
    """
    now = time.time() if now is None else now
    live = {_plain(t) for t in (live_tags or set())}
    try:
        lines = Path(markdown_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    # Parse messages: {ep, snd, to(recipients), body-has-question}.
    msgs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            cur = {"ep": _ts_to_epoch(f"{m.group(1)} {m.group(2)}", now),
                   "snd": _plain(m.group(3)), "first": None, "q": False, "to": frozenset()}
            msgs.append(cur)
        elif cur is not None and line.strip():
            if cur["first"] is None:
                cur["first"] = line
            if "?" in line:
                cur["q"] = True
    # The human (operator) NEVER posts a bus reply — Kyle reads through the UI and ACTS — so an edge
    # TO operator could never close and would dangle as a phantom "waiting on Kyle." bus.sh waiting
    # excludes the human for exactly this reason; the stall graph must too. (A session that needs
    # Kyle is the DECISION QUEUE's job, not a stall.) ``_NONPOSTING`` is module-level (shared with
    # silent_addressees).
    for mm in msgs:
        targets = _address_targets(mm["first"] or "")
        # A message that addresses `all` is a BROADCAST — "one person telling everyone" — even
        # when it also cc's specific tags (`to:a to:b to:all`). Those named tags are for visibility
        # and wake, NOT a directed question each recipient owes a reply to (v2.29's rule). Without
        # this, a fleet-wide conclusion that happens to contain a `?` mints a phantom "A is waiting
        # on B" edge to every session it thanked (93emulator's "RESOLVED… thank you all", 2026-07-17).
        mm["broadcast"] = "all" in targets
        mm["to"] = {t for t in targets
                    if t not in ("all", "p:wake", "p:low") and t not in _NONPOSTING}

    # Latest time each responder addressed each addressee — the "did B reply to A?" index (O(N)).
    last_reply: dict[tuple[str, str], float] = {}
    for mm in msgs:
        for addressee in mm["to"]:
            k = (mm["snd"], addressee)
            if mm["ep"] > last_reply.get(k, -1.0):
                last_reply[k] = mm["ep"]

    edges: dict[tuple[str, str], float] = {}   # (src,dst) -> oldest still-open ask
    horizon = now - window_h * 3600
    for mm in msgs:
        src = mm["snd"]
        if src not in live or mm["ep"] < horizon or not mm["q"]:
            continue
        if mm.get("broadcast"):                                  # to:all — an announcement, never a directed ask
            continue
        if not (1 <= len(mm["to"]) <= _WAKE_MAX_RECIPIENTS):     # directed, not a mass-cc announcement
            continue
        for dst in mm["to"]:
            if dst == src:
                continue
            if last_reply.get((dst, src), -1.0) >= mm["ep"]:   # B replied to A after the ask
                continue
            if (src, dst) not in edges or mm["ep"] < edges[(src, dst)]:
                edges[(src, dst)] = mm["ep"]
    return [{"src": s, "dst": d, "kind": "mail", "hard": False,
             "why": "open question — no reply yet", "since": ep, "age": max(0.0, now - ep)}
            for (s, d), ep in edges.items()]


def silent_addressees(
    markdown_path: Path,
    *,
    now: float | None = None,
    silence_h: float = 4.0,
    addressed_window_h: float = 12.0,
) -> list[dict[str, Any]]:
    """The dead-reader alarm (holobench, 2026-07-13): *"X has POSTED NOTHING for N hours while being
    ADDRESSED DIRECTLY."*

    holobench was gone for **five days** — its bus watcher lived in ``/tmp``, wiped on reboot — and
    332 messages piled up behind a reader that no longer existed while **nothing alarmed.** An unread
    *counter* cannot see that: "is deliberating", "has nothing to say", and "is not running" all render
    as the same number going up. A high unread count is evidence of a LOUD FLEET or a DEAD READER, and
    the second is the only one that needs an alarm and the one the counter cannot distinguish.

    The signal that CAN: a tag that **others are directly addressing** (a ``to:<tag>`` message, not a
    broadcast, not a mass-cc) but that has **posted nothing itself for ``silence_h`` hours** (or ever).
    A session nobody is talking to being quiet is fine; a session people are trying to reach that has
    gone silent is either dead or ignoring its mail — both worth surfacing. This is a pure function of
    the bus log; the caller annotates each hit with whether a live process currently exists (no live
    process + an open ask ⇒ a near-certain outage a human must clear).

    Returns, per silent addressee (most-severe first): ``tag``, ``last_post_ep`` (None = never posted),
    ``silent_for`` seconds (None = never posted), ``addressed_by`` senders, ``last_addressed_ep``,
    ``open_ask_count`` (directed unanswered questions to it) and ``open_ask_from``.
    """
    now = time.time() if now is None else now
    try:
        lines = Path(markdown_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    msgs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for line in lines:
        m = _HEADER_RE.match(line)
        if m:
            cur = {"ep": _ts_to_epoch(f"{m.group(1)} {m.group(2)}", now),
                   "snd": _plain(m.group(3)), "first": None, "q": False, "to": frozenset()}
            msgs.append(cur)
        elif cur is not None and line.strip():
            if cur["first"] is None:
                cur["first"] = line
            if "?" in line:
                cur["q"] = True
    for mm in msgs:
        mm["to"] = {t for t in _address_targets(mm["first"] or "")
                    if t not in ("all", "p:wake", "p:low") and t not in _NONPOSTING}

    # Last time each tag POSTED anything (any message from it), and the reply index for open-asks.
    last_post: dict[str, float] = {}
    last_reply: dict[tuple[str, str], float] = {}
    for mm in msgs:
        if mm["ep"] > last_post.get(mm["snd"], -1.0):
            last_post[mm["snd"]] = mm["ep"]
        for addressee in mm["to"]:
            k = (mm["snd"], addressee)
            if mm["ep"] > last_reply.get(k, -1.0):
                last_reply[k] = mm["ep"]

    # Per addressee: who addressed it (directed only), most-recent such time, and how many still-open
    # questions point at it. A broadcast / mass-cc is NOT "addressing" — being cc'd is not a debt.
    addressed: dict[str, dict[str, Any]] = {}
    for mm in msgs:
        if not (1 <= len(mm["to"]) <= _WAKE_MAX_RECIPIENTS):
            continue
        for dst in mm["to"]:
            if dst == mm["snd"]:
                continue
            info = addressed.setdefault(dst, {"senders": set(), "last_ep": -1.0,
                                              "ask_ct": 0, "open_from": set()})
            info["senders"].add(mm["snd"])
            info["last_ep"] = max(info["last_ep"], mm["ep"])
            if mm["q"] and last_reply.get((dst, mm["snd"]), -1.0) < mm["ep"]:
                info["ask_ct"] += 1
                info["open_from"].add(mm["snd"])

    addr_horizon = now - addressed_window_h * 3600
    silence_s = silence_h * 3600
    out: list[dict[str, Any]] = []
    for tag, info in addressed.items():
        if info["last_ep"] < addr_horizon:            # nobody has tried to reach it recently
            continue
        lp = last_post.get(tag)
        silent_for = None if lp is None else max(0.0, now - lp)
        if silent_for is not None and silent_for < silence_s:
            continue                                  # it HAS been talking — not silent
        out.append({
            "tag": tag,
            "last_post_ep": lp,
            "silent_for": silent_for,
            "addressed_by": sorted(info["senders"]),
            "last_addressed_ep": info["last_ep"],
            "open_ask_count": info["ask_ct"],
            "open_ask_from": sorted(info["open_from"]),
            "ever_posted": lp is not None,
        })
    # Most-severe first: an open ask outranks none; never-posted (None) sorts as the longest silence.
    out.sort(key=lambda d: (-d["open_ask_count"], -(d["silent_for"] if d["silent_for"] is not None else 1e18)))
    return out


_NONPOSTING = {"operator", "human", "kyle"}


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
    mail_edges: list[dict[str, Any]],
    services: list[dict[str, Any]],
    resources: list[dict[str, Any]],
    live_tags: set[str],
    now: float | None = None,
) -> dict[str, Any]:
    """The fleet's wait-for graph. Edge ``A -> B`` == "A is blocked on B"."""
    now = time.time() if now is None else now
    edges: list[dict[str, Any]] = []

    # 1. Directed mail — an OPEN ASK, not an unread count (image_gen, 2026-07-13). ``mail_edges`` is
    #    open_ask_edges(): A asked B a question B hasn't replied to. "B has unread cc'd mail" is NOT
    #    a wait-for edge, so a node that owes nobody a reply can never be a phantom link in a stall.
    for e in (mail_edges or []):
        if _plain(e["src"]) != _plain(e["dst"]):
            edges.append(dict(e))

    # 2. Service queue. A job with image_gen -> the requester is waiting on the service.
    #
    # HARD only if the service is DEAD. A queued/serving job is fire-and-forget: the requester
    # posted it and went back to work, and a LIVE service is going to serve it (working now, or
    # idle and re-woken by _wake_stale_service_heads). That is in-flight async work, not a stall —
    # calling it "stuck" made the Blocked pane shout that image_gen was trapped while image_gen was
    # the one WORKING (2026-07-17: it did the whole job off-book, never ran /svc-next, so the entry
    # sat in the queue and the pane read it as a stall). The genuine stall is a queue in front of a
    # service with NO live session — nobody is going to serve it, exactly the dead-reader signal.
    live_plain = {_plain(t) for t in live_tags}
    for svc in services or []:
        name = _plain(svc.get("name", ""))
        svc_live = name in live_plain
        serving = svc.get("serving")
        if serving and serving.get("requester"):
            src = _plain(serving["requester"])
            started = float(serving.get("started") or serving.get("epoch") or now)
            if src != name:
                edges.append({
                    "src": src, "dst": name, "kind": "service", "hard": not svc_live,
                    "why": (f"job in progress: {(serving.get('text') or '')[:70]}" if svc_live
                            else f"job stuck — {name} is OFFLINE: {(serving.get('text') or '')[:60]}"),
                    "since": started, "age": max(0.0, now - started),
                })
        for job in svc.get("queue") or []:
            src = _plain(job.get("requester", ""))
            if not src or src == name:
                continue
            since = float(job.get("epoch") or now)
            edges.append({
                "src": src, "dst": name, "kind": "service", "hard": not svc_live,
                "why": (f"queued job (being served): {(job.get('text') or '')[:60]}" if svc_live
                        else f"queued job — {name} OFFLINE, nobody serving: {(job.get('text') or '')[:50]}"),
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
                "src": src, "dst": holder, "kind": "resource", "hard": True,
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
                "live": tag in live_plain,
                "worst_age": max((e["age"] for e in edges if e["dst"] == tag), default=0.0),
            }
            for tag, srcs in blocking.items()
        ),
        key=lambda b: (-b["count"], -b["worst_age"]),
    )

    edges.sort(key=lambda e: -e["age"])          # longest-suffering first
    # The HEADLINE number is the hard one. Twenty sessions awaiting a reply on a fast
    # fleet is a conversation, not a crisis; a dashboard that shouts on that is a
    # dashboard you stop reading — and then it is not believed on the night it matters.
    return {
        "edges": edges,
        "cycles": cycles_out,
        "bottlenecks": bottlenecks,
        "blocked_count": len({e["src"] for e in edges if e.get("hard")}),   # genuinely trapped
        "awaiting_count": len({e["src"] for e in edges if not e.get("hard")}),  # merely awaiting a reply
    }


def compute_lost_rc(
    sessions: list[dict[str, Any]],
    rc_ever: set[str],
    lost_rc_since: dict[str, float],
    *,
    now: float,
    threshold_min: float = 15.0,
) -> list[dict[str, Any]]:
    """The live-but-lost-``/RC`` alarm (ARCHITECTURE_VISION §3.4.1, the rt1180 fix).

    A session that lost its remote-control bridge is **alive but invisible in the phone's Claude
    app** — which is exactly why Kyle assumed rt1180 had crashed and launched a replacement, putting
    two sessions in one repo stepping on each other's git and mail. Conductor watches processes, not
    ``/RC``, so it *can* see the session is alive; this surfaces that as an alarm ("alive, lost /RC
    Nm ago — Reconnect, don't relaunch") instead of a quiet per-row button.

    Fires ONLY on *lost it*, never *never-had-it*: a session that was never bridged may simply be one
    Kyle doesn't drive from the phone, so alarming on it would be noise. So we require the session to
    have been seen bridged at least once (``rc_ever``), then observed unbridged — with no reconnect
    queued — for ``threshold_min`` minutes (debounced via ``lost_rc_since``, like the orphan-lease
    flag). ``rc_ever`` and ``lost_rc_since`` are MUTATED in place (per-session state across scans).

    Each input session dict: ``session_id``, ``bridged`` (bool), ``rc_pending`` (bool), plus display
    fields (``member``, ``project_dir``, ``preview``, ``last_activity_at``) carried into the alarm.
    """
    alarms: list[dict[str, Any]] = []
    live: set[str] = set()
    for s in sessions:
        sid = s.get("session_id") or ""
        if not sid:
            continue
        live.add(sid)
        if s.get("bridged"):
            rc_ever.add(sid)                 # it's on the phone now — remember it, clear any timer
            lost_rc_since.pop(sid, None)
            continue
        if s.get("rc_pending"):              # a reconnect is queued — recovering, not lost
            lost_rc_since.pop(sid, None)
            continue
        if sid not in rc_ever:               # never bridged — not this alarm's business
            continue
        lost_rc_since.setdefault(sid, now)
        mins = (now - lost_rc_since[sid]) / 60.0
        if mins >= threshold_min:
            alarms.append({
                "session_id": sid,
                "member": s.get("member", ""),
                "project_dir": s.get("project_dir", ""),
                "preview": s.get("preview", ""),
                "last_activity_at": s.get("last_activity_at"),
                "lost_rc_minutes": round(mins),
            })
    # GC per-session state for sessions that are no longer live (a relaunch mints a new session_id).
    for sid in list(lost_rc_since):
        if sid not in live:
            lost_rc_since.pop(sid, None)
    for sid in list(rc_ever):
        if sid not in live:
            rc_ever.discard(sid)
    alarms.sort(key=lambda a: a["lost_rc_minutes"], reverse=True)   # most-stale first
    return alarms
