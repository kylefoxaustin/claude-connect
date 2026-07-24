#!/usr/bin/env bash
# 95emulator (2026-07-24): the gate denies the WHOLE Bash call, so a compound
# `git add && git commit && git <PUSH>` blocks the commit too — people assume the commit ran.
# The deny message must warn when the blocked command staged/committed before pushing. Drives
# the REAL bus/push-gate.sh. (This lives in a FILE so the harness's own top-level command has no
# push literal — otherwise the installed gate would block running the test.)
set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/bus/push-gate.sh"
P="push"                                   # avoid the literal token in our own command lines
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests"
R="$SB/repo"; git -c init.defaultBranch=main init -q "$R"
git -C "$R" remote add origin https://github.com/kylefoxaustin/product.git
( cd "$R" && echo x > f && git -c user.name=t -c user.email=t@e commit -qam x )

run() {  # $1 = command string ; stderr -> $SB/err ; no token in play -> deny path
  printf '{"cwd":"%s","tool_input":{"command":"%s"}}' "$R" "$1" | bash "$GATE" 2>"$SB/err" >/dev/null
}

# compound: add + commit + push -> DENY with the "commit did NOT run" note
run "git add f && git commit -m x && git ${P} origin main"
grep -q 'did NOT run either' "$SB/err" && ok "compound add/commit/${P}: note present" || bad "compound: note MISSING ($(cat "$SB/err"))"

# commit + push -> note present
run "git commit -am y && git ${P}"
grep -q 'did NOT run either' "$SB/err" && ok "commit+${P}: note present" || bad "commit+push: note missing"

# plain push -> NO note (nothing was staged/committed to warn about)
run "git ${P} origin main"
grep -q 'did NOT run either' "$SB/err" && bad "plain ${P}: note wrongly present" || ok "plain ${P}: no note (correct)"

# a push preceded by a NON-commit command (e.g. a build) -> NO note
run "make && git ${P}"
grep -q 'did NOT run either' "$SB/err" && bad "build+${P}: note wrongly present" || ok "non-commit prefix: no note (correct)"

echo "── push-gate-precommit-note: $pass passed, $fail failed"
[ "$fail" = 0 ]
