"""Coordination state Conductor reads from ``~/.claude/bus-state/coord/``.

Phase 1 has one kind of coordination record: **retractions**. When a session runs
``bus.sh retract <tag> "<why>"`` it drops a record here; Conductor wakes the target
*immediately* (overriding the busy guard — the target may be mid-action) so a bad
instruction can be pulled back before it's acted on.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

RETRACTION_TTL = 2 * 3600  # matches bus.sh's prune window; stale records are ignored


def _parse(path: Path) -> dict[str, str]:
    d: dict[str, str] = {}
    try:
        for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = ln.partition("=")
            if sep:
                d[k.strip()] = v
    except OSError:
        return {}
    return d


def read_retractions(coord_root: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Active (non-expired) retraction records. Each: ``{id, sender, target_plain,
    text, created, epoch}``, newest first."""
    now = time.time() if now is None else now
    rdir = coord_root / "retractions"
    if not rdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = list(rdir.iterdir())
    except OSError:
        return []
    for f in files:
        if not f.is_file():
            continue
        d = _parse(f)
        epoch = d.get("epoch", "")
        if not epoch.isdigit() or now - int(epoch) > RETRACTION_TTL:
            continue
        out.append({
            "id": f.name,
            "sender": d.get("sender", ""),
            "target_plain": d.get("target_plain", ""),
            "text": d.get("text", ""),
            "created": d.get("created", ""),
            "epoch": int(epoch),
        })
    out.sort(key=lambda r: r["epoch"], reverse=True)
    return out


def read_wake_state(coord_root: Path) -> dict[str, tuple[str, float]]:
    """Which sessions we've already prodded to check the bus, and at what watermark.

    Persisted (unlike most of Conductor's state, which is deliberately restart-clean)
    because a restart that FORGETS this re-prods every session with unread mail — and
    a session in a long tool call has its keystrokes *queue*, so repeated restarts
    stack /msg-checks on it. Lives with the other coordination state.
    """
    f = coord_root / "wake-state.json"
    try:
        raw = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, tuple[str, float]] = {}
    if isinstance(raw, dict):
        for tag, v in raw.items():
            if isinstance(v, list) and len(v) == 2:
                try:
                    out[str(tag)] = (str(v[0]), float(v[1]))
                except (TypeError, ValueError):
                    continue
    return out


def write_wake_state(coord_root: Path, state: dict[str, tuple[str, float]]) -> None:
    """Best-effort persist. Never raises — a failure here must not break a scan."""
    try:
        coord_root.mkdir(parents=True, exist_ok=True)
        tmp = coord_root / "wake-state.json.tmp"
        tmp.write_text(json.dumps({k: [v[0], v[1]] for k, v in state.items()}), encoding="utf-8")
        tmp.replace(coord_root / "wake-state.json")   # atomic
    except OSError:
        pass


def read_push_requests(coord_root: Path) -> list[dict[str, Any]]:
    """Pending ``git push`` approvals the PreToolUse gate filed. Each: ``{key,
    repo_name, cwd, cmd, created, epoch}``, newest first. These wait for Kyle — no
    TTL (a push shouldn't silently expire out of the inbox)."""
    rdir = coord_root / "push-requests"
    if not rdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = list(rdir.iterdir())
    except OSError:
        return []
    for f in files:
        if not f.is_file():
            continue
        d = _parse(f)
        out.append({
            "key": f.name,
            "repo_name": d.get("repo_name", f.name),
            "cwd": d.get("cwd", ""),
            "cmd": d.get("cmd", ""),
            "created": d.get("created", ""),
            "epoch": int(d["epoch"]) if d.get("epoch", "").isdigit() else 0,
        })
    out.sort(key=lambda r: r["epoch"], reverse=True)
    return out


def read_push_grants(coord_root: Path, *, now: float | None = None) -> list[dict[str, Any]]:
    """Approvals Kyle has GIVEN that the session hasn't used yet.

    This state used to be invisible, and the invisibility *was* the bug. Approving deleted
    the request and armed a 30-minute token; if the session didn't retry in time (asleep,
    busy, or Conductor not running to ping it) the token expired — and since the request was
    already gone, the approval vanished without trace. The next push filed a *fresh* request,
    so Kyle saw a duplicate ask with no hint that he had already said yes to it.

    Making the grant durable (24h) is only half the fix. The other half is showing it: a
    long-lived permission is safe when you can SEE it and TAKE IT BACK, not when it has a
    short fuse. So an armed grant is now its own state — "approved, waiting for the session
    to push" — with a revoke next to it.
    """
    now = time.time() if now is None else now
    tdir = coord_root / "push-tokens"
    if not tdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = list(tdir.iterdir())
    except OSError:
        return []
    for f in files:
        if not f.is_file():
            continue
        d = _parse(f)
        exp = d.get("expires", "")
        if not exp.isdigit():
            # A leftover bare-epoch token from before the format change. Still honoured by
            # the gate, so it must still be shown — a grant Kyle can't see is one he can't
            # revoke.
            try:
                exp = f.read_text(encoding="utf-8").strip().split("\n")[0].strip()
            except OSError:
                continue
        if not exp.isdigit() or int(exp) <= now:
            continue                        # expired; bus.sh reaps these lazily
        out.append({
            "key": f.name,
            "repo_name": d.get("repo_name") or f.name,
            "approved_at": d.get("approved_at", ""),
            "expires_epoch": int(exp),
            "expires_in": int(exp) - now,
        })
    out.sort(key=lambda r: r["expires_epoch"])
    return out
