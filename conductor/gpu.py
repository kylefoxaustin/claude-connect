"""GPU reservation state for the dashboard (Phase 3 of the bus GPU system).

Reads the cooperative lease that ``bus.sh gpu`` writes (``<bus-state>/gpu/lease``)
and live telemetry from ``nvidia-smi``, and merges them into one payload the GPU
tile renders. Read-only; if there's no GPU or no lease, it degrades gracefully.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any


def query_nvidia_smi() -> dict[str, Any] | None:
    """Live GPU telemetry for GPU 0, or None if nvidia-smi is unavailable."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0 or not out.stdout.strip():
        return None
    line = out.stdout.strip().splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    name, util, used, total = parts[0], parts[1], parts[2], parts[3]
    def _int(s: str) -> int:
        try:
            return int(float(s))
        except ValueError:
            return 0
    return {"name": name, "util": _int(util), "mem_used": _int(used), "mem_total": _int(total)}


def read_lease(gpu_dir: Path, now: float | None = None) -> dict[str, Any] | None:
    """Parse the current GPU lease, or None if free/expired/absent.

    Mirrors ``bus.sh``'s lazy expiry: an expired lease reads as free.
    """
    lease = gpu_dir / "lease"
    try:
        text = lease.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return None
    d: dict[str, str] = {}
    for ln in text.splitlines():
        k, sep, v = ln.partition("=")
        if sep:
            d[k.strip()] = v
    exp = d.get("expires_epoch", "")
    if not exp.isdigit():
        return None
    now = time.time() if now is None else now
    remaining = int(exp) - now
    if remaining <= 0:
        return None  # expired -> free
    idle_since = d.get("idle_since_epoch", "")
    idle = int(now - int(idle_since)) if idle_since.isdigit() else 0
    acq = d.get("acquired_epoch", "")
    nudged = d.get("nudged_epoch", "")
    mode = d.get("mode", "")
    queue = [t for t in d.get("queue", "").split(",") if t]  # waiting tags, FIFO
    return {
        "owner": d.get("owner", ""),
        "mode": mode,                       # "soft" | "hard" | "offer"
        "offered": mode == "offer",         # held-for-the-next-in-line, awaiting claim
        "job": d.get("job", ""),
        "remaining": int(remaining),
        "idle": max(0, idle),
        # Set by the watchdog. `idle_since_epoch` identifies one idle *episode*
        # (cleared on activity); `nudged_epoch` marks that it has posted a nudge.
        "idle_since_epoch": int(idle_since) if idle_since.isdigit() else None,
        "nudged_epoch": int(nudged) if nudged.isdigit() else None,
        "queue": queue,                     # who's waiting, in order
        "requested_by": (queue[0] if queue else None),  # next in line (back-compat)
        "expires_epoch": int(exp),
        "acquired_epoch": int(acq) if acq.isdigit() else None,
    }


def gpu_state(gpu_dir: Path) -> dict[str, Any]:
    """Combined payload for the GPU tile: telemetry + current lease."""
    smi = query_nvidia_smi()
    return {
        "available": smi is not None,
        "smi": smi,
        "lease": read_lease(gpu_dir),
    }
