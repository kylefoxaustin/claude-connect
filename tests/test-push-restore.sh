#!/usr/bin/env bash
# bus/push-restore.sh — give back an approval consumed by a push that never landed.
#
# Testable with NO real push: the hook reads only the filesystem and git's
# remote-tracking ref, and a remote-tracking ref can be written directly with
# `git update-ref`. That matters here, because a real `git push` in this repo is
# correctly blocked by its own gate, and evading the gate to test the gate's
# companion is worth less than the test.
#
# The cases that matter are the REFUSALS. This script hands back a security grant,
# so the tests that earn their keep are the ones proving it refuses: landed pushes,
# stale records, a live token it must not clobber, and an unresolvable upstream.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/bus/push-restore.sh"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }

setup(){
  T="$(mktemp -d)"; export COORD_STATE_DIR="$T/coord"
  mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-spent"
  R="$T/repo"; mkdir -p "$R"
  git init -q "$R"; git -C "$R" config user.email t@t; git -C "$R" config user.name t
  echo a > "$R/f"; git -C "$R" add f; git -C "$R" commit -qm a
  OLD="$(git -C "$R" rev-parse HEAD)"
  echo b > "$R/f"; git -C "$R" commit -qam b
  NEW="$(git -C "$R" rev-parse HEAD)"
  # An upstream, built without pushing. NOTE: `git branch --set-upstream-to` REFUSES a
  # ref created by update-ref when no remote is configured ("not a branch"), which left
  # @{u} unresolvable and made the hook correctly refuse to act -- a fixture fault that
  # read exactly like a broken hook. Configure the remote AND the tracking config.
  git -C "$R" remote add origin "$T/bare" 2>/dev/null || true
  git -C "$R" update-ref refs/remotes/origin/master "$OLD"
  git -C "$R" config branch.master.remote origin
  git -C "$R" config branch.master.merge refs/heads/master
  git -C "$R" rev-parse --verify --quiet '@{u}' >/dev/null \
    || { echo "  FIXTURE BROKEN: no upstream; the hook would refuse for the wrong reason"; exit 1; }
  KEY="repo_key"
}
spend(){  # $1 = sha the approval was pinned to, $2 = age in seconds
  { echo "approved=1"; echo "expires=$(( $(date +%s) + 3600 ))"
    echo "repo_name=demo"; echo "sha=$1"
    echo "spent_epoch=$(( $(date +%s) - ${2:-5} ))"
    echo "spent_key=$KEY"; echo "spent_sha=$1"
    echo "spent_pushdir=$R"; } > "$COORD_STATE_DIR/push-spent/$KEY"
}
tok(){ [ -e "$COORD_STATE_DIR/push-tokens/$KEY" ] && echo present || echo absent; }
rec(){ [ -e "$COORD_STATE_DIR/push-spent/$KEY" ] && echo present || echo gone; }

bash -n "$HOOK" && ok "syntax clean" || no "syntax error"

# 1 — THE BUG: push vetoed by a pre-push hook, commit is NOT on the remote
setup; spend "$NEW"
bash "$HOOK" 2>/dev/null
[ "$(tok)" = present ] && ok "approval RESTORED when the commit never landed" \
  || no "did not restore a genuinely unlanded push"
[ "$(rec)" = gone ] && ok "spent record cleaned up after restoring" || no "record left behind"
# and the restored token must be a usable token, not the bookkeeping record
if [ "$(grep -c '^spent_' "$COORD_STATE_DIR/push-tokens/$KEY" 2>/dev/null)" = 0 ]; then
  ok "restored token carries no spent_* bookkeeping"
else no "restored token leaked spent_* fields"; fi
grep -q '^sha=' "$COORD_STATE_DIR/push-tokens/$KEY" && ok "restored token keeps its sha pin" \
  || no "restored token lost its sha pin"
rm -rf "$T"

# 2 — REFUSAL: the push LANDED. The approval was correctly used; never give it back.
setup; git -C "$R" update-ref refs/remotes/origin/master "$NEW"; spend "$NEW"
bash "$HOOK" 2>/dev/null
[ "$(tok)" = absent ] && ok "refuses to restore after the push LANDED" \
  || no "restored an approval for a push that landed — would double-grant"
[ "$(rec)" = gone ] && ok "landed record purged" || no "landed record left to retry"
rm -rf "$T"

# 3 — REFUSAL: stale record. An approval resurrected minutes later is one Kyle has
# stopped expecting; a grant reappearing unprompted is worse than one that lapsed.
setup; spend "$NEW" 100000
bash "$HOOK" 2>/dev/null
[ "$(tok)" = absent ] && ok "refuses to restore past the window" || no "restored on stale evidence"
[ "$(rec)" = gone ] && ok "stale record dropped" || no "stale record kept"
rm -rf "$T"

# 4 — REFUSAL: a token already exists. Kyle has since granted a FRESH approval and
# overwriting it with an older record would move the sha-pin backwards under him.
setup; spend "$OLD"; echo "approved=2
sha=$NEW" > "$COORD_STATE_DIR/push-tokens/$KEY"
bash "$HOOK" 2>/dev/null
grep -q "sha=$NEW" "$COORD_STATE_DIR/push-tokens/$KEY" \
  && ok "refuses to clobber a live token (sha-pin not moved backwards)" \
  || no "overwrote a live approval with an older record"
rm -rf "$T"

# 5 — REFUSAL: no resolvable upstream => cannot tell => do nothing. Losing a tap is
# acceptable; inventing one is not.
setup; git -C "$R" branch --unset-upstream master >/dev/null 2>&1
git -C "$R" update-ref -d refs/remotes/origin/master
spend "$NEW"
bash "$HOOK" 2>/dev/null
[ "$(tok)" = absent ] && ok "refuses to restore when landing is undecidable" \
  || no "restored without being able to confirm the push failed"
[ "$(rec)" = present ] && ok "undecidable record kept to age out, not acted on" \
  || no "consumed a record it could not evaluate"
rm -rf "$T"

# 6 — a push-less world: no spent records at all must cost nothing and touch nothing
setup
bash "$HOOK" 2>/dev/null; rc=$?
[ "$rc" = 0 ] && ok "no-op exits 0 with an empty spent dir" || no "no-op exited $rc"
[ "$(tok)" = absent ] && ok "no-op minted nothing" || no "minted a token from nowhere"
rm -rf "$T"

# 7 — a scripted push never passes through the gate, so it never leaves a spent record;
# there is nothing for this hook to restore and the bypass stays closed.
setup; bash "$HOOK" 2>/dev/null
[ "$(tok)" = absent ] && ok "no spent record => no grant (scripted-push bypass stays shut)" \
  || no "granted without a gate-written record"
rm -rf "$T"

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
