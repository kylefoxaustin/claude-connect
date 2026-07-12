"""Who is ACTUALLY on the GPU — reconciling the lease against reality.

The hole this closes was found by a Claude falling into it. `image_gen` held the GPU lease,
found its renders taking 10m26s instead of 24.7s, and had **no way to discover who else was
on the card**. So it asked Kyle whether it could kill pid 2776079 as "a stale leftover".

It was not a leftover. It was `personal-ai-framework-llm-server-1`, a Docker container that
had served a request 90 seconds earlier, belonging to another live session. image_gen was
about thirty seconds from killing a working set out from under a colleague.

**image_gen did everything right.** It took the lease. It measured. It found the card
crowded anyway. And then it hit a wall: *the lease system only describes the sessions that
took a lease.* A container started outside it is invisible. So the lease reports intentions
while `nvidia-smi` reports reality, and when those diverge **the lease reports the
reassuring one** — which is the failure shape this fleet has spent a lot of energy learning
to hate.

The fix is not to make the lease stricter. It's to make it HONEST: ask the card who is on
it, attribute each process to a session / container / user, and hand that to whoever holds
the lease. Then "who do I talk to?" has an answer that isn't "go ask Kyle".
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

log = logging.getLogger("conductor.gpu_procs")

_SMI = ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"]


def _docker_name(pid: int) -> str | None:
    """The container a pid belongs to, if any.

    A GPU process whose parent is containerd is the case that actually bit us: it runs as
    root, `ps` shows a bare `python3 llm_server.py`, and it looks for all the world like a
    stray system daemon. It isn't — it's someone's service.
    """
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8") as fh:
            cg = fh.read()
    except OSError:
        return None
    if "docker" not in cg and "containerd" not in cg:
        return None
    # The container id is the last 64-hex path segment in the cgroup line.
    cid = ""
    for part in cg.replace("/", "\n").split("\n"):
        part = part.strip().removesuffix(".scope").removeprefix("docker-")
        if len(part) == 64 and all(c in "0123456789abcdef" for c in part):
            cid = part
            break
    if not cid:
        return None
    try:
        out = subprocess.run(
            ["docker", "inspect", "--format", "{{.Name}}", cid],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().lstrip("/")
        return out or None
    except (subprocess.SubprocessError, OSError):
        return cid[:12]        # we know it's containerised even if docker won't tell us more


def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return " ".join(fh.read().decode("utf-8", "replace").split("\0")).strip()
    except OSError:
        return ""


def _owner_user(pid: int) -> str:
    try:
        import pwd
        return pwd.getpwuid(os.stat(f"/proc/{pid}").st_uid).pw_name
    except (OSError, KeyError, ImportError):
        return "?"


def gpu_processes(session_dirs: dict[int, str] | None = None) -> list[dict[str, Any]]:
    """Every process holding VRAM, with an attribution a human (or a Claude) can act on.

    ``session_dirs`` maps a live session's pid -> its project dir, so a GPU process launched
    from inside a Claude session can be named as that session rather than as "some python".
    """
    try:
        out = subprocess.run(_SMI, capture_output=True, text=True, timeout=8, check=True).stdout
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []                       # no nvidia-smi: not an error, just nothing to say

    procs: list[dict[str, Any]] = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2 or not parts[0].isdigit():
            continue
        pid = int(parts[0])
        try:
            mem = int(parts[1])
        except ValueError:
            mem = 0
        cmd = _cmdline(pid)
        container = _docker_name(pid)
        procs.append({
            "pid": pid,
            "mem_mb": mem,
            "cmd": cmd[:120],
            "user": _owner_user(pid),
            "container": container,
            # The name to put in front of a human. A container's name is the most useful
            # thing we have — "personal-ai-framework-llm-server-1" tells you who to talk to;
            # "python3" tells you nothing and invites you to kill it.
            "owner": container or _short(cmd) or f"pid {pid}",
        })
    procs.sort(key=lambda p: -p["mem_mb"])
    return procs


def _short(cmd: str) -> str:
    for part in cmd.split():
        if part.endswith(".py") or ("/" not in part and part not in ("python", "python3")):
            return os.path.basename(part)
    return ""


def foreign_processes(procs: list[dict[str, Any]], holder_pids: set[int]) -> list[dict[str, Any]]:
    """The processes on the card that the LEASE HOLDER does not own.

    This is the list image_gen needed and could not get. Everything here is someone else's
    work — so the answer to "why is my render slow" is a name you can go and ask, not a pid
    you're tempted to kill.
    """
    return [p for p in procs if p["pid"] not in holder_pids]
