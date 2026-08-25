"""Shared-resource reservation state for the dashboard (generalizes the GPU tile).

Reads the named-resource leases that ``bus.sh res`` writes (under
``<bus-state>/resources/<name>/lease``) plus, for the ``gpu`` resource, live
``nvidia-smi`` telemetry — so Conductor can render a tile per shared resource
(the GPU, the IQ9 EVK, …).
"""

from __future__ import annotations

from .locks import exclusive
import time
from pathlib import Path
from typing import Any

from .gpu import query_nvidia_smi, read_lease
from .gpu_procs import gpu_processes


def touch_lease_activity(res_dir: Path, now: int | None = None) -> bool:
    """Refresh a lease's ``last_active_epoch`` — an activity heartbeat.

    A remote board has no telemetry, so the watchdog judges it idle by how long
    ago the owner ran ``/keep``. But a Claude deep in a long build never stops to
    heartbeat, so a *busy* holder's lease looks abandoned. Conductor knows the
    owner's session is working, so it heartbeats on their behalf.

    Takes the same ``flock`` on ``<res>/.lock`` that ``bus.sh`` uses, so this can
    never race a reserve/release/promote.
    """
    lease = res_dir / "lease"
    now = int(time.time()) if now is None else int(now)
    try:
        # The lock was previously released only by the handle closing. `exclusive` releases
        # on the way out of the block instead, which matters on Windows: a byte-range lock
        # leaked by an early `return` is not reclaimed as promptly as an flock is.
        with open(res_dir / ".lock", "a+") as lockf, exclusive(lockf):
            try:
                text = lease.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return False  # released underneath us
            out, seen = [], False
            for ln in text.splitlines():
                if ln.startswith("last_active_epoch="):
                    out.append(f"last_active_epoch={now}")
                    seen = True
                else:
                    out.append(ln)
            if not seen:
                out.append(f"last_active_epoch={now}")
            lease.write_text("\n".join(out) + "\n", encoding="utf-8")
            return True
    except OSError:
        return False


def _label(name: str) -> str:
    return "GPU" if name == "gpu" else name


def slim_resource_cards(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the resources payload with each asset card reduced to a stub.

    Asset cards are 99% of this payload (MEASURED 2026-08-16: 53.5 KB of 54.0 KB)
    and they are STATIC — yet they rode the 3 s broadcast because the 0.5 KB of
    lease/telemetry beside them ticks with GPU utilization. That is the scan-loop
    defect one layer up: *a payload mixing volatile and static data forces the
    static part to travel at the volatile rate.*

    A tile needs only ``has_access`` (to choose its label) and ``kind``. The body is
    read solely when the card modal opens, so it is fetched then, from
    ``/api/resources/<name>/card``. Pure function of its input so the wire format
    can be pinned by a test without standing up an AppState.

    The caller keeps the FULL payload server-side — only the wire gets the stub.
    """
    out = dict(payload)
    slim: list[dict[str, Any]] = []
    for r in out.get("resources", []):
        card = r.get("card")
        if not isinstance(card, dict):
            slim.append(r)
            continue
        r = dict(r)
        r["card"] = {
            "kind": card.get("kind"),
            "has_access": card.get("has_access", False),
            "deferred": True,          # body at /api/resources/<name>/card
        }
        slim.append(r)
    out["resources"] = slim
    return out


def resources_state(res_root: Path) -> dict[str, Any]:
    """One entry per shared resource: ``{name, label, smi|None, lease|None}``.

    The GPU is always included when ``nvidia-smi`` is present (so its tile shows
    utilization even when free); other resources appear once they've been used at
    least once (their lease dir exists).
    """
    entries: dict[str, dict[str, Any]] = {}

    smi = query_nvidia_smi()
    if smi is not None:
        entries["gpu"] = {
            "name": "gpu", "label": "GPU", "smi": smi,
            "lease": read_lease(res_root / "gpu"),
            # WHO IS ACTUALLY ON THE CARD. The lease describes intentions; nvidia-smi
            # describes reality. image_gen held the lease, found the GPU crowded anyway, and
            # had no way to learn that the 8.3 GB belonged to a live container of another
            # session — so it asked to kill it as "a stale leftover". A lease that can't see
            # the card it leases is a lease that lies by omission.
            "processes": gpu_processes(),
        }

    if res_root.is_dir():
        try:
            dirs = sorted(d for d in res_root.iterdir() if d.is_dir())
        except OSError:
            dirs = []
        for d in dirs:
            name = d.name
            if name in entries:
                entries[name]["lease"] = read_lease(d)  # refresh (gpu)
            else:
                entries[name] = {"name": name, "label": _label(name), "smi": None, "lease": read_lease(d)}

    return {"resources": list(entries.values())}
