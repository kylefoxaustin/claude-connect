"""Coordination state Conductor reads from ``~/.claude/bus-state/coord/``.

Phase 1 has one kind of coordination record: **retractions**. When a session runs
``bus.sh retract <tag> "<why>"`` it drops a record here; Conductor wakes the target
*immediately* (overriding the busy guard — the target may be mid-action) so a bad
instruction can be pulled back before it's acted on.
"""

from __future__ import annotations

import json
import os
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


def read_winddown(coord_root: Path) -> dict[str, Any]:
    """The active fleet wind-down (if any) + the per-member VERIFIED acks.

    ``active`` is the initiator/created marker written by ``bus.sh shutdown begin`` (or None
    when no wind-down is in progress); ``acks`` maps a member's plain name to its verified
    done-record — the file ``bus.sh shutdown ack`` writes ONLY after checking the real git +
    lease state on disk, so an ack here means the session provably completed the protocol,
    not that it claimed to. That is what makes a session safe to close."""
    base = coord_root / "wind-down"
    active_f = base / "active"
    if not active_f.exists():
        return {"active": None, "acks": {}}
    active = _parse(active_f)
    acks: dict[str, dict[str, str]] = {}
    try:
        for f in sorted(base.glob("*.done")):
            rec = _parse(f)
            plain = (rec.get("plain") or f.stem).strip().lower()
            acks[plain] = rec
    except OSError:
        pass
    return {"active": active, "acks": acks}


def read_wake_state(coord_root: Path) -> dict[str, tuple]:
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
    out: dict[str, tuple] = {}
    if isinstance(raw, dict):
        for tag, v in raw.items():
            # Accept 2-, 3- and 4-element forms and pass the WHOLE tuple through;
            # the caller normalises. This used to accept ONLY len==2, which silently
            # dropped every richer entry — so widening the writer alone would have
            # emptied the map on restart and re-prodded the entire fleet, the exact
            # storm this file is persisted to prevent. Widen both sides or neither.
            if isinstance(v, (list, tuple)) and 2 <= len(v) <= 4:
                try:
                    rest = tuple(v[2:])
                    out[str(tag)] = (str(v[0]), float(v[1])) + rest
                except (TypeError, ValueError):
                    continue
    return out


def write_wake_state(coord_root: Path, state: dict[str, tuple]) -> None:
    """Best-effort persist. Never raises — a failure here must not break a scan.

    Persist the WHOLE tuple. This used to write ``[v[0], v[1]]`` while the scanner
    stored a 4-tuple ``(watermark, woke_at, last_activity_at, latest_ts)``, so the
    activity stamp never survived a restart; ``read_wake_state`` then read the
    2-element form back with activity ``+inf``, and the lost-keystroke retry — whose
    test is "the transcript MOVED while the watermark did NOT" — could never fire
    again, because nothing exceeds infinity. A session that missed one wake stayed
    silent forever. Measured 2026-09-17: four live sessions held 2,475 unread
    messages with their dedup key pinned to a watermark only a successful read
    could advance.
    """
    try:
        coord_root.mkdir(parents=True, exist_ok=True)
        tmp = coord_root / "wake-state.json.tmp"
        tmp.write_text(json.dumps({k: list(v) for k, v in state.items()}), encoding="utf-8")
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
            # WHAT is being pushed, in words ("main", "tag v1.1-rules", "delete old-branch").
            # Without it two requests for one repo are indistinguishable in the inbox: Kyle
            # approved a branch, saw the TAG request appear, and read it as the same ask coming
            # back — "didn't see any new ones to tap" (2026-08-31). Older gates do not write the
            # field; "" renders as the plain repo name, exactly as before.
            "refs": d.get("refs", ""),
            # ⭐ THE SESSION THAT ASKED, BY STABLE IDENTITY — not by the directory it was in.
            # The verdict could only ever be routed by `cwd`, and TWO WRITERS DISAGREE about what
            # that field holds: the tool-layer gate records the SESSION's dir, while the pre-push
            # hook records `$PWD`, which git sets to the REPO TOPLEVEL. So a session that pushes a
            # repo other than its own project filed a cwd no session lives in, the verdict resolved
            # to nobody, and it was dropped in silence. agentic-skills-imx lived it: Kyle tapped SIX
            # times for two repos because each tap appeared to do nothing.
            #
            # Its own evidence states the defect better than the cwd framing does — in ONE session,
            # minutes apart, a SPURIOUS request filed by the tool layer delivered perfectly while
            # both GENUINE pushes resolved to None. Deliverability tracked which code path filed the
            # request, not whether the request was real.
            #
            # CLAUDE.md rule 2: identify by stable identity, never by a proxy. `cwd` is a proxy for
            # "which session", and it drifted. Older gates omit this; "" falls back to the cwd match,
            # so nothing regresses before the gate patch is installed.
            "session_id": d.get("session_id", ""),
            "created": d.get("created", ""),
            "epoch": int(d["epoch"]) if d.get("epoch", "").isdigit() else 0,
        })
    out.sort(key=lambda r: r["epoch"], reverse=True)
    return out


def read_push_proposals(coord_root: Path) -> list[dict[str, Any]]:
    """A session asking *"is this the right MOMENT to push?"* — with the context to answer it.

    Different question from the gate's. The gate asks **"may you push?"** and protects the
    repo. This asks **"should you push NOW, or keep digging?"** and protects the *work* — and
    the gate cannot answer it, because Kyle's inbox only ever showed him a repo name and a
    command. Approving that is a rubber stamp on a decision he never made.

    A proposal carries what the gate can't: what is actually in the commits, the session's
    case for shipping now, and the alternatives it is weighing. One decision, with the
    information, from anywhere — and answering it ARMS the grant, so there is no second
    content-free tap afterwards.
    """
    pdir = coord_root / "push-proposals"
    if not pdir.is_dir():
        return []
    out: list[dict[str, Any]] = []
    try:
        files = list(pdir.iterdir())
    except OSError:
        return []
    for f in files:
        if not f.is_file():
            continue
        # `alt=` repeats, so the flat single-value parser won't do.
        alts: list[str] = []
        d: dict[str, str] = {}
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                k, _, v = line.partition("=")
                if k == "alt":
                    alts.append(v)
                elif k:
                    d[k] = v
        except OSError:
            continue
        if not d.get("why"):
            continue
        out.append({
            "key": f.name,
            "repo_name": d.get("repo_name", f.name),
            "cwd": d.get("cwd", ""),
            # Same stable-identity routing as a gate request — see read_push_requests. A
            # proposal is filed by the session itself, so its cwd is usually right; recording
            # the id anyway means the verdict does not depend on that staying true.
            "session_id": d.get("session_id", ""),
            "why": d["why"],
            "alts": alts,
            "commits": [c for c in (d.get("commits", "").split("|")) if c],
            "created": d.get("created", ""),
            "epoch": int(d["epoch"]) if d.get("epoch", "").isdigit() else 0,
        })
    out.sort(key=lambda r: r["epoch"], reverse=True)
    return out


def clear_push_proposal(coord_root: Path, key: str) -> None:
    try:
        os.unlink(coord_root / "push-proposals" / key)
    except OSError:
        pass


def read_persist_requests(coord_root: Path) -> list[dict[str, Any]]:
    """Acts whose consequences would OUTLIVE the session that wants to commit them.

    The second hard control. The push gate guards a repo; this guards the machine — and it
    exists because *claude-connect fabricated Kyle's approval* and image_gen went to install a
    systemd daemon on the strength of it. Only its own harness stopped it. Luck, not
    architecture.

    The property that makes it immune to that: **the grant is a TOKEN IN A FILE, not words in
    a message.** A Claude can say "Kyle approved this" a hundred times and it is still denied.
    """
    rdir = coord_root / "persist-requests"
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
        if not d.get("target"):
            continue
        out.append({
            "key": f.name,
            "kind": d.get("kind", "?"),
            "target": d.get("target", ""),
            "target_name": d.get("target_name") or f.name,
            "detail": d.get("detail", ""),
            "cwd": d.get("cwd", ""),
            "created": d.get("created", ""),
            "epoch": int(d["epoch"]) if d.get("epoch", "").isdigit() else 0,
        })
    out.sort(key=lambda r: r["epoch"], reverse=True)
    return out


INFLIGHT_TTL = 24 * 3600  # bound directory growth; the transcript-advance check is the real clear


def read_inflight(coord_root: Path, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Sessions with a tool in flight — a Bash/Edit/… call that may be sitting on a
    permission prompt right now, keyed by realpath(cwd) so it matches how the picker guard
    resolves a session.

    Written by the ``tool-inflight.sh`` PreToolUse hook, cleared by PostToolUse. Each record
    carries ``started_epoch`` so the choke-point guard can self-clear: once the session's
    transcript has advanced past that time the tool has resolved, and a marker orphaned by a
    denied tool (PostToolUse may not fire) can never wedge the guard shut.

    Keyed by cwd, not session_id, because a cwd hosts at most one live session and that is the
    join key the injection guard already has (``SessionRecord.project_dir``). The newest marker
    for a cwd wins.
    """
    now = time.time() if now is None else now
    idir = coord_root / "inflight"
    if not idir.is_dir():
        return {}
    out: dict[str, dict[str, Any]] = {}
    try:
        files = list(idir.iterdir())
    except OSError:
        return {}
    for f in files:
        if not f.is_file() or f.name.endswith(".tmp"):
            continue
        d = _parse(f)
        cwd = (d.get("cwd") or "").strip()
        started = d.get("started_epoch", "")
        if not cwd or not started.isdigit():
            continue
        started_i = int(started)
        if now - started_i > INFLIGHT_TTL:
            continue                        # ancient; the tool is long gone
        key = os.path.realpath(cwd)
        prev = out.get(key)
        if prev is None or started_i > prev["started_epoch"]:
            out[key] = {
                "session_id": d.get("session_id", ""),
                "cwd": cwd,
                "tool": d.get("tool", ""),
                "started_epoch": started_i,
                "transcript": d.get("transcript", ""),
            }
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


# ── Fleet-health alert dismissals ───────────────────────────────────────────────────────
# ⚠️ WHY THESE LIVE ON THE SERVER AND NOT IN localStorage. The dismiss ✕ stored its state
# in localStorage, which works in a browser and CANNOT work in the native desktop app:
# pywebview runs in private mode and wipes localStorage (app.py:99 says so, and the auth
# token already works around it by seeding a variable instead). So on the machine Kyle
# actually uses the board from, a dismissal could never survive — no matter how correct the
# logic was. It was "fixed" twice without that being noticed, because the logic tests all
# passed against a store that is simply absent in that build.
#
# Server-side is also strictly better than the localStorage it replaces: a dismissal now
# survives a restart and is the same on the phone, the browser and the native app, which is
# what an operator means by "I have seen this one".

def read_alert_dismissals(coord_root: Path) -> dict[str, dict]:
    """``{key: {"at": epoch_ms, "n": magnitude}}``. Never raises."""
    f = coord_root / "alert-dismissals.json"
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    out: dict[str, dict] = {}
    for k, v in d.items():
        if isinstance(v, dict) and isinstance(v.get("at"), (int, float)):
            out[str(k)] = {"at": float(v["at"]), "n": float(v.get("n") or 0)}
    return out


def write_alert_dismissals(coord_root: Path, d: dict[str, dict]) -> None:
    """Best-effort persist, newest 200 only. Never raises — losing a dismissal must
    never break a scan, and an unbounded map accumulates keys for conditions that can
    no longer recur."""
    try:
        coord_root.mkdir(parents=True, exist_ok=True)
        trimmed = dict(sorted(d.items(), key=lambda kv: -(kv[1].get("at") or 0))[:200])
        f = coord_root / "alert-dismissals.json"
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trimmed), encoding="utf-8")
        tmp.replace(f)
    except (OSError, TypeError, ValueError):
        pass


# --- Launcher prefs: pinned / hidden dormant sessions ---------------------------------------
# The session launcher (desktop launcher.js, phone /m) lets Kyle ★ pin and hide dormant
# sessions. Those lived in each device's localStorage, so a pin on the phone never reached the
# desktop; he asked for them to sync (2026-10-13). Keyed by the session's real folder, the same
# key the launcher already used. Each entry stores WHEN it was set, which is what bounds it.
_LAUNCHER_PREFS = "launcher-prefs.json"
LAUNCHER_PREFS_CAP = 500


def read_launcher_prefs(coord_root: Path) -> dict[str, dict[str, float]]:
    """``{"pins": {dir: epoch_s}, "hidden": {dir: epoch_s}}``. Never raises; junk is dropped."""
    out: dict[str, dict[str, float]] = {"pins": {}, "hidden": {}}
    try:
        d = json.loads((coord_root / _LAUNCHER_PREFS).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return out
    if not isinstance(d, dict):
        return out
    for kind in out:
        v = d.get(kind)
        if isinstance(v, dict):
            out[kind] = {str(k): float(t) for k, t in v.items()
                         if isinstance(k, str) and k.startswith("/") and isinstance(t, (int, float))}
    return out


def write_launcher_prefs(coord_root: Path, prefs: dict[str, dict[str, float]]) -> None:
    """Best-effort atomic persist, newest LAUNCHER_PREFS_CAP per kind. Never raises."""
    try:
        coord_root.mkdir(parents=True, exist_ok=True)
        trimmed = {kind: dict(sorted((prefs.get(kind) or {}).items(), key=lambda kv: -kv[1])
                              [:LAUNCHER_PREFS_CAP])
                   for kind in ("pins", "hidden")}
        f = coord_root / _LAUNCHER_PREFS
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(trimmed), encoding="utf-8")
        tmp.replace(f)
    except (OSError, TypeError, ValueError):
        pass
