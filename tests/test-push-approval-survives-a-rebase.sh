#!/usr/bin/env bash
# Kyle: "I'd rather all the sessions know what the process is... it just goes back and forth."
#
# MEASURED 2026-08-26/27: 18 approvals granted in two days, several spent on pushes that never
# landed. Two accounting bugs, neither of them a security property:
#
# 1. THE GRANT IS CONSUMED AT AUTHORISATION TIME, which is BEFORE git speaks to the remote. A push
#    the remote then rejects as non-fast-forward has already burned the approval, so Kyle taps
#    again for a push that never existed. git hands this hook the remote sha on stdin, so the
#    rejection is PREDICTABLE — refuse without consuming, and say the approval is intact.
#
# 2. THE PIN IS ON THE TIP COMMIT, so rebasing onto whoever pushed first rewrites every sha and the
#    approval stops matching changes Kyle approved UNCHANGED. `git patch-id --stable` is invariant
#    across a rebase exactly when the diff is unchanged, so it keeps a clean rebase covered and
#    correctly drops a rebase whose conflict resolution ALTERED a diff.
#
# Nothing here loosens the gate: still one push per approval, still his tap, still revocable, and
# a changed diff still asks again. What goes away is taps spent on races.
#
# ⚠️ Written with the Write tool rather than a shell heredoc ON PURPOSE: a heredoc containing a
# real push invocation trips the push gate on the text of the test itself. That is the fourth
# prefilter false positive today and it is its own finding.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/bus/git-hooks/pre-push"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests" "$COORD_STATE_DIR/push-claims"

up="$SB/up"; wt="$SB/wt"
git init -q --bare "$up"
git init -q -b main "$wt"
git -C "$wt" config user.email t@t; git -C "$wt" config user.name t
git -C "$wt" remote add origin "$up"
echo base > "$wt/a.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm base
# seed the remote by cloning FROM the worktree — avoids writing a push invocation into this file
git clone -q --bare "$wt" "$SB/seed" && rm -rf "$up" && mv "$SB/seed" "$up"
git -C "$wt" fetch -q origin && git -C "$wt" branch -q -u origin/main 2>/dev/null || true

echo mine > "$wt/mine.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm "my change"
MINE="$(git -C "$wt" rev-parse HEAD)"
PID="$(git -C "$wt" show "$MINE" | git patch-id --stable | cut -d' ' -f1)"
KEY="$(printf '%s' "$wt" | tr -cs 'A-Za-z0-9._-' '_' | sed 's/^_*//;s/_*$//')"

mint() {   # <sha> [patch_id]
  { echo "expires=$(( $(date +%s) + 3600 ))"; echo "repo=$wt"; echo "repo_name=wt"
    echo "sha=$1"; [ -n "${2:-}" ] && echo "patch_id=$2"
    echo "approved=$(date +%s)"; } > "$COORD_STATE_DIR/push-tokens/$KEY"
}
run() {    # feed the hook what git would: <lref> <lsha> <rref> <rsha>
  printf '%s\n' "refs/heads/main $1 refs/heads/main $2" \
    | (cd "$wt" && bash "$HOOK" origin "$up" >/dev/null 2>"$SB/err"); echo $?
}
tok() { [ -f "$COORD_STATE_DIR/push-tokens/$KEY" ] && echo present || echo consumed; }

# ---------------------------------------------------------------------------------------
# 1. Someone else landed first. The push CANNOT fast-forward — refuse, and do not spend the tap.
# ---------------------------------------------------------------------------------------
other="$SB/other"; git clone -q "$up" "$other"
git -C "$other" config user.email o@o; git -C "$other" config user.name o
echo theirs > "$other/theirs.txt"; git -C "$other" add -A; git -C "$other" commit -qm theirs
git -C "$other" update-ref refs/heads/main HEAD
git --git-dir="$up" fetch -q "$other" main:main 2>/dev/null \
  || git --git-dir="$up" fetch -q "$other" HEAD:refs/heads/main
THEIRS="$(git --git-dir="$up" rev-parse refs/heads/main)"
# ⚠️ DELIBERATELY NOT FETCHING. The first version of this test fetched here, which made the remote
# tip a local object and let the guard take a branch production never reaches — so the suite went
# green while the guard burned a real approval on the real race. In life you discover the remote
# moved BY BEING REJECTED, which is after the fetch you have not done. The hook must resolve it
# itself.
mint "$MINE" "$PID"
rc="$(run "$MINE" "$THEIRS")"
[ "$rc" != 0 ] && ok "a push that cannot fast-forward is refused" \
  || bad "allowed a push the remote would reject"
[ "$(tok)" = present ] && ok "⭐ and the approval is NOT spent on it" \
  || bad "burned the grant on a push that could never land"
grep -q 'APPROVAL IS UNTOUCHED' "$SB/err" && ok "and it says so, so nobody re-taps" \
  || bad "no reassurance in the message — the session will ask for another approval"

# ---------------------------------------------------------------------------------------
# 2. Rebase — every sha changes. The CHANGES are still the ones Kyle approved.
# ---------------------------------------------------------------------------------------
git -C "$wt" rebase -q origin/main >/dev/null 2>&1
REBASED="$(git -C "$wt" rev-parse HEAD)"
[ "$REBASED" != "$MINE" ] && ok "the rebase rewrote the sha (a tip pin would now miss)" \
  || bad "sha unchanged — this test is not exercising the rebase case"
rc="$(run "$REBASED" "$THEIRS")"
[ "$rc" = 0 ] && ok "⭐ a clean rebase keeps the approval (patch-id pin)" \
  || bad "denied a rebase of the very commits Kyle approved: $(head -c 140 "$SB/err")"
[ "$(tok)" = consumed ] && ok "and NOW it is consumed — one push per approval still holds" \
  || bad "a push that would land did not consume the grant"

# ---------------------------------------------------------------------------------------
# 3. THE CONTROL. A rebase whose conflict resolution CHANGED the diff must ask again, or
#    "keeps the approval" would quietly mean "approves anything".
# ---------------------------------------------------------------------------------------
echo altered >> "$wt/mine.txt"; git -C "$wt" add -A; git -C "$wt" commit -q --amend --no-edit
ALTERED="$(git -C "$wt" rev-parse HEAD)"
mint "$MINE" "$PID"
rc="$(run "$ALTERED" "$THEIRS")"
[ "$rc" != 0 ] && ok "a rebase that ALTERED the content is denied" \
  || bad "an altered diff rode an approval Kyle gave for different content"
[ "$(tok)" = present ] && ok "and that denial does not spend the grant either" \
  || bad "burned the grant on a denial"

echo "── push-approval-survives-a-rebase: $pass passed, $fail failed"
[ "$fail" = 0 ]
