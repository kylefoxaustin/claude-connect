"""Autonomy windows — "for the next N hours, these Claudes may talk to each other".

The problem this solves. Auto-delivery already wakes a session that has unread mail
addressed to it… but only when it's IDLE/DORMANT. A session parked quietly at its
prompt is **WAITING**, and WAITING is deliberately never woken, because *Kyle might be
typing at that prompt*. That guard is right when he's at the keyboard — and worthless
when he's asleep. Since WAITING is the resting state of virtually every quiet session,
the guard is exactly what forces him to hand-click "check msgs" across 30+ sessions.

So an autonomy window is a **permission slip**, not a new subsystem:

    "I am not at these keyboards for the next N hours. Let them wake each other."

A window is a set of session tags + an expiry. While it's live, a member may be woken
by directed (``to:<tag>``) mail from a *fellow member* even when it's WAITING. Nothing
else changes:

  * BUSY (active/warm) is still never interrupted — the window lifts the *attended*
    guard, not the *working* guard.
  * Only directed mail wakes anyone. Broadcasts still wake nobody, so a fleet-wide
    window cannot storm itself.
  * It **expires**. The time-box is the safety property.

Safety rests on guardrails that already exist: nothing reaches a repo without a human
click (the push gate), and a bad instruction can be pulled back (retraction).
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

_STORE = "autonomy.json"


def _plain(tag: str) -> str:
    """Normalize a tag for membership tests: ``[other:qualcomm]`` == ``qualcomm``."""
    t = (tag or "").strip().strip("[]")
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()


def read_windows(coord_root: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Active (unexpired) windows, newest first. Expired ones are simply ignored —
    they're pruned on the next write."""
    now = time.time() if now is None else now
    try:
        raw = json.loads((coord_root / _STORE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for w in raw:
        if not isinstance(w, dict):
            continue
        try:
            expires = float(w.get("expires", 0))
            members = [str(m) for m in (w.get("members") or [])]
        except (TypeError, ValueError):
            continue
        if expires <= now or len(members) < 2:
            continue  # dead, or too small to mean anything
        out.append({
            "id": str(w.get("id", "")),
            "members": members,
            "expires": expires,
            "created": float(w.get("created", 0) or 0),
        })
    out.sort(key=lambda w: w["created"], reverse=True)
    return out


def write_windows(coord_root: Path, windows: list[dict[str, Any]]) -> None:
    """Best-effort atomic persist. Never raises — this must not break a scan."""
    try:
        coord_root.mkdir(parents=True, exist_ok=True)
        tmp = coord_root / (_STORE + ".tmp")
        tmp.write_text(json.dumps(windows), encoding="utf-8")
        tmp.replace(coord_root / _STORE)
    except OSError:
        pass


def open_window(coord_root: Path, members: list[str], hours: float,
                now: float | None = None) -> dict[str, Any]:
    """Open a window over ``members`` for ``hours``. Replaces nothing — windows
    compose, so the emulator crew and a qualcomm↔imx95 pair can run side by side."""
    now = time.time() if now is None else now
    hours = max(0.05, min(24.0, float(hours)))          # 3 min .. 24 h
    win = {
        "id": uuid.uuid4().hex[:12],
        "members": list(dict.fromkeys(members)),        # de-dupe, keep order
        "expires": now + hours * 3600.0,
        "created": now,
    }
    existing = read_windows(coord_root, now)            # drops expired ones on write
    write_windows(coord_root, [win, *existing])
    return win


def close_window(coord_root: Path, window_id: str, now: float | None = None) -> bool:
    """End a window early. True if one was actually removed."""
    now = time.time() if now is None else now
    existing = read_windows(coord_root, now)
    keep = [w for w in existing if w["id"] != window_id]
    if len(keep) == len(existing):
        return False
    write_windows(coord_root, keep)
    return True


def peers_in_window(windows: list[dict[str, Any]], tag: str) -> set[str]:
    """Plain names that share an active window with ``tag``.

    These are the peers allowed to wake it while it's merely WAITING (parked at its
    prompt). Empty set ⇒ no autonomy: the normal guard applies.
    """
    me = _plain(tag)
    peers: set[str] = set()
    for w in windows:
        plains = {_plain(m) for m in w["members"]}
        if me in plains:
            peers |= plains - {me}
    return peers
