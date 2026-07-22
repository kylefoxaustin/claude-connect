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
git "${GA[@]}" init -q --bare "$SB/remote.git"
git "${GA[@]}" clone -q "$SB/remote.git" "$SB/work" 2>/dev/null
WORK="$SB/work"
( cd "$WORK" && echo hi > f && git "${GA[@]}" add f && git "${GA[@]}" commit -qm init \
  && git "${GA[@]}" push -q origin main ) 2>/dev/null   # now upstream == HEAD

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
( cd "$WORK" && git "${GA[@]}" push -q origin main ) 2>/dev/null   # re-sync: nothing ahead
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
