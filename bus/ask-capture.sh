#!/usr/bin/env bash
# ask-capture.sh — surface a Claude's pending AskUserQuestion so a human can answer it
# from anywhere (the phone, another room), instead of having to walk to the PC.
#
# WHY A HOOK AND NOT THE TRANSCRIPT
# ---------------------------------
# The obvious plan was to read pending asks out of `~/.claude/projects/*/*.jsonl`. It does
# not work, and it fails in the worst possible way: **Claude Code does not flush the
# assistant message until the tool completes.** So while a picker is on screen and the
# session is genuinely blocked on a human, there is NOTHING on disk. The ask only appears
# once it has been answered.
#
# A transcript-driven decision queue would therefore show you exactly the questions that no
# longer need answering, and would be silent about every question that does. It would look
# like it worked. (Measured, not assumed — see docs/DECISION_QUEUE.md.)
#
# A PreToolUse hook fires BEFORE the tool runs and is handed the full `tool_input`, so we
# get the question, the options and the multiSelect flag at the only moment they matter.
#
# CONTRACT
#   * Fires on AskUserQuestion only. Always exits 0 — this hook can never block a tool,
#     never gate anything, and never fails a session. Worst case it writes nothing.
#   * One pending ask per session (a blocked session cannot ask twice), so the record is
#     keyed on session_id and naturally supersedes itself.
#   * PostToolUse removes the record whoever answered it — phone, or Kyle at the keyboard.
set -uo pipefail

STATE_DIR="${BUS_STATE_DIR:-$HOME/.claude/bus-state}"
DEC_DIR="$STATE_DIR/coord/decisions"

# Stdin is the hook payload. Slurp it once; if anything at all goes wrong from here on,
# we exit 0 quietly — an observability feature must never be able to break the fleet.
PAYLOAD="$(cat 2>/dev/null || true)"
[ -n "$PAYLOAD" ] || exit 0

mkdir -p "$DEC_DIR" 2>/dev/null || exit 0

MODE="${1:-capture}"

# NOTE: the payload goes through the ENVIRONMENT, not a pipe. `python3 -` reads its
# program from stdin, so a heredoc and a piped payload cannot coexist — the heredoc wins
# and the payload is silently eaten. (Cost me a test run; it fails as exit-0-and-do-nothing,
# which is the worst way for a hook to fail.)
ASK_PAYLOAD="$PAYLOAD" python3 - "$DEC_DIR" "$MODE" <<'PY' 2>/dev/null || true
import json, os, sys, time

dec_dir, mode = sys.argv[1], sys.argv[2]
try:
    p = json.loads(os.environ["ASK_PAYLOAD"])
except Exception:
    sys.exit(0)

sid = (p.get("session_id") or "").strip()
if not sid or p.get("tool_name") != "AskUserQuestion":
    sys.exit(0)

path = os.path.join(dec_dir, f"{sid}.json")

if mode == "resolve":
    # Answered — by the phone, or by Kyle at the keyboard. Either way it's gone.
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    sys.exit(0)

qs = ((p.get("tool_input") or {}).get("questions")) or []
if not qs:
    sys.exit(0)

rec = {
    "session_id": sid,
    "cwd": p.get("cwd") or "",
    "transcript": p.get("transcript_path") or "",
    "asked_epoch": time.time(),
    "questions": [
        {
            "question": q.get("question") or "",
            "header": q.get("header") or "",
            "multiSelect": bool(q.get("multiSelect")),
            "options": [
                {"label": o.get("label") or "", "description": o.get("description") or ""}
                for o in (q.get("options") or [])
            ],
        }
        for q in qs
    ],
}

# Atomic: Conductor polls this directory and must never read a half-written record.
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(rec, fh)
os.replace(tmp, path)
PY

exit 0
