#!/usr/bin/env bash
# The push gate must not BURN a valid one-shot approval on a NO-OP push (image_gen,
# 2026-07-21): a bare `git push` with nothing ahead of upstream moves zero refs, so
# the token must be PRESERVED for the real push. A push that actually moves refs
# still consumes. Anything non-bare (explicit ref / flags) consumes as before.
# Drives the REAL bus/push-gate.sh.
set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/bus/push-gate.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests"
GA=(-c user.name=t -c user.email=t@e -c commit.gpgsign=false -c init.defaultBranch=main)

# A bare "remote" + a working clone tracking it → HEAD == origin/main (nothing ahead).
#
# ⚠️ THE `-u` BELOW IS LOAD-BEARING AND WAS MISSING, so this suite failed 4 of 11 for reasons
# that had nothing to do with the gate. Cloning an EMPTY bare repo sets no upstream, and a plain
# `git push origin main` does not create one — so `@{u}` did not resolve, `rev-list --count
# @{u}..HEAD` printed nothing, and the no-op branch (which requires the count to equal "0") was
# UNREACHABLE. The gate then fell through and consumed, which is its documented behaviour when
# there is no upstream. The suite was reporting a defect the gate does not have, in a path it
# never executed.
#
# Same family as the no-burn guard's test earlier today, and the exact mirror of it: that one
# established a precondition production LACKS (it fetched first); this one failed to establish
# one production HAS. A fixture whose setup does not match reality measures the fixture.
# ⚠️ THE FIXTURE MUST NOT USE `git push`, AND THAT IS WHY THIS SUITE WAS RED. `core.hooksPath`
# is set globally, so the pre-push hook fires inside a scratch repo in /tmp too — it DENIED the
# setup push, so `refs/remotes/origin/main` was never created, so `@{u}` did not resolve, so
# `rev-list --count @{u}..HEAD` printed nothing, so the no-op branch (which requires "0") was
# UNREACHABLE and the gate fell through and consumed. Four assertions failed describing a defect
# the gate does not have, in a path they never executed.
#
# ⭐ The security control broke its own test's setup, and nothing noticed because these 30 shell
# suites are not wired into `make test` — a check that did not run looks exactly like a check
# that passed (M51), applied to the suite instead of the code.
#
# Seed the remote by FETCHING from the work tree, the way test-push-approval-survives-a-rebase.sh
# already does. That establishes a real upstream with no push invocation to be gated, and without
# teaching a bypass anyone could copy into a real repo.
git "${GA[@]}" init -q --bare "$SB/remote.git"
git "${GA[@]}" init -q "$SB/work"
WORK="$SB/work"
( cd "$WORK" && echo hi > f && git "${GA[@]}" add f && git "${GA[@]}" commit -qm init ) 2>/dev/null
git --git-dir="$SB/remote.git" fetch -q "$WORK" main:refs/heads/main 2>/dev/null
( cd "$WORK" && git "${GA[@]}" remote add origin "$SB/remote.git" \
  && git "${GA[@]}" fetch -q origin && git "${GA[@]}" branch -q -u origin/main main ) 2>/dev/null
# The precondition every assertion below depends on. Prove it rather than assume it — assuming it
# is precisely how this suite spent weeks reporting a gate bug that did not exist.
if [ "$(cd "$WORK" && git rev-list --count '@{u}..HEAD' 2>/dev/null)" != "0" ]; then
  echo "  FATAL fixture: no upstream, so the no-op path cannot be exercised"; exit 1
fi

KEY="$(printf '%s' "$WORK" | tr '/ ' '__' | sed 's/^_*//')"
TOK="$COORD_STATE_DIR/push-tokens/$KEY"
now="$(date +%s)"
mktok() { printf 'expires=%s\napproved_at=x\n' $((now+3600)) > "$TOK"; }
run() {  # $1 = the push command; echoes exit code
  printf '{"cwd":"%s","tool_input":{"command":"%s"}}' "$WORK" "$1" | bash "$GATE" 2>/dev/null; echo $?
}

# 1. bare `git push`, nothing ahead → ALLOW, token PRESERVED
mktok
[ "$(run 'git push')" = 0 ] && ok "no-op bare push: ALLOWED" || bad "no-op push not allowed"
[ -f "$TOK" ] && ok "no-op bare push: token PRESERVED" || bad "no-op push burned the token"

# 2. bare `git push origin`, nothing ahead → ALLOW, token PRESERVED
[ "$(run 'git push origin')" = 0 ] && ok "no-op 'push origin': ALLOWED" || bad "no-op push origin denied"
[ -f "$TOK" ] && ok "no-op 'push origin': token PRESERVED" || bad "no-op push origin burned token"

# 3. a REAL push (a commit ahead of upstream) → ALLOW, token CONSUMED
( cd "$WORK" && echo more >> f && git "${GA[@]}" commit -qam more ) 2>/dev/null
[ "$(run 'git push')" = 0 ] && ok "real push (ahead): ALLOWED" || bad "real push denied"
[ ! -f "$TOK" ] && ok "real push: token CONSUMED" || bad "real push did not consume token"

# 4. non-bare push (explicit branch) with nothing ahead → CONSUMED (conservative)
# Re-sync without a push, for the same reason as the setup above.
git --git-dir="$SB/remote.git" fetch -q "$WORK" main:refs/heads/main 2>/dev/null
( cd "$WORK" && git "${GA[@]}" fetch -q origin ) 2>/dev/null   # re-sync: nothing ahead
mktok
[ "$(run 'git push origin main')" = 0 ] && ok "explicit-ref no-op: ALLOWED" || bad "explicit-ref denied"
[ ! -f "$TOK" ] && ok "explicit-ref no-op: CONSUMED (not treated as bare)" || bad "explicit-ref wrongly preserved"

# 5. a flag push (--tags) with nothing ahead → CONSUMED (conservative)
mktok
[ "$(run 'git push --tags')" = 0 ] && ok "--tags no-op: ALLOWED" || bad "--tags denied"
[ ! -f "$TOK" ] && ok "--tags no-op: CONSUMED (flag → not bare)" || bad "--tags wrongly preserved"

# 6. no-op push with NO token → still DENIED (never newly-allows an unapproved push)
rm -f "$TOK"
[ "$(run 'git push')" = 2 ] && ok "no-op, no token: still DENIED" || bad "no-op without token slipped through"

echo "── push-gate-noop-token: $pass passed, $fail failed"
[ "$fail" = 0 ]
