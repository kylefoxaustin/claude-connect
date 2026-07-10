"""Coordination state Conductor reads from ``~/.claude/bus-state/coord/``.

Phase 1 has one kind of coordination record: **retractions**. When a session runs
``bus.sh retract <tag> "<why>"`` it drops a record here; Conductor wakes the target
*immediately* (overriding the busy guard — the target may be mid-action) so a bad
instruction can be pulled back before it's acted on.
"""

from __future__ import annotations

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
