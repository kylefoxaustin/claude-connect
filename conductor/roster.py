"""Fleet roster — the disaster-recovery pick-list.

The roster is the *source of truth for which Claudes exist* so they can be
recreated on a new machine (image_gen's DR ask, 2026-07-20). A "session" here is
a **cwd** (a project/repo), not a live process — the durable unit is the working
directory plus the transcript that ``claude --continue`` resumes from. Multiple
encoded ``~/.claude/projects`` dirs can resolve to the same cwd (re-encoded
across Claude versions); we group by resolved cwd and aggregate every transcript.

Per entry we record what a restore needs:
  • cwd + is_repo + git_remote/branch/head  → re-hook the repo from GitHub
  • tag / member                            → restore its bus identity
  • transcript_paths + transcript_bytes     → the --continue fuel to ship
  • last_active / tokens                     → so Kyle can choose what to bring back

The output is a plain dict (JSON-serialisable). It's generated on the live box
(Conductor's host) and committed into the private backup repo; the Reconstitute
screen reads it back on the new machine.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

from .scanner import derive_tag, last_recorded_cwd, newest_jsonl, parse_session_meta

# Mirrors scripts/token-usage.py — the four usage counters Claude Code records.
_TOKEN_KEYS = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)


def _usage_of(jsonl: Path) -> tuple[int, int, int]:
    """Return ``(output_tokens, total_tokens, turns)`` for one transcript."""
    out = total = turns = 0
    try:
        text = jsonl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, 0, 0
    for line in text.splitlines():
        try:
            o = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        msg = o.get("message") if isinstance(o, dict) else None
        u = msg.get("usage") if isinstance(msg, dict) else None
        if not isinstance(u, dict):
            continue
        turns += 1
        for k in _TOKEN_KEYS:
            v = u.get(k, 0)
            if isinstance(v, int):
                total += v
                if k == "output_tokens":
                    out += v
    return out, total, turns


def _git(cwd: str, *args: str) -> str | None:
    """Run ``git -C cwd <args>`` and return stripped stdout, or None on failure."""
    try:
        r = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    s = r.stdout.strip()
    return s or None


def _git_info(cwd: str) -> dict[str, object]:
    """Repo attribution for a cwd that exists on disk: remote, branch, HEAD.

    ``is_repo`` is False for a plain (non-git) dir — still recoverable, just
    restored from the transcript/working-tree rather than re-cloned. A cwd that
    no longer exists on disk yields ``exists=False`` (nothing to inspect).
    """
    info: dict[str, object] = {
        "exists": os.path.isdir(cwd),
        "is_repo": False,
        "git_remote": None,
        "git_branch": None,
        "git_head": None,
        "git_dirty": None,
    }
    if not info["exists"]:
        return info
    inside = _git(cwd, "rev-parse", "--is-inside-work-tree")
    if inside != "true":
        return info
    info["is_repo"] = True
    # Prefer origin; fall back to whatever the first remote is.
    remote = _git(cwd, "remote", "get-url", "origin")
    if remote is None:
        first = _git(cwd, "remote")
        if first:
            remote = _git(cwd, "remote", "get-url", first.splitlines()[0])
    info["git_remote"] = remote
    info["git_branch"] = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    info["git_head"] = _git(cwd, "rev-parse", "HEAD")
    # Uncommitted work does NOT survive a plain clone — flag it so the runbook /
    # UI can warn that the working tree itself must be in the snapshot.
    status = _git(cwd, "status", "--porcelain")
    info["git_dirty"] = bool(status)
    return info


def _project_dirs_by_cwd(projects_root: Path) -> dict[str, list[Path]]:
    """Group every project dir under ``projects_root`` by the resolved cwd its
    newest transcript last ran in. Value is the list of encoded project dirs that
    map to that cwd (usually one; more when re-encoded across versions)."""
    by_cwd: dict[str, list[Path]] = {}
    try:
        dirs = list(projects_root.iterdir())
    except OSError:
        return by_cwd
    for d in dirs:
        if not d.is_dir():
            continue
        jsonl = newest_jsonl(d)
        if jsonl is None:
            continue
        cwd = last_recorded_cwd(jsonl)
        if not cwd:
            continue
        by_cwd.setdefault(os.path.realpath(cwd), []).append(d)
    return by_cwd


def build_roster(
    projects_root: Path,
    tag_map: dict[str, str] | None = None,
    *,
    member_map: dict[str, str] | None = None,
) -> dict:
    """Build the fleet roster over every project dir under ``projects_root``.

    ``tag_map`` mirrors the bus.sh case-table (settings.toml ``[bus.tags]``) so
    the roster's tags match the live bus. ``member_map`` optionally maps a
    bracketed/bare tag to its durable member name (from ``bus-state/members``);
    absent, member defaults to the tag's bare form.
    """
    home = os.path.expanduser("~")
    entries: list[dict] = []
    for cwd, dirs in _project_dirs_by_cwd(projects_root).items():
        # Aggregate every transcript across all encoded dirs for this cwd.
        transcripts: list[Path] = []
        for d in dirs:
            try:
                transcripts.extend(sorted(p for p in d.glob("*.jsonl") if p.is_file()))
            except OSError:
                continue
        if not transcripts:
            continue
        newest = max(transcripts, key=lambda p: _safe_mtime(p))
        last_active = _safe_mtime(newest)
        total_bytes = sum(_safe_size(p) for p in transcripts)
        out_tok = tot_tok = turns = 0
        for t in transcripts:
            o, tt, tr = _usage_of(t)
            out_tok += o
            tot_tok += tt
            turns += tr
        session_id, title, _ = parse_session_meta(newest)
        tag = derive_tag(cwd, tag_map)
        bare = tag.strip("[]")
        member = None
        if member_map:
            member = member_map.get(tag) or member_map.get(bare)
        entries.append(
            {
                "tag": tag,
                "member": member or bare,
                "title": title,
                "session_id": session_id,
                "cwd": cwd,
                "project_dirs": [d.name for d in dirs],
                **_git_info(cwd),
                "last_active": last_active,
                "tokens_out": out_tok,
                "tokens_total": tot_tok,
                "turns": turns,
                "transcript_paths": [str(p) for p in transcripts],
                "transcript_bytes": total_bytes,
            }
        )
    entries.sort(key=lambda e: e["last_active"], reverse=True)
    return {
        "schema": 1,
        "host": socket.gethostname(),
        "home": home,
        "projects_root": str(projects_root),
        "session_count": len(entries),
        "sessions": entries,
    }


def _safe_mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _safe_size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return 0
