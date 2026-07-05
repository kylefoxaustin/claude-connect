#!/usr/bin/env python3
"""Report Claude Code token usage from session transcripts.

Every assistant turn in ``~/.claude/projects/<proj>/<session>.jsonl`` records a
``usage`` block (the same numbers Claude Code shows per command). This sums them
per session and overall.

    python scripts/token-usage.py                    # every project under ~/.claude/projects
    python scripts/token-usage.py <project-dir>      # one project's sessions
    python scripts/token-usage.py <session.jsonl>    # a single session
    python scripts/token-usage.py --json             # machine-readable

Note on "out" vs "total": total = everything processed (input context + output);
out = just what the model generated. The gap is almost all *cache reads* — the
whole conversation is re-read as input every turn (cheap, but it makes "total"
balloon). So `out` = work done, `total` = raw tokens processed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


def usage_of(jsonl: Path) -> tuple[dict[str, int], int]:
    sums = {k: 0 for k in KEYS}
    turns = 0
    try:
        text = jsonl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return sums, 0
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
        for k in KEYS:
            v = u.get(k, 0)
            if isinstance(v, int):
                sums[k] += v
    return sums, turns


def human(n: int) -> str:
    n = n or 0
    for div, suf in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            return f"{n / div:.1f}{suf}"
    return str(n)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", nargs="?", help="a project dir, a .jsonl session, or omit for ALL projects")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    ap.add_argument("--projects-root", default=os.path.expanduser("~/.claude/projects"))
    args = ap.parse_args()

    if args.path:
        p = Path(args.path)
        files = [p] if p.is_file() else sorted(p.glob("*.jsonl")) if p.is_dir() else []
        if not files:
            print(f"no transcripts at {p}", file=sys.stderr)
            return 1
    else:
        root = Path(args.projects_root)
        files = sorted(root.glob("*/*.jsonl")) if root.is_dir() else []

    grand = {k: 0 for k in KEYS}
    gturns = 0
    rows = []
    for f in files:
        s, turns = usage_of(f)
        if not turns:
            continue
        gturns += turns
        for k in KEYS:
            grand[k] += s[k]
        rows.append({
            "project": f.parent.name, "session": f.stem, "turns": turns,
            "output": s["output_tokens"], "input": s["input_tokens"],
            "cache_creation": s["cache_creation_input_tokens"],
            "cache_read": s["cache_read_input_tokens"], "total": sum(s.values()),
        })

    gtotal = sum(grand.values())
    if args.json:
        print(json.dumps({"sessions": rows, "grand": {**grand, "turns": gturns, "total": gtotal}}, indent=2))
        return 0

    # Group by project for a readable table.
    rows.sort(key=lambda r: (r["project"], -r["total"]))
    last_proj = None
    for r in rows:
        # The project dir is Claude's encoded cwd (hyphens are ambiguous, so we
        # don't try to reverse it) — trim the common ~/.claude prefix for brevity.
        proj = r["project"]
        for pre in ("-home-", "-Users-", "-root-"):
            if proj.startswith(pre):
                proj = "~/" + proj[len(pre):].split("-", 1)[-1]
                break
        if proj != last_proj:
            print(f"\n{proj}")
            last_proj = proj
        print(f"  {r['session'][:12]:12}  turns={r['turns']:>5}  out={human(r['output']):>8}  total={human(r['total']):>8}")

    c = lambda n: f"{n:,}"
    print("\n" + "=" * 60)
    print(f"TOTAL across {len(rows)} session(s), {c(gturns)} turns:")
    print(f"  output generated : {c(grand['output_tokens'])}   ({human(grand['output_tokens'])})")
    print(f"  new input        : {c(grand['input_tokens'])}")
    print(f"  cache creation   : {c(grand['cache_creation_input_tokens'])}")
    print(f"  cache reads      : {c(grand['cache_read_input_tokens'])}   (context re-read each turn — cheap)")
    print(f"  ── total processed : {c(gtotal)}   ({human(gtotal)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
