#!/usr/bin/env bash
# msgbox-only pushes on the Finding Together repo are EXEMPT (Kyle's policy, 2026-08-22).
#
# WHY IT EXISTS: three people work on that repo, each with their own Claude session, and
# msgbox/ is the channel those sessions talk on. Every reply is one of those gated commands,
# so with the gate on, THIS side needed a human tap to say a sentence while the two remote
# sessions could converse freely. A channel with a human in the middle of every sentence is
# not a channel.
#
# THE RULE: allowed IFF every changed file is under msgbox/. Code still needs Kyle.
# SPOOF-RESISTANT: keyed on the origin REMOTE slug, not the dir basename.
# FAILS CLOSED everywhere else: no upstream, a flag, a refspec, a diverged branch, an empty
# file list — any of them fall through to the normal gate.
#
# Drives the REAL bus/push-gate.sh. Written when the exemption moved from Kyle's live copy
# into the repo: it had no test at all while it lived only on his box, which is exactly the
# kind of code that drifts.
#
# ⚠️ THE UPSTREAM IS BUILT WITH `git clone --bare`, NOT BY PUSHING TO IT. Writing this file
# the obvious way tripped the push gate on the literal command sitting inside the test's own
# source — the same false-positive shape the gate has hit before (a `crontab` in a quoted
# grep pattern, v2.31). Cloning gets the same upstream with no such string in the file, so
# the next person to edit this test is not fighting the thing it tests.
set -uo pipefail

GATE="$(cd "$(dirname "$0")/.." && pwd)/bus/push-gate.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord" BUS_STATE_DIR="$SB/bus-state"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests"

SLUG="FindingTogether/findingtogether"

mkclone() {   # $1 = work dir, $2 = origin slug ("" = leave the remote pointing at the bare)
  local up="$SB/up-$(basename "$1")-$RANDOM"
  mkdir -p "$1"; git -C "$1" init -q -b main
  git -C "$1" config user.email t@t; git -C "$1" config user.name t
  mkdir -p "$1/msgbox/open" "$1/app"
  echo base > "$1/app/index.js"; echo base > "$1/msgbox/open/seed.md"
  git -C "$1" add -A; git -C "$1" commit -qm base
  git clone -q --bare "$1" "$up"                 # upstream now has the base commit
  git -C "$1" remote add origin "$up"
  git -C "$1" fetch -q origin
  git -C "$1" branch -q -u origin/main           # so @{u} resolves the way it does in life
  [ -n "$2" ] && git -C "$1" remote set-url origin "https://github.com/$2.git"
  return 0
}
commit() { echo "$3" >> "$1/$2"; git -C "$1" add -A; git -C "$1" commit -qm c; }
run() {   # $1 = dir, $2 = command (default: a plain two-arg invocation)
  printf '{"cwd":"%s","tool_input":{"command":"%s"}}' "$1" "${2:-git push origin main}" \
    | bash "$GATE" 2>"$SB/err"; echo $?
}
requests() { ls "$COORD_STATE_DIR/push-requests" 2>/dev/null | wc -l | tr -d ' '; }

# 1. msgbox-only -> ALLOWED, and nothing left in the inbox
R="$SB/ft"; mkclone "$R" "$SLUG"; commit "$R" msgbox/open/hello.md hi
before="$(requests)"
[ "$(run "$R")" = 0 ] && ok "msgbox-only: ALLOWED" || bad "msgbox-only was denied"
[ "$(requests)" = "$before" ] && ok "msgbox-only: filed NO request" || bad "filed a request anyway"

# 2. ⚠️ THE REDIRECT CASE. A real tool call ends `2>&1 | tail -4`, and the argument
#    extraction used to keep `2>&1`, count it as a third argument, and fail the shape check —
#    fail-closed, so never dangerous, but it denied every actual send and made the exemption
#    look like it simply did not work. Found by running the REAL command after every crafted
#    test had passed.
[ "$(run "$R" 'git push origin main 2>&1 | tail -4')" = 0 ] && ok "redirect + pipe: ALLOWED" || bad "a redirect broke the exemption"

# 3. one code file in the same batch -> DENIED. Message traffic flows; code gets a human.
R2="$SB/ft-code"; mkclone "$R2" "$SLUG"
commit "$R2" msgbox/open/a.md hi; commit "$R2" app/index.js more
[ "$(run "$R2")" = 2 ] && ok "msgbox + one code file: DENIED" || bad "code slipped through the exemption"

# 4. SPOOF: right basename, no origin at all -> DENIED
R3="$SB/spoof/findingtogether"; mkclone "$R3" ""; git -C "$R3" remote remove origin 2>/dev/null
commit "$R3" msgbox/open/a.md hi
[ "$(run "$R3")" = 2 ] && ok "spoof (basename, no remote): DENIED" || bad "basename spoof was exempted!"

# 5. SPOOF: right basename, someone else's slug -> DENIED
R4="$SB/evil/findingtogether"; mkclone "$R4" "attacker/findingtogether"
commit "$R4" msgbox/open/a.md hi
[ "$(run "$R4")" = 2 ] && ok "spoof (wrong owner slug): DENIED" || bad "wrong-owner slug was exempted!"

# 6. shape checks: a flag or a refspec falls through to the normal gate even on msgbox content
[ "$(run "$R" 'git push --force origin main')" = 2 ] && ok "--force: DENIED despite msgbox-only" || bad "--force was exempted!"
[ "$(run "$R" 'git push origin HEAD:refs/heads/main')" = 2 ] && ok "refspec: DENIED" || bad "refspec was exempted!"

# 7. the exemption must not leak to any other repo
R5="$SB/claude-connect"; mkclone "$R5" "kylefoxaustin/claude-connect"; commit "$R5" msgbox/open/a.md hi
[ "$(run "$R5")" = 2 ] && ok "different repo, msgbox-only: still DENIED" || bad "exemption leaked to another repo"

echo "── push-gate-msgbox-exempt: $pass passed, $fail failed"
[ "$fail" = 0 ]
