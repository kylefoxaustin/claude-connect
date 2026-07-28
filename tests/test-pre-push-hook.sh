#!/usr/bin/env bash
# PRE-PUSH HOOK (2026-07-28): closes the scripted-bypass hole in the PreToolUse push gate. The gate
# only greps the Bash tool-call STRING for "push", so a `git push` inside a script / `bash -c` / a
# `make` target / a git alias sails through. A global `pre-push` git hook fires on the REAL push
# regardless of invocation, and git hands it the actual refs+shas+remote, so it SHA-pins exactly and
# tells a true no-op from a real move. Drives the REAL bus/git-hooks/pre-push AND bus/push-gate.sh.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOK="$ROOT/bus/git-hooks/pre-push"
GATE="$ROOT/bus/push-gate.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-claims" "$COORD_STATE_DIR/push-requests"
GA=(-c user.name=t -c user.email=t@e -c commit.gpgsign=false -c init.defaultBranch=main)
HOOKS="$SB/hooks"; mkdir -p "$HOOKS"; cp "$HOOK" "$HOOKS/pre-push"; chmod +x "$HOOKS/pre-push"

git "${GA[@]}" init -q --bare "$SB/remote.git"
REPO="$SB/work"; git "${GA[@]}" init -q "$REPO"
git "${GA[@]}" -C "$REPO" config core.hooksPath "$HOOKS"       # per-repo: mimics the global arm
git "${GA[@]}" -C "$REPO" remote add origin "$SB/remote.git"
( cd "$REPO" && echo one > a && git "${GA[@]}" add a && git "${GA[@]}" commit -qm one )
HEAD="$(git -C "$REPO" rev-parse HEAD)"
KEY="$(printf '%s' "$REPO" | tr '/ ' '__' | sed 's/^_*//')"
TOK="$COORD_STATE_DIR/push-tokens/$KEY"; CLM="$COORD_STATE_DIR/push-claims/$KEY"; REQ="$COORD_STATE_DIR/push-requests/$KEY"
now="$(date +%s)"
# push the REAL branch through the hook (git normalizes any hook rejection to `git push` exit 1)
P() { ( cd "$REPO" && git "${GA[@]}" push origin main >/dev/null 2>"$SB/perr" ); echo $?; }

echo "── the bypass, closed: an unapproved push is stopped by the hook itself"
rm -f "$TOK" "$CLM" "$REQ"
[ "$(P)" = 1 ] && ok "unapproved push DENIED (exit 1)" || bad "unapproved push not denied"
[ -f "$REQ" ] && ok "request filed for Kyle's inbox" || bad "no request filed"
grep -q 'pre-push hook' "$SB/perr" && ok "message names the pre-push hook" || bad "message missing"

echo "── valid token, sha matches a pushed ref -> ALLOW + consume (one push per approval)"
printf 'expires=%s\nsha=%s\napproved_at=x\n' "$((now+300))" "$HEAD" > "$TOK"; rm -f "$CLM"
[ "$(P)" = 0 ] && ok "approved push allowed" || bad "approved push blocked"
[ ! -f "$TOK" ] && ok "token consumed" || bad "token not consumed"

echo "── genuine no-op (nothing to push) -> ALLOW, no token needed"
rm -f "$TOK" "$CLM"
[ "$(P)" = 0 ] && ok "no-op push allowed with no token" || bad "no-op push blocked"

echo "── PreToolUse hand-off: a fresh matching CLAIM (token already consumed at tool layer) -> ALLOW"
( cd "$REPO" && echo two > b && git "${GA[@]}" add b && git "${GA[@]}" commit -qm two )
HEAD2="$(git -C "$REPO" rev-parse HEAD)"
rm -f "$TOK"; printf 'sha=%s\nepoch=%s\n' "$HEAD2" "$now" > "$CLM"
[ "$(P)" = 0 ] && ok "claimed direct-push allowed" || bad "claimed push blocked"
[ ! -f "$CLM" ] && ok "claim honoured once, then removed" || bad "claim not consumed"

echo "── SHA-pin: token for a DIFFERENT commit -> DENY, token preserved"
( cd "$REPO" && echo three > c && git "${GA[@]}" add c && git "${GA[@]}" commit -qm three )
HEAD3="$(git -C "$REPO" rev-parse HEAD)"
printf 'expires=%s\nsha=deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n' "$((now+300))" > "$TOK"; rm -f "$CLM"
[ "$(P)" = 1 ] && ok "mismatched-sha push denied" || bad "mismatch not denied"
[ -f "$TOK" ] && ok "mismatched token NOT consumed" || bad "mismatch burned token"

echo "── expired token -> DENY + clear; stale claim -> DENY"
printf 'expires=%s\nsha=%s\n' "$((now-10))" "$HEAD3" > "$TOK"; rm -f "$CLM"
[ "$(P)" = 1 ] && ok "expired-token push denied" || bad "expired not denied"
[ ! -f "$TOK" ] && ok "expired token cleared" || bad "expired token lingered"
printf 'sha=%s\nepoch=%s\n' "$HEAD3" "$((now-999))" > "$CLM"; rm -f "$TOK"
[ "$(P)" = 1 ] && ok "stale claim (> TTL) rejected" || bad "stale claim honoured"

echo "── fleet-backup remote is EXEMPT (auto-push must never need a tap)"
rm -f "$TOK" "$CLM"
printf 'refs/heads/main %s refs/heads/main 0000000000000000000000000000000000000000\n' "$HEAD3" \
  | "$HOOKS/pre-push" origin "git@github.com:kylefoxaustin/fleet-backup.git" >/dev/null 2>&1
[ "$?" = 0 ] && ok "fleet-backup exempt" || bad "fleet-backup not exempt"

echo "── chaining: a repo-local pre-push that rejects blocks the push (its policy preserved)"
mkdir -p "$REPO/.git/hooks"
printf '#!/usr/bin/env bash\nexit 7\n' > "$REPO/.git/hooks/pre-push"; chmod +x "$REPO/.git/hooks/pre-push"
printf 'expires=%s\nsha=%s\n' "$((now+300))" "$HEAD3" > "$TOK"   # valid token present...
[ "$(P)" = 1 ] && ok "repo-local rejection blocks despite a valid token (chaining fired)" || bad "chaining did not fire"
rm -f "$REPO/.git/hooks/pre-push"

echo "── the PreToolUse gate writes the claim on approve (the hand-off end)"
printf 'expires=%s\nsha=%s\n' "$((now+300))" "$HEAD3" > "$TOK"; rm -f "$CLM"
printf '{"cwd":"%s","tool_input":{"command":"git push origin main"}}' "$REPO" | bash "$GATE" >/dev/null 2>&1
[ ! -f "$TOK" ] && ok "gate consumed the token" || bad "gate didn't consume"
[ -f "$CLM" ] && grep -q "sha=$HEAD3" "$CLM" && ok "gate wrote a sha-matched claim for the hook" || bad "gate didn't write claim"

echo "── push-gate: $pass passed, $fail failed"
[ "$fail" = 0 ]
