#!/usr/bin/env bash
# SHA-PIN (qualcomm, 2026-07-22): a push approval must authorize ONE SPECIFIC commit, not "the
# next arbitrary push to this repo". The token carries the approved commit's SHA; the gate
# allows a push only when HEAD still equals it, and DENYs without consuming when HEAD has moved
# (new commit / amend). A legacy token with no sha stays honoured (back-compat). Drives the REAL
# bus/push-gate.sh.
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

REPO="$SB/repo"; mkdir -p "$REPO"
git "${GA[@]}" init -q "$REPO"
git "${GA[@]}" -C "$REPO" remote add origin https://github.com/kylefoxaustin/product.git
( cd "$REPO" && echo a > f && git "${GA[@]}" add f && git "${GA[@]}" commit -qm A )
SHA_A="$(git -C "$REPO" rev-parse HEAD)"

KEY="$(printf '%s' "$REPO" | tr '/ ' '__' | sed 's/^_*//')"
TOK="$COORD_STATE_DIR/push-tokens/$KEY"
REQ="$COORD_STATE_DIR/push-requests/$KEY"
now="$(date +%s)"
mktok() { printf 'expires=%s\nrepo=%s\n%s\napproved_at=x\n' "$((now+3600))" "$REPO" "$1" > "$TOK"; }
run() { printf '{"cwd":"%s","tool_input":{"command":"git push origin main"}}' "$REPO" | bash "$GATE" 2>"$SB/err"; echo $?; }

# 1. token pinned to A, HEAD == A -> ALLOW, consumed
mktok "sha=$SHA_A"
[ "$(run)" = 0 ] && ok "pinned to HEAD: ALLOWED" || bad "pinned-to-HEAD not allowed"
[ ! -f "$TOK" ] && ok "matching push: token consumed" || bad "matching push didn't consume"

# advance HEAD to a NEW commit B
( cd "$REPO" && echo b >> f && git "${GA[@]}" commit -qam B )
SHA_B="$(git -C "$REPO" rev-parse HEAD)"

# 2. token still pinned to A, HEAD == B -> DENY, token PRESERVED, mismatch message
mktok "sha=$SHA_A"
[ "$(run)" = 2 ] && ok "HEAD moved off approved commit: DENIED" || bad "moved-HEAD not denied"
[ -f "$TOK" ] && ok "mismatch: token NOT consumed (still valid for its commit)" || bad "mismatch burned the token"
grep -q "was for commit ${SHA_A:0:8}" "$SB/err" && ok "mismatch: names the approved commit" || bad "mismatch: no approved-commit in message"
grep -q "HEAD is now ${SHA_B:0:8}" "$SB/err" && ok "mismatch: names the current commit" || bad "mismatch: no current-commit in message"

# 3. re-approve for B (token pinned to B), HEAD == B -> ALLOW
mktok "sha=$SHA_B"
[ "$(run)" = 0 ] && ok "re-approved for new commit: ALLOWED" || bad "re-approve for B not allowed"

# 4. legacy token (NO sha) -> honoured (back-compat)
printf 'expires=%s\nrepo=%s\napproved_at=x\n' "$((now+3600))" "$REPO" > "$TOK"
[ "$(run)" = 0 ] && ok "legacy no-sha token: still ALLOWED (back-compat)" || bad "legacy token broke"

# 5. no token -> DENY, and the filed REQUEST records the pushing commit's sha
rm -f "$TOK" "$REQ"
[ "$(run)" = 2 ] && ok "no token: DENIED" || bad "no-token wrong exit"
grep -q "sha=$SHA_B" "$REQ" && ok "request records HEAD's sha (for pinning on approve)" || bad "request missing sha"

echo "── push-gate-sha-pin: $pass passed, $fail failed"
[ "$fail" = 0 ]
