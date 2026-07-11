"""Service Claudes — a session that does work FOR other sessions (image_gen).

Kyle's realisation, and it's a good one: image_gen is *exactly* an EVK. Single
holder, one job at a time, contended by the fleet, needs a queue, needs telling when
its turn comes. The resource abstraction he already built turned out to be more
general than the thing he built it for.

But the lease **inverts**. With a dev board, the requester takes it and does the work
on it. With image_gen, the *service* does the work. So the lease stops meaning "I have
taken this" and starts meaning **"I am currently serving X"** — and the queue stops
being sessions waiting for access and starts being **jobs waiting to be done**.

Two consequences shape the whole design:

  * **Fire-and-forget.** A requester posts a job and goes straight back to its own
    work; when the service finishes it posts the result back as directed mail, and
    auto-delivery wakes the requester. Nobody idles in line. (A queue of *blocked*
    Claudes would be the worst of both worlds.)

  * **The human is not a queue entry.** Kyle talks to a service directly, so "make me
    first" can't mean "insert a job". It means **hold the queue**: finish the current
    job — no half-done render, no wasted GPU — then stop and wait for him rather than
    pulling the next one.

State lives in ``bus-state/coord/services/<name>/`` and is written by ``bus.sh svc``;
Conductor only reads it (plus the hold, which it can set on Kyle's click).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _fields(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    try:
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = ln.partition("=")
            if sep:
                d[k.strip()] = v
    except OSError:
        return {}
    return d


def _job(d: dict[str, str]) -> dict[str, Any]:
    return {
        "id": d.get("id", ""),
        "requester": d.get("requester", ""),
        "text": d.get("text", ""),
        "created": d.get("created", ""),
        "epoch": int(d["epoch"]) if d.get("epoch", "").isdigit() else 0,
        "started": int(d["started"]) if d.get("started", "").isdigit() else 0,
    }


def read_services(coord_root: Path) -> dict[str, Any]:
    """Every registered service: who it's serving, who's queued, and whether Kyle has
    claimed the next opening."""
    root = coord_root / "services"
    out: list[dict[str, Any]] = []
    if not root.is_dir():
        return {"services": out}
    try:
        dirs = sorted(p for p in root.iterdir() if p.is_dir())
    except OSError:
        return {"services": out}

    for d in dirs:
        serving_f = d / "serving"
        serving = _job(_fields(serving_f)) if serving_f.is_file() and serving_f.stat().st_size else None
        if serving and not serving.get("requester"):
            serving = None

        queue: list[dict[str, Any]] = []
        try:
            ids = [ln.strip() for ln in (d / "queue").read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            ids = []
        for jid in ids:
            jf = d / "jobs" / jid
            if jf.is_file():
                queue.append(_job(_fields(jf)))

        hold = ""
        hf = d / "hold"
        if hf.is_file():
            try:
                hold = hf.read_text(encoding="utf-8").strip()
            except OSError:
                hold = ""

        out.append({
            "name": d.name,
            "serving": serving,
            "queue": queue,
            "held": bool(hold),
            "hold_reason": hold,
        })
    return {"services": out}
