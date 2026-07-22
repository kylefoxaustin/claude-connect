#!/usr/bin/env bash
# fleet-backup is EXEMPT from the push gate (Kyle's policy, 2026-07-21): a private
# disaster-recovery backup whose value IS auto-push. The exemption must be
# SPOOF-RESISTANT — keyed on the origin REMOTE slug, not the dir basename, so a
# stray `mkdir fleet-backup` (no remote / wrong remote) is NOT exempt. Drives the
# REAL bus/push-gate.sh.
set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/bus/push-gate.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
have_git=1; command -v git >/dev/null 2>&1 || have_git=0

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests"

# make a git repo at $1 with origin remote $2 (empty = no remote)
mkrepo() {
  mkdir -p "$1"; git -C "$1" init -q 2>/dev/null
  [ -n "$2" ] && git -C "$1" remote add origin "$2" 2>/dev/null || true
}
run() {  # run gate against a push in dir $1; echoes exit code, stderr -> $SB/err
  printf '{"cwd":"%s","tool_input":{"command":"git push origin main"}}' "$1" \
    | bash "$GATE" 2>"$SB/err"; echo $?
}
requests() { ls "$COORD_STATE_DIR/push-requests" 2>/dev/null | wc -l | tr -d ' '; }

if [ "$have_git" = 0 ]; then echo "git unavailable — skipping"; exit 0; fi

# 1. the REAL fleet-backup (https remote) -> EXEMPT (allow, no token, no request)
R1="$SB/fleet-backup"; mkrepo "$R1" "https://github.com/kylefoxaustin/fleet-backup.git"
before="$(requests)"
[ "$(run "$R1")" = 0 ] && ok "fleet-backup (https): ALLOWED with no token" || bad "fleet-backup https not allowed"
[ "$(requests)" = "$before" ] && ok "fleet-backup: filed NO request" || bad "fleet-backup filed a request"

# 2. ssh remote form of the same slug -> EXEMPT
R2="$SB/fb-ssh"; mkrepo "$R2" "git@github.com:kylefoxaustin/fleet-backup.git"
[ "$(run "$R2")" = 0 ] && ok "fleet-backup (git@ ssh): ALLOWED" || bad "fleet-backup ssh not allowed"

# 3. SPOOF: a dir literally named fleet-backup but with NO remote -> NOT exempt (DENY)
R3="$SB/spoofdir/fleet-backup"; mkrepo "$R3" ""
[ "$(run "$R3")" = 2 ] && ok "spoof (basename only, no remote): DENIED" || bad "spoof by basename was exempted!"

# 4. SPOOF: fleet-backup name but a DIFFERENT remote (someone else's repo) -> DENY
R4="$SB/evil/fleet-backup"; mkrepo "$R4" "https://github.com/attacker/fleet-backup.git"
[ "$(run "$R4")" = 2 ] && ok "spoof (wrong owner slug): DENIED" || bad "wrong-owner slug was exempted!"

# 5. a normal product repo -> still gated (unchanged behaviour)
R5="$SB/claude-connect"; mkrepo "$R5" "https://github.com/kylefoxaustin/claude-connect.git"
[ "$(run "$R5")" = 2 ] && ok "product repo: still DENIED (gate intact)" || bad "product repo slipped through"

# 6. non-push in fleet-backup still sails through untouched (fast path, exit 0)
ec="$(printf '{"cwd":"%s","tool_input":{"command":"git log --oneline"}}' "$R1" | bash "$GATE" 2>/dev/null; echo $?)"
[ "$ec" = 0 ] && ok "non-push in fleet-backup: sails through" || bad "non-push gated"

echo "── push-gate-backup-exempt: $pass passed, $fail failed"
[ "$fail" = 0 ]
