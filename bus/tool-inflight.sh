#!/usr/bin/env bash
# tool-inflight.sh — mark that a session has a tool in flight, so Conductor never types
# a confirming keystroke into a permission prompt.
#
# THE BUG THIS CLOSES
# -------------------
# A session blocked on a Bash/Edit permission prompt ("Dangerous rm … — 1. Yes / 2. No",
# cursor on Yes) STOPS writing its transcript. Its status therefore decays IDLE/WAITING,
# and Conductor treats IDLE/WAITING as wakeable — so an auto-delivery or a ping button types
# `/msg-check` + **Return** into it. Return confirms the highlighted default, which is *Yes*.
# Conductor can approve a destructive command merely by trying to deliver mail.
#
# WHY A HOOK AND NOT THE TRANSCRIPT (the same reason as ask-capture.sh)
# --------------------------------------------------------------------
# Claude Code does not flush the assistant message until the tool completes, so while a
# permission prompt is on screen there is NOTHING on disk that distinguishes "blocked on a
# human" from "idle at a ready prompt". They are transcript-identical. Only a marker written
# at PreToolUse — *before* the prompt can appear — carries the fact at the one moment it is
# knowable.
#
# CONTRACT
#   * capture (PreToolUse): write coord/inflight/<sid> with the start time + transcript path.
#   * resolve (PostToolUse): remove it, whoever/however the tool ended (ran, or denied).
#   * Conductor ALSO self-clears: it ignores a marker once the session's transcript has
#     advanced past started_epoch, so a marker orphaned by a denied tool (PostToolUse may not
#     fire) or a crash can never wedge the guard shut. The marker is an ACCELERATOR of the
#     ground truth, never the only signal — the same discipline as every other wake path.
#   * ALWAYS exits 0. A guard-support hook must never be able to block a tool or fail a
#     session; worst case it writes nothing and the transcript-advance backstop still holds.
set -uo pipefail

STATE_DIR="${BUS_STATE_DIR:-$HOME/.claude/bus-state}"
INFLIGHT_DIR="$STATE_DIR/coord/inflight"

PAYLOAD="$(cat 2>/dev/null || true)"
[ -n "$PAYLOAD" ] || exit 0

mkdir -p "$INFLIGHT_DIR" 2>/dev/null || exit 0

MODE="${1:-capture}"

# Payload rides in the ENVIRONMENT, not a pipe: `python3 -` reads its program from stdin, so
# a heredoc and a piped payload cannot coexist (the heredoc wins and the payload is eaten —
# the ask-capture.sh lesson, which failed as exit-0-and-do-nothing, the worst way).
INFLIGHT_PAYLOAD="$PAYLOAD" python3 - "$INFLIGHT_DIR" "$MODE" <<'PY' 2>/dev/null || true
import json, os, re, sys, time

inflight_dir, mode = sys.argv[1], sys.argv[2]
try:
    p = json.loads(os.environ["INFLIGHT_PAYLOAD"])
except Exception:
    sys.exit(0)

sid = (p.get("session_id") or "").strip()
if not sid:
    sys.exit(0)
# sids are uuids, but never trust an id straight into a path.
safe = re.sub(r"[^A-Za-z0-9._-]", "_", sid)
path = os.path.join(inflight_dir, safe)

if mode == "resolve":
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    sys.exit(0)

# capture: only the tools that can raise a permission prompt / block on a human. (Read/Grep/
# etc. never gate, so marking them would only add false "busy" windows.)
tool = p.get("tool_name") or ""
if tool not in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"):
    sys.exit(0)

lines = [
    f"session_id={sid}",
    f"cwd={p.get('cwd') or ''}",
    f"tool={tool}",
    f"started_epoch={int(time.time())}",
    f"transcript={p.get('transcript_path') or ''}",
]
tmp = path + ".tmp"
try:
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, path)          # atomic — Conductor must never read a half-written marker
except OSError:
    sys.exit(0)
PY

exit 0
