"""Shared-resource reservation state for the dashboard (generalizes the GPU tile).

Reads the named-resource leases that ``bus.sh res`` writes (under
``<bus-state>/resources/<name>/lease``) plus, for the ``gpu`` resource, live
``nvidia-smi`` telemetry — so Conductor can render a tile per shared resource
(the GPU, the IQ9 EVK, …).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .gpu import query_nvidia_smi, read_lease


def _label(name: str) -> str:
    return "GPU" if name == "gpu" else name


def resources_state(res_root: Path) -> dict[str, Any]:
    """One entry per shared resource: ``{name, label, smi|None, lease|None}``.

    The GPU is always included when ``nvidia-smi`` is present (so its tile shows
    utilization even when free); other resources appear once they've been used at
    least once (their lease dir exists).
    """
    entries: dict[str, dict[str, Any]] = {}

    smi = query_nvidia_smi()
    if smi is not None:
        entries["gpu"] = {"name": "gpu", "label": "GPU", "smi": smi, "lease": read_lease(res_root / "gpu")}

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
