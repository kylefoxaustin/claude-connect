#!/usr/bin/env bash
# The push gate must not SILENTLY BURN an expired approval. The old order rm'd the token before
# checking expiry, so an expired token was consumed and the push fell through to the generic
# "needs approval" message — Kyle was never told his approval had LAPSED. Drives the REAL
# bus/push-gate.sh.
set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/bus/push-gate.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests"
REPO="$SB/myrepo"; mkdir -p "$REPO"
KEY="$(printf '%s' "$REPO" | tr '/ ' '__' | sed 's/^_*//')"
TOK="$COORD_STATE_DIR/push-tokens/$KEY"
PAYLOAD="{\"cwd\":\"$REPO\",\"tool_input\":{\"command\":\"git push origin main\"}}"
run() { printf '%s' "$PAYLOAD" | bash "$GATE" 2>"$SB/err"; echo $?; }   # echoes exit code; stderr in $SB/err
now="$(date +%s)"

# 1. VALID token -> ALLOW, consumed
printf 'expires=%s\napproved_at=x\n' $((now+3600)) > "$TOK"
[ "$(run)" = 0 ] && ok "valid token: ALLOWS (exit 0)" || bad "valid token did not allow"
[ ! -f "$TOK" ] && ok "valid token: consumed" || bad "valid token not consumed"

# 2. EXPIRED token -> DENY, removed, and the message SAYS it expired (the bug)
printf 'expires=%s\napproved_at=2026-07-14 12:00\n' $((now-100)) > "$TOK"
[ "$(run)" = 2 ] && ok "expired token: DENIES (exit 2)" || bad "expired token wrong exit"
[ ! -f "$TOK" ] && ok "expired token: removed" || bad "expired token left behind"
grep -q 'EXPIRED' "$SB/err" && ok "expired: message SAYS it expired" || bad "expired: silent burn — generic message"
grep -q 'NOT silently reused' "$SB/err" && ok "expired: reassures it wasn't reused" || bad "expired: missing reassurance"
grep -q 'granted 2026-07-14 12:00' "$SB/err" && ok "expired: names when it was granted" || bad "expired: no grant time"

# 3. NO token -> DENY with the GENERIC message (must NOT falsely claim 'expired')
[ "$(run)" = 2 ] && ok "no token: DENIES (exit 2)" || bad "no token wrong exit"
grep -q 'EXPIRED' "$SB/err" && bad "no token: falsely said EXPIRED" || ok "no token: generic message (correct)"
grep -q "needs Kyle's approval" "$SB/err" && ok "no token: the normal request message" || bad "no token: wrong message"

# 4. a bare-epoch legacy token (no key=value) still honoured when unexpired
printf '%s\n' $((now+3600)) > "$TOK"
[ "$(run)" = 0 ] && ok "legacy bare-epoch token still allowed" || bad "legacy token broke"

# 5. NON-push command sails through untouched (exit 0, no request filed)
before=$(ls "$COORD_STATE_DIR/push-requests" | wc -l)
ec=$(printf '{"cwd":"%s","tool_input":{"command":"git log --oneline"}}' "$REPO" | bash "$GATE" 2>/dev/null; echo $?)
[ "$ec" = 0 ] && ok "non-push (git log): sails through" || bad "non-push was gated"
[ "$(ls "$COORD_STATE_DIR/push-requests" | wc -l)" = "$before" ] && ok "non-push: filed no request" || bad "non-push filed a request"

echo "── push-gate-expiry: $pass passed, $fail failed"
[ "$fail" = 0 ]
