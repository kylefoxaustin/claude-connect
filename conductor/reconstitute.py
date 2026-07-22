"""Reconstitute plan — the DR capstone's logic (fresh-machine fleet rebuild).

Given a ``fleet-roster.json`` (from a restored fleet-backup) and the CURRENT machine's
state (which cwds exist on disk, which sessions are live), decide — per session — what it
takes to bring it back:

  * ``live``            — a session is already running there; nothing to do.
  * ``present``         — the cwd exists but no session is running; just relaunch it
                          (`claude --continue`). Its transcript is checked for.
  * ``clone``           — a git repo whose cwd isn't on disk yet; clone it, then relaunch.
  * ``transcript-only`` — no repo to clone and the cwd is gone; recreate the dir and resume
                          the conversation (code is not recoverable, the transcript is).
  * ``blocked``         — nothing to restore into (no repo, no cwd, no transcript).

This is a PURE function of (roster, live_cwds, filesystem) so it is fully testable off the
target machine — the executor (clone → place transcript → relaunch) runs the steps.
"""

from __future__ import annotations

import os
from typing import Any


def _transcripts_present(entry: dict) -> bool:
    """True if at least one of this session's transcripts exists on disk (the
    ``--continue`` fuel). On a fresh box they're extracted from the transcript
    release asset before launch; if none are here, we surface that as a blocker."""
    paths = entry.get("transcript_paths") or []
    return any(os.path.isfile(p) for p in paths)


def plan_for(entry: dict, live_cwds: set[str]) -> dict[str, Any]:
    """The reconstitute plan for one roster session. ``live_cwds`` is the set of
    realpath'd cwds that currently have a live Claude process."""
    cwd = entry.get("cwd") or ""
    real = os.path.realpath(cwd) if cwd else ""
    on_disk = bool(cwd) and os.path.isdir(cwd)
    is_repo = bool(entry.get("is_repo"))
    remote = entry.get("git_remote")
    have_tx = _transcripts_present(entry)

    steps: list[str] = []
    blockers: list[str] = []

    if real and real in live_cwds:
        status = "live"
    elif on_disk:
        status = "present"
        steps.append(f"relaunch `claude --continue` in {cwd}")
    elif is_repo and remote:
        status = "clone"
        steps.append(f"git clone {remote} {cwd}")
        if entry.get("git_branch"):
            steps.append(f"git checkout {entry['git_branch']}")
        steps.append(f"relaunch `claude --continue` in {cwd}")
    elif have_tx:
        # No repo (plain dir) or the repo's cwd is gone, but we have its transcript.
        status = "transcript-only"
        steps.append(f"recreate dir {cwd}")
        steps.append(f"relaunch `claude --continue` in {cwd}")
    else:
        status = "blocked"
        blockers.append("no repo to clone, no cwd on disk, and no transcript to resume")

    # Transcript availability matters for every launchable status (it's the --continue fuel).
    if status in ("present", "clone", "transcript-only") and not have_tx:
        blockers.append("transcript not found — extract the fleet-transcripts asset first, "
                        "or it resumes as a blank session")
    if is_repo and entry.get("git_dirty"):
        blockers.append("backup has this repo's committed HEAD only — any uncommitted work "
                        "at snapshot time is not recoverable")

    return {
        "tag": entry.get("tag"),
        "member": entry.get("member"),
        "cwd": cwd,
        "status": status,
        "is_repo": is_repo,
        "git_remote": remote,
        "git_branch": entry.get("git_branch"),
        "git_head": entry.get("git_head"),
        "git_dirty": bool(entry.get("git_dirty")),
        "last_active": entry.get("last_active"),
        "tokens_out": entry.get("tokens_out"),
        "transcript_bytes": entry.get("transcript_bytes"),
        "transcripts_present": have_tx,
        "steps": steps,
        "blockers": blockers,
        "recoverable": status != "blocked",
    }


def build_plan(roster: dict, live_cwds: set[str]) -> dict[str, Any]:
    """Whole-fleet reconstitute plan from a roster + the current live cwds.

    Sorted so the sessions that still NEED action come first (newest-active within that),
    and the already-``live`` ones sink to the bottom."""
    sessions = [plan_for(e, live_cwds) for e in roster.get("sessions", [])]
    order = {"clone": 0, "present": 1, "transcript-only": 2, "blocked": 3, "live": 4}
    sessions.sort(key=lambda p: (order.get(p["status"], 9), -(p.get("last_active") or 0)))
    counts: dict[str, int] = {}
    for p in sessions:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {
        "host": roster.get("host"),
        "home": roster.get("home"),
        "session_count": len(sessions),
        "counts": counts,
        "sessions": sessions,
    }
