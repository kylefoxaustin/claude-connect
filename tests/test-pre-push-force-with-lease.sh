#!/usr/bin/env bash
# qualcomm, 2026-10-16: Kyle approved a history rewrite (a filter-repo purge), the session pushed
# with --force-with-lease=main:138a65f while origin/main WAS 138a65f, and the pre-push hook refused
# it as a race: "refs/heads/main has moved since you last fetched". A rewrite's old tip is never an
# ancestor of its new one, so the non-fast-forward guard blocked EVERY approved force push, and the
# only way past was --no-verify, which skips the whole gate.
#
# git does not hand a hook its flags. The hook now reads them from the git process that ran it, so
# this test MUST drive a REAL git push: feeding the hook stdin from bash (as the other hook tests
# do) leaves no git parent, and would test the branch production never takes. Every push here goes
# to a bare repo inside mktemp, with core.hooksPath and COORD_STATE_DIR pointed at the sandbox.
#
# ⚠️ Written with the Write tool, not a heredoc: a heredoc containing a push invocation trips the
# tool-layer push gate on the text of the test itself.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/bus/git-hooks/pre-push"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }
[ -r /proc/self/cmdline ] || { echo "no /proc — skipping (force detection reads it)"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests" "$COORD_STATE_DIR/push-claims"
mkdir -p "$SB/hooks" && ln -s "$HOOK" "$SB/hooks/pre-push"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1

up="$SB/up"; wt="$SB/wt"; other="$SB/other"
git init -q -b main "$wt"
git -C "$wt" config user.email t@t; git -C "$wt" config user.name t
echo base > "$wt/a.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm base
echo two > "$wt/b.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm "two (to be purged)"
git clone -q --bare "$wt" "$up"
git -C "$wt" remote add origin "$up"; git -C "$wt" fetch -q origin
git -C "$wt" branch -q -u origin/main
OLD="$(git --git-dir="$up" rev-parse main)"
KEY="$(printf '%s' "$wt" | tr '/ ' '__' | sed 's/^_*//')"

# The rewrite: drop the second commit's file from history. Old tip is no longer an ancestor.
git -C "$wt" rm -q b.txt; git -C "$wt" commit -q --allow-empty --amend -m "two (purged)"
NEW="$(git -C "$wt" rev-parse HEAD)"
git -C "$wt" merge-base --is-ancestor "$OLD" "$NEW" \
  && bad "setup: the rewrite is still a fast-forward — not testing the rewrite case" \
  || ok "setup: the rewritten tip does not contain the remote tip"

mint() { { echo "expires=$(( $(date +%s) + 3600 ))"; echo "repo=$wt"; echo "repo_name=wt"
           echo "sha=$1"; echo "approved=$(date +%s)"; } > "$COORD_STATE_DIR/push-tokens/$KEY"; }
tok()  { [ -f "$COORD_STATE_DIR/push-tokens/$KEY" ] && echo present || echo consumed; }
remote_tip() { git --git-dir="$up" rev-parse main; }
gpush() { (cd "$wt" && git -c core.hooksPath="$SB/hooks" push "$@" >"$SB/out" 2>&1); echo $?; }

# 1. Approved force-with-lease over the tip we fetched → lands, consumes exactly one approval.
mint "$NEW"
rc="$(gpush --force-with-lease=main:"$OLD" origin main)"
[ "$rc" = 0 ] && ok "⭐ an approved --force-with-lease rewrite lands" \
  || bad "approved rewrite refused (rc=$rc): $(grep -m2 -E '⏪|🛑|rejected' "$SB/out")"
[ "$(remote_tip)" = "$NEW" ] && ok "and the remote really is the rewritten tip" \
  || bad "remote is $(remote_tip), wanted $NEW"
[ "$(tok)" = consumed ] && ok "and the approval was spent — one push per approval still holds" \
  || bad "a landed push left its approval live"

# 2. Same shape, NO approval → the normal approval gate, not the misleading race message.
git -C "$wt" fetch -q origin
echo three > "$wt/c.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm three
B4="$(remote_tip)"
git -C "$wt" reset -q --soft HEAD~2; git -C "$wt" commit -qm "squashed"   # a rewrite of the remote
rc="$(gpush --force-with-lease origin main)"
[ "$rc" != 0 ] && [ "$(remote_tip)" = "$B4" ] && ok "an UNapproved rewrite is still refused" \
  || bad "an unapproved force push landed"
grep -q "needs Kyle's approval" "$SB/out" && ! grep -q '⏪' "$SB/out" \
  && ok "and it asks for approval instead of claiming the remote moved" \
  || bad "wrong refusal: $(grep -m2 -E '⏪|🛑' "$SB/out")"
[ -f "$COORD_STATE_DIR/push-requests/$KEY" ] && ok "and the request is filed for Kyle" \
  || bad "no request filed"

# 3. CONTROL — a real race: someone else pushed since our fetch. Even with --force and a live
#    approval, we must not overwrite what we never saw, nor spend the approval.
git clone -q "$up" "$other"; git -C "$other" config user.email o@o; git -C "$other" config user.name o
echo theirs > "$other/t.txt"; git -C "$other" add -A; git -C "$other" commit -qm theirs
git --git-dir="$up" fetch -q "$other" main:main
THEIRS="$(remote_tip)"
MINE="$(git -C "$wt" rev-parse HEAD)"; mint "$MINE"
rc="$(gpush --force origin main)"
[ "$rc" != 0 ] && [ "$(remote_tip)" = "$THEIRS" ] && ok "⭐ a bare --force over a remote that moved is refused" \
  || bad "clobbered a commit we never fetched"
grep -q '⏪' "$SB/out" && ok "with the race message" || bad "no race message: $(head -c 200 "$SB/out")"
[ "$(tok)" = present ] && ok "and the approval is untouched" || bad "burned the approval on a race"

# 4. CONTROL — an UNforced push of a rewrite never gets past, approval or not.
git -C "$wt" fetch -q origin
rc="$(gpush origin main)"
[ "$rc" != 0 ] && [ "$(remote_tip)" = "$THEIRS" ] && ok "an unforced non-fast-forward still does not land" \
  || bad "an unforced rewrite landed"
[ "$(tok)" = present ] && ok "and does not spend the approval" || bad "unforced reject spent the approval"

echo "── pre-push-force-with-lease: $pass passed, $fail failed"
[ "$fail" = 0 ]
