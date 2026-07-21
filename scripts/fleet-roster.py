#!/usr/bin/env python3
"""Emit the fleet roster — the disaster-recovery pick-list.

The roster is the source of truth for *which Claudes exist* so they can be
reconstituted on a new machine: per session its cwd, git remote/branch/HEAD,
tag/member, transcripts (the ``--continue`` fuel), last-active, and tokens.

    python scripts/fleet-roster.py                 # human summary
    python scripts/fleet-roster.py --json          # the full roster (for the backup repo)
    python scripts/fleet-roster.py -o roster.json  # write it to a file

Run on the live box (Conductor's host); commit the JSON into the private backup
repo. The Reconstitute screen reads it back on the new machine. Reads
settings.toml for the ``[bus.tags]`` map and ``~/.claude/bus-state/members`` for
tag→member, so the roster matches the live bus identities.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Import the conductor package that sits next to this scripts/ dir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conductor.roster import build_roster  # noqa: E402
from conductor.settings import load_settings  # noqa: E402


def _human(n: int) -> str:
    n = n or 0
    for div, suf in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            return f"{n / div:.1f}{suf}"
    return str(n)


def _load_member_map(state_dir: Path) -> dict[str, str]:
    """Map ``project`` (bare tag) -> durable ``member`` from bus-state/members.

    Handles the divergent case (e.g. a cwd basename ``keyhole`` whose member is
    ``backend``); for the common case member == bare tag and this is a no-op.
    """
    members = state_dir / "members"
    out: dict[str, str] = {}
    try:
        for line in members.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            cols = line.split("\t")
            if len(cols) >= 4 and cols[1] and cols[3]:
                out[cols[3]] = cols[1]  # project -> member
    except OSError:
        pass
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Emit the fleet disaster-recovery roster.")
    ap.add_argument("--json", action="store_true", help="print the full roster as JSON")
    ap.add_argument("-o", "--output", metavar="FILE", help="write JSON to FILE")
    ap.add_argument(
        "--settings", metavar="FILE", help="settings.toml path (default: ./settings.toml)"
    )
    args = ap.parse_args()

    settings = load_settings(args.settings)
    projects_root = settings.scanner.claude_home_path / "projects"
    if not projects_root.is_dir():
        print(f"no projects dir at {projects_root}", file=sys.stderr)
        return 2

    member_map = _load_member_map(settings.bus.state_dir_resolved)
    roster = build_roster(projects_root, settings.bus.tags, member_map=member_map)

    if args.output:
        Path(os.path.expanduser(args.output)).write_text(
            json.dumps(roster, indent=2) + "\n", encoding="utf-8"
        )
        print(f"wrote {roster['session_count']} sessions -> {args.output}", file=sys.stderr)
        return 0
    if args.json:
        print(json.dumps(roster, indent=2))
        return 0

    # Human summary.
    print(f"Fleet roster — {roster['host']}  ({roster['session_count']} sessions)")
    print(f"  home: {roster['home']}")
    print()
    for e in roster["sessions"]:
        repo = "—"
        if e["is_repo"]:
            repo = e["git_remote"] or "(local repo, no remote)"
            if e["git_dirty"]:
                repo += "  ⚠ dirty"
        elif not e["exists"]:
            repo = "⚠ cwd gone (transcript-only)"
        else:
            repo = "(plain dir, not a repo)"
        print(f"  {e['member']:<24} {_human(e['tokens_out']):>7} out  {_human(e['transcript_bytes']):>7}B")
        print(f"    {e['cwd']}")
        print(f"    {repo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
