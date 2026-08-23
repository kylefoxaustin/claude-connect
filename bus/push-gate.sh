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
CLAIMS="$COORD/push-claims"   # short-lived hand-off to the pre-push enforcer (see below)

# ---- WHICH PYTHON, AND HOW WE DARE TO ANSWER THAT --------------------------------
# ⚠️ BOTH GATES USED A BARE `python3` AND SWALLOWED ITS FAILURE. When python3 could not
# run, the substitution produced nothing, the "no match" branch fired, and the gate
# exited 0 — SILENTLY ALLOWING the act it exists to stop. An armed gate that is not
# there. Found by win_conductor (the Windows-port session) on 2026-08-23, reproduced
# here with a control the same day; the push gate had the identical defect, so BOTH of
# Kyle's hard controls disarmed together on one missing binary.
#
# ⭐ AND THE PART THAT MAKES THIS TEN LINES INSTEAD OF TWO: RESOLUTION IS NOT USABILITY.
# The obvious fix — try python3, then python, then py -3, taking the first that EXISTS —
# would not have closed it. On Windows, `WindowsApps\python3.exe` is a ZERO-BYTE App
# Execution Alias: it satisfies `command -v`, `where`, and `test -x`, and it exits 49
# with "Python was not found". An existence check picks the stub on its FIRST try,
# declares victory, and leaves the gate open with a fix in front of it and a comment
# claiming it is handled — strictly worse than today's undisguised failure, because it
# is now disguised. MEASURED by win_conductor inside a real hook on Windows 11.
#
# So a candidate is chosen by RUNNING it. The probe imports exactly what the gate
# bodies need, so a python too old or too stripped to execute them fails HERE, where we
# can say so, instead of mid-parse where the failure looks like "nothing matched".
#
# Called LAZILY — only after a fast path has already decided we must run python — so
# the common case (every tool call that is not a candidate) still costs one grep.
#
# DUPLICATED VERBATIM IN push-gate.sh, ON PURPOSE. A gate that must `source` a helper
# acquires a new silent-failure mode — file missing, function undefined, gate wide open
# — which is the exact bug being fixed. Twelve duplicated lines beat a load-bearing dot.
# ---- D: A DEGRADED GATE MUST LEAVE A TRACE ---------------------------------------
# Neither gate wrote a single line anywhere when it took a degraded path. That is why the
# fail-open survived: from the outside it is identical to a quiet fleet. "A silent no-op is
# a lie of omission" is this project's own rule (v2.37) and the gates were exempt from it.
#
# Deliberately NOT logged: normal denials and normal allows. A denial already files a
# request and prints a banner; an allow is the common case and logging it would produce a
# log nobody reads, which is the same as no log. Only ANOMALIES land here.
# ⚠️ LAZY. My first version ran the mkdir and the writability probe at the TOP of the file,
# i.e. on EVERY Bash/Edit/Write in EVERY session — two syscalls added to the hot path of a
# hook whose stated design constraint is "instant no-op for anything that is not a
# candidate". Setting a variable is free; touching the filesystem is not. So the preparation
# happens in _gate_log_ready, called only once we are past the fast path and about to spawn
# python anyway. Caught by re-reading the file's own header after writing the patch.
_GATE_LOG="${BUS_STATE_DIR:-$HOME/.claude/bus-state}/gate.log"
_gate_log_ready() {
  mkdir -p "$(dirname "$_GATE_LOG")" 2>/dev/null || true
  # If the log is unwritable, degrade to /dev/null rather than letting a failed redirect
  # take the gate down. A logging bug must never become an outage in the thing it logs.
  { : >> "$_GATE_LOG"; } 2>/dev/null || _GATE_LOG=/dev/null
}
_gate_log() { printf '%s\t%s\t%s\n' "$(date '+%F %T')" "$1" "$2" >> "$_GATE_LOG" 2>/dev/null || true; }

_gate_py() {
  [ -n "${_GATE_PY:-}" ] && { printf '%s' "$_GATE_PY"; return 0; }
  # unquoted on purpose: "py -3" must split into a command plus its argument.
  for _c in ${CLAUDE_BUS_PYTHON:-} python3 python "py -3"; do
    $_c -c 'import json,os,re,sys' >/dev/null 2>&1 || continue
    _GATE_PY="$_c"; printf '%s' "$_c"; return 0
  done
  return 1
}

INPUT="$(cat 2>/dev/null || true)"

# ---- fast path: not even a mention of "push" -> allow instantly (no python) -----
printf '%s' "$INPUT" | grep -q 'push' || exit 0

# ---- the interpreter must exist BEFORE we trust anything it would have told us -----
# This is the fail-closed half. Past this point the gate's verdict comes from python; if
# python cannot run, the gate has NO VERDICT — and "no verdict" must never be spelled the
# same way as "allowed". Loud beats silent for a control whose entire job is to stop things.
_gate_log_ready
if ! _PYBIN="$(_gate_py)"; then
  cat >&2 <<'EOF'
🛑 PUSH GATE — DENIED, because the gate is blind.
No usable Python interpreter was found, so this gate cannot evaluate the command — and a
gate that cannot evaluate must not allow. Tried: $CLAUDE_BUS_PYTHON, python3, python, py -3
(each was RUN, not merely resolved — a Windows App Execution Alias resolves and is not an
interpreter).

Fix the interpreter, or point the gate at a known-good one:
    export CLAUDE_BUS_PYTHON=/absolute/path/to/python
This gate is armed; a push cannot proceed while it cannot see what it is gating.
EOF
  _gate_log push "no usable Python interpreter — DENIED (the gate could not evaluate)"
  exit 2
fi

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
    # WAS: write two blank lines and exit 0 — which the caller read as "no push here" and
    # ALLOWED. A parse failure is not evidence of innocence; it is the absence of evidence,
    # and this gate exists precisely to stop guessing in the permissive direction. Exit 3
    # so the caller can tell a crash from a clean no-match, and print why.
    import traceback
    traceback.print_exc()
    sys.exit(3)

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
_parsed="$(printf '%s' "$INPUT" | $_PYBIN -c "$_PY" 2>>"$_GATE_LOG")"
_rc=$?
if [ "$_rc" != 0 ]; then
  _gate_log push "parse crashed (rc=$_rc) — DENIED; traceback above"
  cat >&2 <<'EOF'
🛑 PUSH GATE — DENIED, because the gate itself failed.
It could not parse the tool call, so it cannot tell whether this is a push or where it
would land. It will not guess in the permissive direction.

The traceback is in the gate log:
    tail ~/.claude/bus-state/gate.log
EOF
  exit 2
fi
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
# Sanitize to EXACTLY the charset Conductor's API accepts for a request key. `tr '/ ' '__'`
# replaced only slashes and spaces, so a repo path containing anything else ($ + ( & …) filed a
# request the API then refused with "bad request key" — filable, but not dismissible from the
# desktop OR the phone, re-ringing Kyle hourly with no way to clear it (2026-08-06). A gate that
# can raise an alarm the operator cannot lower teaches the operator to ignore the alarm.
KEY="$(printf '%s' "$REPO" | tr -c 'A-Za-z0-9._-' '_' | sed 's/^_*//')"
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

# The commit this push would land (for the SHA-pin below + the request record). HEAD is the
# right proxy: a plain `git push` / `git push <remote>` pushes the current branch's tip = HEAD.
# A fancier push (explicit ref, --all) whose pushed ref != HEAD fails SAFE — it mismatches and
# asks for re-approval, never a false allow.
HEAD_SHA="$(git -C "$PUSHDIR" rev-parse HEAD 2>/dev/null || true)"

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
    # SHA-PIN (qualcomm, 2026-07-22): an approval authorizes ONE SPECIFIC commit, not "the next
    # arbitrary push to this repo". If the token names a commit and HEAD has since MOVED (a new
    # commit, or `git commit --amend`), DENY without consuming and require re-approval for the
    # commit actually being pushed. A legacy token with no `sha=` is still honoured (back-compat,
    # like the bare-epoch handling) so an in-flight approval from before this change still works.
    tok_sha="$(grep -E '^sha=' "$TOK" 2>/dev/null | head -1 | cut -d= -f2-)"
    if [ -n "$tok_sha" ] && [ "$tok_sha" != "$HEAD_SHA" ]; then
      MISMATCH=1; MM_APPROVED="$tok_sha"           # keep the token — it's still valid for ITS commit
    else
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
    # Hand a short-lived CLAIM to the pre-push hook (the real enforcer, which fires next on the
    # actual push). We just consumed the token, so pre-push would otherwise find nothing and DENY a
    # push Kyle just approved. The claim says "this exact commit was approved-and-consumed at the
    # tool layer moments ago"; pre-push honours it once (sha-matched, TTL-bounded) and deletes it.
    # A scripted push never passes through THIS hook, so it never gets a claim — the bypass stays
    # closed. (If the pre-push hook isn't installed, this file is harmless clutter that expires.)
    mkdir -p "$CLAIMS" 2>/dev/null || true
    { echo "sha=$HEAD_SHA"; echo "epoch=$now"; } > "$CLAIMS/$KEY" 2>/dev/null || true
    exit 0                                       # ALLOW (proceeds via normal perms)
    fi                                           # end SHA-pin: token's commit matches HEAD
  else
    # Expired. Grab when it was granted (for an honest message), remove the stale token, and DENY
    # below — but with a message that says it LAPSED, so Kyle re-approves instead of thinking the
    # gate is broken.
    EXPIRED_AT="$(grep -E '^approved_at=' "$TOK" 2>/dev/null | head -1 | cut -d= -f2-)"
    rm -f "$TOK"
    EXPIRED=1
  fi
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

# no valid (matching) token -> file a request Conductor surfaces, and DENY this push. The
# request carries the SHA of the commit being pushed (HEAD), so `push approve` can pin the
# token to THIS commit — an approval authorizes one specific commit, not the next arbitrary push.
mkdir -p "$REQUESTS" 2>/dev/null || true
{ echo "repo=$REPO"; echo "repo_name=$NAME"; echo "cwd=$CWD"
  echo "cmd=$PUSHCMD"; echo "sha=$HEAD_SHA"; echo "epoch=$now"; echo "created=$(date '+%Y-%m-%d %H:%M')"; } > "$REQUESTS/$KEY" 2>/dev/null || true
# 95emulator (2026-07-24): the gate denies the WHOLE Bash call, so a compound
# `git add … && git commit … && git push` blocks the COMMIT too — but it's natural to assume the
# commit ran and only the push is pending. It didn't: HEAD never moved, and a later standalone
# push says "Everything up-to-date". If the blocked command staged/committed before the push,
# say so — so nobody chases a commit that never happened (cost ~20 min twice).
_precommit=""
if printf '%s' "$CMD" | grep -Eq '(^|[;&|(])[[:space:]]*git[[:space:]]+(add|commit)\b'; then
  _precommit="
⚠ Heads-up: the git add/commit in this command did NOT run either — the WHOLE command was blocked, HEAD did not move. Commit in a SEPARATE step first, then push."
fi
if [ "${MISMATCH:-0}" = 1 ]; then
  echo "🛑 Your approval for '$NAME' was for commit ${MM_APPROVED:0:8}, but HEAD is now ${HEAD_SHA:0:8} (you committed again or amended). That approval was NOT consumed — it still stands for its commit. Re-approve THIS commit in Conductor's inbox (or 'bus.sh push approve $NAME'), then re-run this push." >&2
elif [ "${EXPIRED:-0}" = 1 ]; then
  echo "🛑 Your approval for '$NAME'${EXPIRED_AT:+ (granted $EXPIRED_AT)} EXPIRED before this push ran — it did NOT go through, and it was NOT silently reused. A fresh request is filed: re-approve in Conductor's inbox (or 'bus.sh push approve $NAME'), then re-run this push." >&2
else
  echo "🛑 Push to '$NAME' needs Kyle's approval (commits are fine — only pushes are gated). Requested in Conductor's push inbox; approve there or Kyle runs 'bus.sh push approve $NAME', then re-run this push.${_precommit}" >&2
fi
exit 2
