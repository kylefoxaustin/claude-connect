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

# ---- exemption: the private disaster-recovery backup repo auto-pushes ------------
# Kyle's policy (2026-07-21): fleet-backup is EXEMPT from the gate. Its entire value
# is being CURRENT + off-box; a snapshot that needs a manual tap every hour goes
# stale and fails exactly when the disaster hits (the "notification must never be the
# only door" trap, applied to backups). There is no product code here to protect.
# SPOOF-RESISTANT BY DESIGN: we match the repo's ORIGIN REMOTE against the real
# GitHub slug, NOT the directory basename — a stray `mkdir fleet-backup` with no
# remote (or a different remote) is NOT exempt and still hits the gate.
FLEET_BACKUP_SLUG="${FLEET_BACKUP_SLUG:-kylefoxaustin/fleet-backup}"
_origin="$(git -C "$PUSHDIR" remote get-url origin 2>/dev/null || true)"
# owner/repo from any remote form: https://host/…, git@host:…, ssh://…/… (drop .git)
_slug="$(printf '%s' "$_origin" | sed -E 's#^(https?://[^/]+/|ssh://[^/]+/|[^/@]+@[^:]+:)##; s#\.git$##; s#/+$##')"
if [ -n "$_slug" ] && [ "$_slug" = "$FLEET_BACKUP_SLUG" ]; then
  rm -f "$REQUESTS/$KEY" 2>/dev/null || true   # never leave a stale request for an exempt repo
  exit 0                                        # ALLOW — private backup, auto-push is the point
fi

TOK="$TOKENS/$KEY"
if [ -f "$TOK" ]; then
  # The token is `key=value` lines. It USED to be a bare epoch, and a leftover one must
  # still be honoured — failing closed here would look exactly like "Kyle's approval
  # didn't work", on the one control he relies on.
  exp="$(grep -E '^expires=' "$TOK" 2>/dev/null | head -1 | cut -d= -f2-)"
  if [ -z "$exp" ]; then exp="$(head -1 "$TOK" 2>/dev/null || echo 0)"; fi
  case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
  # Check expiry BEFORE consuming. The old order rm'd the token FIRST, so an EXPIRED token was
  # silently burned and the push fell through to the generic "needs approval" message — Kyle was
  # never told his approval had LAPSED, only that he needed to approve, which reads as "it didn't
  # work" on the one control he relies on. A consumed-but-unreported approval is the worst thing
  # this gate can do.
  if [ "$now" -lt "$exp" ]; then
    # Don't BURN a valid approval on a provable NO-OP push (image_gen, 2026-07-21).
    # The gate fires PRE-push, so it normally can't tell "Everything up-to-date" from
    # a real push and consumes the one-shot token either way — wasting a scarce human
    # click and training toward "just approve again". For a BARE `git push` /
    # `git push <remote>` (no branch, refspec, or flags), the only thing it CAN push
    # is the current branch to its upstream; if HEAD is not ahead of @{u}, zero refs
    # move. Allow WITHOUT consuming so the approval survives for the real push.
    # Anything fancier — explicit ref, --tags/--delete/--force, or no upstream (@{u}
    # errors → count empty) — falls through and consumes as before. Conservative: this
    # only ever PRESERVES an already-granted token on a guaranteed no-op; it never
    # newly-allows an unapproved push (no token still means DENY below).
    _pargs="$(printf '%s' "$CMD" | grep -Eo '\bpush\b[^;&|]*' | head -1 | sed -E 's/^push[[:space:]]*//')"
    _bare=0
    if [ -z "$_pargs" ]; then _bare=1; else case "$_pargs" in
      -* ) _bare=0 ;;                # a flag (--force/--tags/--delete/-f…)
      *[[:space:]]* ) _bare=0 ;;     # more than one token (remote + branch/refspec)
      *:* ) _bare=0 ;;               # a refspec / delete syntax
      * ) _bare=1 ;;                 # a single remote name only (e.g. `origin`)
    esac; fi
    if [ "$_bare" = 1 ]; then
      _ahead="$(git -C "$PUSHDIR" rev-list --count '@{u}..HEAD' 2>/dev/null || true)"
      if [ "$_ahead" = 0 ]; then
        exit 0                                   # provable no-op → ALLOW, token PRESERVED
      fi
    fi
    rm -f "$TOK"                                 # consume a VALID token — one push per approval
    rm -f "$REQUESTS/$KEY" 2>/dev/null || true   # clear the (now-satisfied) request
    exit 0                                       # ALLOW (proceeds via normal perms)
  fi
  # Expired. Grab when it was granted (for an honest message), remove the stale token, and DENY
  # below — but with a message that says it LAPSED, so Kyle re-approves instead of thinking the
  # gate is broken.
  EXPIRED_AT="$(grep -E '^approved_at=' "$TOK" 2>/dev/null | head -1 | cut -d= -f2-)"
  rm -f "$TOK"
  EXPIRED=1
fi

# The line Kyle actually approves on. `$CMD` is the WHOLE tool call and is multi-line —
# the Bash tool prepends a `cd`, so storing it verbatim meant the inbox read back only its
# FIRST line and showed "cd /home/kyle/Documents/GitHub/claude-connect" as the thing being
# approved. The gate was right and the LABEL was lying, which is the same failure as the
# repo-attribution bug: control intact, description false. Pull out the actual push
# invocation, strip any leading `cd … &&`, and store that one line.
PUSHCMD="$(printf '%s' "$CMD" \
  | grep -Eo 'git([[:space:]]+(-[^[:space:]]+|-C[[:space:]]+[^[:space:]]+))*[[:space:]]+push[^;&|]*' \
  | head -1 | sed -E 's/[[:space:]]*[0-9]*>[[:space:]]*$//; s/[[:space:]]*$//')"
[ -n "$PUSHCMD" ] || PUSHCMD="git push"

# no valid token -> file a request Conductor surfaces, and DENY this push
mkdir -p "$REQUESTS" 2>/dev/null || true
{ echo "repo=$REPO"; echo "repo_name=$NAME"; echo "cwd=$CWD"
  echo "cmd=$PUSHCMD"; echo "epoch=$now"; echo "created=$(date '+%Y-%m-%d %H:%M')"; } > "$REQUESTS/$KEY" 2>/dev/null || true
if [ "${EXPIRED:-0}" = 1 ]; then
  echo "🛑 Your approval for '$NAME'${EXPIRED_AT:+ (granted $EXPIRED_AT)} EXPIRED before this push ran — it did NOT go through, and it was NOT silently reused. A fresh request is filed: re-approve in Conductor's inbox (or 'bus.sh push approve $NAME'), then re-run this push." >&2
else
  echo "🛑 Push to '$NAME' needs Kyle's approval (commits are fine — only pushes are gated). Requested in Conductor's push inbox; approve there or Kyle runs 'bus.sh push approve $NAME', then re-run this push." >&2
fi
exit 2
