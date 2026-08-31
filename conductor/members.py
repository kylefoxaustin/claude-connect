"""Member registry — Conductor's WRITE side for the durable-principal bindings (v4 §3.4).

A *member* is the durable worker/conversation; ``session_id`` is its credential (harness-minted,
unforgeable, stable across ``--continue``). Conductor is the registrar because it is the one thing
that sees every live session — ``session_id`` is the transcript filename stem, and it also knows the
session's project — so it binds ``session_id -> member`` and lets the human set a *role*. The referee
(``persist-gate.sh`` via ``member-registry.sh``) READS the same file to enforce; this is the writer.

File: ``<bus-state>/members`` — one TAB-separated line per binding, the tag-map data-file pattern so a
script migration can never touch the bindings::

    <session_id>\t<member>\t<role>\t<project>

Roles: ``observer | service | peer | trusted``. Default is ``peer`` — byte-for-byte today's behavior,
because the referee adds no denial for ``peer`` (§3.4). We NEVER auto-assign more than ``peer``; a
higher role is only ever a deliberate human act (Observer *lowers* authority, Trusted *raises* it and
so must be granted, never inferred).
"""
from __future__ import annotations

from .locks import exclusive
import os
import tempfile
from pathlib import Path
from typing import Any

ROLES = ("observer", "service", "peer", "trusted")
_DEFAULT_ROLE = "peer"


def members_path(bus_state: Path) -> Path:
    return Path(bus_state) / "members"


def read_members(bus_state: Path) -> dict[str, dict[str, str]]:
    """``{session_id: {"member", "role", "project"}}``. Blank / ``#`` lines ignored; a malformed
    line is skipped, never fatal (the referee's read is best-effort too)."""
    path = members_path(bus_state)
    out: dict[str, dict[str, str]] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        sid = parts[0].strip()
        member = parts[1].strip() if len(parts) > 1 else ""
        if not sid or not member:
            continue
        role = (parts[2].strip() if len(parts) > 2 else "") or _DEFAULT_ROLE
        project = parts[3].strip() if len(parts) > 3 else ""
        out[sid] = {"member": member, "role": role, "project": project}
    return out


def _write_atomic(bus_state: Path, rows: dict[str, dict[str, str]]) -> None:
    """Write the whole registry atomically, under the same advisory lock the readers can take.

    The lock is a sibling ``members.lock`` (never the data file itself, so a reader mid-parse is never
    truncated). Atomic replace means the referee always sees a whole file or the old whole file —
    never a half-written one (a half-written members file would read EXACTLY like a whole one, which
    is failure class #1, and this file gates who may write to the machine)."""
    bus_state = Path(bus_state)
    bus_state.mkdir(parents=True, exist_ok=True)
    lock = bus_state / "members.lock"
    body = ["# session_id\tmember\trole\tproject  (managed by Conductor — v4 §3.4 member registry)"]
    for sid, rec in sorted(rows.items()):
        member = rec.get("member", "").strip()
        if not sid or not member:
            continue
        role = rec.get("role", _DEFAULT_ROLE).strip() or _DEFAULT_ROLE
        project = rec.get("project", "").strip()
        body.append(f"{sid}\t{member}\t{role}\t{project}")
    data = "\n".join(body) + "\n"
    with open(lock, "w") as lf, exclusive(lf):
        fd, tmp = tempfile.mkstemp(dir=str(bus_state), prefix=".members.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
            os.replace(tmp, str(members_path(bus_state)))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


def bind(bus_state: Path, session_id: str, member: str, *,
         role: str | None = None, project: str = "") -> dict[str, str]:
    """Upsert a ``session_id -> member`` binding. If the session is already bound and ``role`` is not
    given, its existing role is PRESERVED (re-binding on a scan must never silently reset a role a
    human set). A brand-new binding defaults to ``peer``. Returns the resulting record."""
    session_id = (session_id or "").strip()
    member = (member or "").strip()
    if not session_id or not member:
        raise ValueError("session_id and member are required")
    rows = read_members(bus_state)
    existing = rows.get(session_id)
    if role is None:
        role = existing["role"] if existing else _DEFAULT_ROLE
    role = _valid_role(role)
    if not project and existing:
        project = existing.get("project", "")
    # No-op guard: don't rewrite the file if nothing changed (avoids needless churn every scan).
    new_rec = {"member": member, "role": role, "project": project}
    if existing == new_rec:
        return new_rec
    rows[session_id] = new_rec
    _write_atomic(bus_state, rows)
    return new_rec


def ensure_bound(bus_state: Path, session_id: str, default_member: str, project: str = "") -> str:
    """Bind ``session_id -> default_member`` exactly ONCE, on first sighting, role ``peer``. If the
    session is already bound, do NOTHING and return the stored member — the member must be STABLE,
    never re-derived from a tag that can drift with a ``cd``. This is what Conductor calls per live
    session each scan; only the first call for a given ``session_id`` writes. Returns the member (or
    "" if inputs are empty)."""
    session_id = (session_id or "").strip()
    default_member = (default_member or "").strip()
    if not session_id or not default_member:
        return ""
    existing = read_members(bus_state).get(session_id)
    if existing:
        return existing["member"]
    bind(bus_state, session_id, default_member, role=_DEFAULT_ROLE, project=project)
    return default_member


def set_role(bus_state: Path, member: str, role: str) -> int:
    """Set the role on EVERY binding of ``member`` (a member's role is a property of the member, not
    of one session_id). Returns the number of rows changed. This is the human's deliberate act."""
    member = (member or "").strip()
    role = _valid_role(role)
    rows = read_members(bus_state)
    changed = 0
    for rec in rows.values():
        if rec.get("member") == member and rec.get("role") != role:
            rec["role"] = role
            changed += 1
    if changed:
        _write_atomic(bus_state, rows)
    return changed


def forget(bus_state: Path, session_id: str) -> bool:
    rows = read_members(bus_state)
    if session_id in rows:
        del rows[session_id]
        _write_atomic(bus_state, rows)
        return True
    return False


def detect_collisions(live_bindings: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Two live sessions under one member (holobench, 2026-07-13). *"An identity derived from a
    LOCATION is not an identity — it is an ADDRESS, and two things can stand at one address."*

    The bus tag is derived from the working directory, so two Claude sessions started in the SAME
    repo post under one tag and are indistinguishable — for ~10 hours one day, two ``rt1180emulator``
    sessions with different memories shared a name and nobody noticed until Kyle spotted his own extra
    terminal. This is the ``orin``/``orin-agx`` split with the arrow reversed: there two names pointed
    at one board; here one name points at two sessions. Both are a non-injective identity, both silent.

    The invariant is clean because ``member`` binds to the unforgeable ``session_id``: a member with
    **two or more distinct live ``session_id``s** is a collision. Conductor is the reliable detector —
    it always sees every live session — so it shouts in the UI; ``bus.sh`` shouts a second time at
    session-start (the "even with Conductor off" path). Input: one dict per live session with
    ``member``/``session_id`` (extra keys like ``name``/``project`` are carried through for the UI).
    """
    by_member: dict[str, dict[str, dict[str, str]]] = {}
    for b in live_bindings:
        member = (b.get("member") or "").strip()
        sid = (b.get("session_id") or "").strip()
        if not member or not sid:
            continue
        by_member.setdefault(member, {})[sid] = b   # dedup by session_id — one session, one entry
    out: list[dict[str, Any]] = []
    for member, sessions in sorted(by_member.items()):
        if len(sessions) >= 2:
            out.append({"member": member, "count": len(sessions),
                        "sessions": list(sessions.values())})
    return out


def _valid_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role not in ROLES:
        raise ValueError(f"invalid role {role!r}; must be one of {ROLES}")
    return role


def members_summary(bus_state: Path) -> list[dict[str, Any]]:
    """Registry as a list for the API/UI, grouped by member (one entry per member with its role and
    the session_ids under it)."""
    rows = read_members(bus_state)
    by_member: dict[str, dict[str, Any]] = {}
    for sid, rec in rows.items():
        m = rec["member"]
        e = by_member.setdefault(m, {"member": m, "role": rec["role"],
                                     "project": rec.get("project", ""), "session_ids": []})
        e["session_ids"].append(sid)
        # a member's role should be consistent; surface the most-restrictive if not, defensively
        if ROLES.index(rec["role"]) < ROLES.index(e["role"]):
            e["role"] = rec["role"]
    return sorted(by_member.values(), key=lambda e: e["member"])
