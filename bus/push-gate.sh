#!/usr/bin/env bash
# Claude Code PreToolUse(Bash) hook — gate `git push` behind Kyle's one-click OK.
#
# Design constraints (this runs on EVERY Bash tool call in EVERY session):
#   • Instant no-op for anything that isn't a git push — the first thing it does is
#     a single grep; if the command doesn't even contain "push", exit 0 immediately
#     (no python, no git, no file I/O). Non-push commands are never touched.
#   • A `git push` is ALLOWED iff a valid, unexpired approval token exists — which it
#     then CONSUMES (one push per approval). Otherwise DENIED (exit 2, reason on
#     stderr → Claude sees it) and a request is filed for Conductor's inbox.
#   • Fail-safe: commits/branches/everything-else always pass; only pushes are gated.
#
# Approve from Conductor (the inbox) or the CLI:  bus.sh push approve <repo-name>
set -uo pipefail

COORD="${COORD_STATE_DIR:-$HOME/.claude/bus-state/coord}"
TOKENS="$COORD/push-tokens"
REQUESTS="$COORD/push-requests"

INPUT="$(cat 2>/dev/null || true)"

# ---- fast path: not even a mention of "push" -> allow instantly (no python) -----
printf '%s' "$INPUT" | grep -q 'push' || exit 0

# ---- parse the tool call (only for commands that mention push) -------------------
# Emits 3 lines: the SESSION's cwd, the directory the push actually runs in, then
# the command (rest of stream, newlines preserved — bash can't hold NUL in a var).
#
# Those first two differ more often than you'd think: `cd /elsewhere && git push`
# or `git -C /elsewhere push` pushes a DIFFERENT repo than the one the session is
# sitting in. Keying the gate off the session's cwd mislabels the request ("image_gen
# wants to push" when it's really pushing ai-image) and keys the token to the wrong
# repo. So: attribute the repo from the EFFECTIVE dir, but keep the session cwd so
# Conductor can find the Claude that asked and tell it when it's approved.
read -r -d '' _PY <<'PY' || true
import json, os, re, sys
try:
    d = json.load(sys.stdin)
    cwd = d.get("cwd", "") or ""
    cmd = (d.get("tool_input") or {}).get("command", "") or ""
except Exception:
    sys.stdout.write("\n\n")
    raise SystemExit

eff = cwd
m = re.search(r'\bgit\s+(?:-(?!C\b)[^\s]+\s+)*-C\s+([^\s;&|]+)', cmd)
if m:                                   # `git -C <dir> ... push`
    eff = m.group(1)
else:                                   # last `cd <dir>` before the push
    at = re.search(r'(^|[;&|(])\s*git\b[^;&|]*\bpush\b', cmd)
    head = cmd[:at.start()] if at else cmd
    cds = re.findall(r'(?:^|[;&|(&])\s*cd\s+([^\s;&|]+)', head)
    if cds:
        eff = cds[-1]

eff = os.path.expanduser(eff.strip().strip('"').strip("'"))
if not os.path.isabs(eff):
    eff = os.path.join(cwd or os.getcwd(), eff)

sys.stdout.write((cwd or "") + "\n")
sys.stdout.write(os.path.normpath(eff) + "\n")
sys.stdout.write(cmd)
PY
_parsed="$(printf '%s' "$INPUT" | python3 -c "$_PY" 2>/dev/null || printf '\n\n')"
CWD="$(printf '%s' "$_parsed" | sed -n 1p)"       # the session's cwd
PUSHDIR="$(printf '%s' "$_parsed" | sed -n 2p)"   # where the push actually runs
CMD="$(printf '%s' "$_parsed" | tail -n +3)"
[ -n "$CWD" ] || CWD="$PWD"
[ -n "$PUSHDIR" ] || PUSHDIR="$CWD"

# Gate only a real `git [opts] push` INVOCATION — i.e. `git` at a command position
# (start of a line, or right after ; & | && || or `(`), not "git push" sitting
# inside a quoted argument (echo "...", a commit message, this very announcement).
# CMD keeps its newlines, and grep is line-oriented, so a push on its own line in a
# multi-line command still matches.
printf '%s' "$CMD" | grep -Eq '(^|[;&|(])[[:space:]]*git([[:space:]]+(-[^[:space:]]+|-C[[:space:]]+[^[:space:]]+))*[[:space:]]+push([[:space:]]|$)' || exit 0

# ---- it's a git push: require a valid approval token ----------------------------
# Attribute to the repo the push actually TARGETS (PUSHDIR), not the session's cwd —
# so the request Kyle sees names the real repo, and the token is keyed to it.
REPO="$(git -C "$PUSHDIR" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PUSHDIR")"
NAME="$(basename "$REPO")"
KEY="$(printf '%s' "$REPO" | tr '/ ' '__' | sed 's/^_*//')"
now="$(date +%s)"

TOK="$TOKENS/$KEY"
if [ -f "$TOK" ]; then
  exp="$(cat "$TOK" 2>/dev/null || echo 0)"; case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
  rm -f "$TOK"                                   # consume — one push per approval
  if [ "$now" -lt "$exp" ]; then
    rm -f "$REQUESTS/$KEY" 2>/dev/null || true   # clear the (now-satisfied) request
    exit 0                                       # ALLOW (proceeds via normal perms)
  fi
fi

# no valid token -> file a request Conductor surfaces, and DENY this push
mkdir -p "$REQUESTS" 2>/dev/null || true
{ echo "repo=$REPO"; echo "repo_name=$NAME"; echo "cwd=$CWD"
  echo "cmd=$CMD"; echo "epoch=$now"; echo "created=$(date '+%Y-%m-%d %H:%M')"; } > "$REQUESTS/$KEY" 2>/dev/null || true
echo "🛑 Push to '$NAME' needs Kyle's approval (commits are fine — only pushes are gated). Requested in Conductor's push inbox; approve there or Kyle runs 'bus.sh push approve $NAME', then re-run this push." >&2
exit 2
