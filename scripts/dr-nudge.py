#!/usr/bin/env python3
"""DR nudge — remind LIVE sessions with uncommitted work to commit + push.

Kyle's disaster-recovery policy (2026-07-21): the backup recovers repos by CLONE, so
uncommitted work is lost unless it's committed+pushed. Rather than tar every working tree
into the backup, we nudge the sessions to push. This posts one directed `[operator]` bus
message to the currently-live sessions whose repo is dirty, listing each repo, and (with
--ping) wakes them to read it. Throttled so it can't nag.

    python scripts/dr-nudge.py            # nudge live dirty sessions (throttled)
    python scripts/dr-nudge.py --dry-run  # show who WOULD be nudged, send nothing
    python scripts/dr-nudge.py --ping      # also inject /msg-check into each recipient
    python scripts/dr-nudge.py --force     # ignore the throttle

Needs Conductor running (it posts through /api/bus/send, so the message is a clean
[operator] post, not one under some random cwd tag).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from conductor.roster import build_roster  # noqa: E402
from conductor.settings import load_settings  # noqa: E402

THROTTLE_HOURS = 12.0
STATE = Path(os.path.expanduser("~/.claude/bus-state/dr-nudge-state.json"))


def _api(base: str, token: str, path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("X-Conductor-Token", token)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "{}")


def _get(base: str, token: str, path: str) -> dict:
    req = urllib.request.Request(base + path)
    if token:
        req.add_header("X-Conductor-Token", token)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode() or "{}")


def _load_throttle() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def main() -> int:
    ap = argparse.ArgumentParser(description="Nudge live dirty sessions to commit+push (DR).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ping", action="store_true", help="inject /msg-check into recipients")
    ap.add_argument("--force", action="store_true", help="ignore the per-session throttle")
    ap.add_argument("--hours", type=float, default=THROTTLE_HOURS)
    args = ap.parse_args()

    s = load_settings()
    base = f"http://{s.server.host}:{s.server.port}"
    token = os.environ.get("CONDUCTOR_AUTH_TOKEN") or s.server.auth_token or ""

    # Which sessions are LIVE right now (a bus nudge only helps a running session).
    try:
        ops = _get(base, token, "/api/ops")
    except urllib.error.URLError as e:
        print(f"Conductor not reachable at {base} ({e}). Is the service running?", file=sys.stderr)
        return 2
    live_tags = {(sess.get("tag") or "").strip("[]").lower()
                 for sess in ops.get("sessions", [])}

    roster = build_roster(s.scanner.claude_home_path / "projects", s.bus.tags)
    dirty = [e for e in roster["sessions"]
             if e["git_dirty"] and e["git_remote"]
             and e["tag"].strip("[]").lower() in live_tags]

    if not dirty:
        print("No live session has uncommitted work. Nothing to nudge.")
        return 0

    throttle = _load_throttle()
    now = time.time()
    horizon = args.hours * 3600
    fresh = [e for e in dirty
             if args.force or (now - throttle.get(e["tag"], 0)) >= horizon]

    if not fresh:
        print(f"All {len(dirty)} dirty session(s) were nudged within {args.hours}h "
              f"(use --force to override).")
        return 0

    recipients = [e["tag"] for e in fresh]
    lines = ["🧯 DR reminder — you have UNCOMMITTED work that a rebuild-from-backup would "
             "LOSE (recovery clones from GitHub, so only committed+pushed work comes back). "
             "Please commit + push when it's at a good stopping point:"]
    for e in fresh:
        head = (e["git_head"] or "")[:8]
        lines.append(f"  • {e['tag']}: {e['cwd']} (backup currently has only {head})")
    lines.append("Not urgent — just don't leave it uncommitted overnight. — DR/operator")
    text = "\n".join(lines)

    if args.dry_run:
        print("DRY-RUN — would post to:", ", ".join(recipients))
        print(text)
        return 0

    resp = _api(base, token, "/api/bus/send",
                {"text": text, "recipients": recipients, "ping": args.ping})
    ok = resp.get("ok", True)
    for e in fresh:
        throttle[e["tag"]] = now
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(throttle))
    print(f"Nudged {len(fresh)} session(s): {', '.join(recipients)}"
          + (f" · pinged {resp.get('pinged')}" if args.ping else "")
          + ("" if ok else "  (send reported not-ok — check Conductor)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
