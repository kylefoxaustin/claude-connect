#!/usr/bin/env bash
# A FILED REQUEST MUST NAME WHO ASKED, BY STABLE IDENTITY.
#
# Kyle tapped Approve SIX times for two repos and nothing happened (agentic-skills-imx,
# 2026-10-10). The verdict could only be routed by `cwd`, and the two gates DISAGREE about
# what that field holds:
#
#     bus/push-gate.sh     (tool layer)  cwd = the SESSION's dir
#     ~/.claude/git-hooks/pre-push       cwd = $PWD, which git sets to the REPO TOPLEVEL
#
# So a session pushing a repo other than its own project filed a cwd no session lives in,
# Conductor resolved the recipient to None, and the verdict was dropped in silence.
#
# The reporter's own evidence is the sharpest form of it: in ONE session, minutes apart, a
# SPURIOUS request filed by the tool layer delivered perfectly while both GENUINE pushes
# resolved to nobody. Deliverability tracked WHICH CODE PATH FILED THE REQUEST, not whether
# the request was real.
#
# `session_id` is the fix because it is a real join key, both halves VERIFIED on this box:
#   - a git-spawned hook inherits CLAUDE_CODE_SESSION_ID from the Bash tool call
#   - it is byte-identical to the session_id Conductor derives from the transcript
#
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

REPO="$SB/repo"; mkdir -p "$REPO"
git "${GA[@]}" init -q "$REPO"
git "${GA[@]}" -C "$REPO" remote add origin https://github.com/kylefoxaustin/product.git
( cd "$REPO" && echo a > f && git "${GA[@]}" add f && git "${GA[@]}" commit -qm A )
KEY="$(printf '%s' "$REPO" | tr '/ ' '__' | sed 's/^_*//')"
REQ="$COORD_STATE_DIR/push-requests/$KEY"

run() { printf '{"cwd":"%s","tool_input":{"command":"git push origin main"}}' "$REPO" \
        | bash "$GATE" 2>"$SB/err"; echo $?; }

# 1. with a session id in the environment, the filed request carries it
rm -f "$REQ"
CLAUDE_CODE_SESSION_ID="abc-123-def" run >/dev/null
if [ -f "$REQ" ]; then
  ok "a denied push files a request (unchanged)"
  if grep -qx 'session_id=abc-123-def' "$REQ"; then
    ok "the request NAMES the asking session by stable identity"
  else
    bad "no session_id in the request — the verdict will be unroutable again"
    sed 's/^/       /' "$REQ"
  fi
else
  bad "no request filed at all"
fi

# 2. cwd must STILL be recorded — it is the fallback for an un-upgraded peer gate
grep -q "^cwd=$REPO$" "$REQ" && ok "cwd still recorded (fallback path intact)" \
  || bad "cwd was dropped — older Conductors could not route at all"

# 3. ⚠️ AN ABSENT SESSION ID MUST NOT BREAK THE GATE. The gate is a security control; it has
#    to fail toward DENY, never toward a crash or an allow, when the env is not what we expect.
rm -f "$REQ"
rc="$(env -u CLAUDE_CODE_SESSION_ID bash -c '
  printf "{\"cwd\":\"'"$REPO"'\",\"tool_input\":{\"command\":\"git push origin main\"}}" \
  | COORD_STATE_DIR="'"$COORD_STATE_DIR"'" bash "'"$GATE"'" 2>/dev/null; echo $?' | tail -1)"
[ "$rc" = 2 ] && ok "no session id in env: still DENIES (fails closed)" \
  || bad "unset session id changed the verdict (rc=$rc)"
[ -f "$REQ" ] && ok "no session id in env: request still filed" || bad "request not filed without the env var"
grep -qx 'session_id=' "$REQ" && ok "empty session_id written -> Conductor falls back to cwd" \
  || bad "session_id line malformed when the env var is unset"

# 4. the gate's FAST PATH must stay a no-op for anything that is not a push. This is the
#    property the whole gate rests on (never add latency or risk to normal bash).
rm -f "$REQ"
rc2="$(printf '{"cwd":"%s","tool_input":{"command":"echo git push"}}' "$REPO" | bash "$GATE" >/dev/null 2>&1; echo $?)"
[ "$rc2" = 0 ] && ok "non-push still sails through" || bad "non-push was gated (rc=$rc2)"
[ ! -f "$REQ" ] && ok "non-push filed no request" || bad "non-push filed a request"

echo "── push-gate-records-session: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
