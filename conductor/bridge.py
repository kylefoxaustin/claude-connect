"""Read Claude Code's per-session registry — the ground truth for *"is this session
remote-controlled (on the phone)"*.

Claude Code writes ``~/.claude/sessions/<pid>.json`` for each live session. Its
``bridgeSessionId`` is ``null`` until ``/rc`` (``/remote-control``) bridges the session
to claude.ai; once bridged it holds a ``session_…`` id and the session appears on the
phone. That field is the only honest signal of the bridge state from *outside* the TUI —
which is exactly what lets Conductor confirm a reconnect worked with no display attached
(found live 2026-07-17: an /rc injected mid-turn queues and silently fails to bridge, and
bridgeSessionId null->set is how we could tell the difference).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def sessions_dir() -> Path:
    return Path.home() / ".claude" / "sessions"


def read_bridge(pid: int | None, sdir: Path | None = None) -> dict[str, Any]:
    """``{"bridged": bool, "bridge_id": str|None, "cc_status": str|None}`` for a live pid.

    Best-effort: a missing, unreadable, or half-written file yields ``bridged=False`` — the
    SAFE default, because "not sure it's bridged" should OFFER a reconnect, never hide one.
    ``cc_status`` is Claude Code's own idea of the session's state (idle/busy/waiting), a
    second opinion alongside Conductor's activity-derived status.
    """
    out: dict[str, Any] = {"bridged": False, "bridge_id": None, "cc_status": None}
    if not pid:
        return out
    try:
        d = json.loads(((sdir or sessions_dir()) / f"{pid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if not isinstance(d, dict):
        return out
    bid = d.get("bridgeSessionId")
    out["bridge_id"] = bid if (isinstance(bid, str) and bid) else None
    out["bridged"] = out["bridge_id"] is not None
    st = d.get("status")
    out["cc_status"] = st if isinstance(st, str) else None
    return out
