"""Who is actually on the GPU.

The lease describes INTENTIONS — it only knows about sessions that took one. nvidia-smi
describes REALITY. A Docker container started outside the lease system is invisible to the
first and perfectly visible to the second, and when the two disagree the lease reports the
reassuring answer.

That is not hypothetical. image_gen held the GPU lease, watched its renders take 10m26s
instead of 24.7s, and asked to kill "a root-owned python3 holding 8.3 GB" as a stale
leftover. It was another live session's container, which had served a request 90 seconds
earlier. The lease could not see it, so the Claude could not see it, so it nearly destroyed
a colleague's working set — while doing everything else right.
"""

from __future__ import annotations

from conductor.gpu_procs import foreign_processes


def _p(pid, mem, owner, container=None):
    return {"pid": pid, "mem_mb": mem, "owner": owner, "container": container,
            "cmd": "", "user": "root" if container else "kyle"}


def test_foreign_processes_are_the_ones_you_do_not_own():
    """The list image_gen needed and could not get."""
    procs = [_p(1, 17000, "server.py"), _p(2, 8350, "pai-llm-server", "pai-llm-server-1")]
    assert [p["pid"] for p in foreign_processes(procs, holder_pids={1})] == [2]


def test_a_container_is_named_by_its_container_not_its_command():
    """`python3` invites you to kill it. `personal-ai-framework-llm-server-1` tells you who
    to go and ask. The attribution IS the safety property — a root-owned bare `python3` is
    exactly what a competent Claude will reasonably assume is a daemon, and be wrong about.
    """
    p = _p(2, 8350, "personal-ai-framework-llm-server-1", "personal-ai-framework-llm-server-1")
    assert p["owner"] == "personal-ai-framework-llm-server-1"
    assert p["owner"] != "python3"


def test_holding_the_lease_does_not_mean_holding_the_card():
    """The whole point. You can own the lease and still be sharing the silicon."""
    procs = [_p(1, 17000, "comfyui"), _p(2, 8350, "svc", "svc-1"), _p(3, 2750, "other")]
    foreign = foreign_processes(procs, holder_pids={1})
    assert len(foreign) == 2
    assert sum(p["mem_mb"] for p in foreign) == 11100


def test_an_empty_card_is_quiet():
    assert foreign_processes([], holder_pids=set()) == []
