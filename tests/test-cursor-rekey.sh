#!/usr/bin/env bash
# The load-bearing test for the member-keyed cursor (v4 §2.3, impl step 5). Drives the REAL bus.sh
# and proves the properties that, done wrong, lose mail:
#   T1 common case (member==tag) — behavior unchanged, single file.
#   T2 DRIFT — a session whose tag drifts keeps its cursor: no mail loss, no history re-dump.
#   T3 dual-write — Conductor's current-tag file stays correct with no change on its side.
#   T4 migration — a legacy tag-keyed cursor is carried over on the first member-keyed read.
#   T5 unbound session (no registry / no join) behaves byte-for-byte as today (tag cursor).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BUS="$HERE/../bus/bus.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
SD="$HOME/.claude/bus-state"; mkdir -p "$SD" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"; : > "$BUS_FILE"
TAB="$(printf '\t')"
# whitelist both the stable tag and the drifted tag so the cursor advances for each
printf 'backend\nother:beta\nother:alpha\n' > "$SD/active-tags"
# tag-map: cwd .../alpha resolves to tag `backend`; .../beta falls through to other:beta
printf '*/alpha%sbackend\n' "$TAB" > "$SD/tag-map"
# registry binds this session's sid -> member backend; pid-join binds the (overridden) pid -> sid
printf 'sid-be%sbackend%speer%salpha\n' "$TAB" "$TAB" "$TAB" > "$SD/members"
printf '77001%ssid-be\n' "$TAB" > "$SD/pid-sid"
W1="$HOME/w/alpha"; W2="$HOME/w/beta"; mkdir -p "$W1" "$W2"

pass=0 fail=0
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }
okc(){ if printf '%s' "$2" | grep -qF "$3"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — output missing [$3]"; fi; }
nokc(){ if printf '%s' "$2" | grep -qF "$3"; then fail=$((fail+1)); echo "FAIL: $1 — output SHOULD NOT contain [$3]"; else pass=$((pass+1)); fi; }
addmsg(){ printf '## %s [%s]\n%s\n\n' "$1" "$2" "$3" >> "$BUS_FILE"; }
seen(){ cat "$SD/$1.last-seen" 2>/dev/null || echo NONE; }

# confirm tag resolution is as intended
ok "W1 tag" "$(cd "$W1" && bash "$BUS" whoami)" "backend"
ok "W2 tag (drifted)" "$(cd "$W2" && bash "$BUS" whoami)" "other:beta"
ok "member is stable" "$(cd "$W2" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" whoami --member)" "backend"

# messages m1..m3, then a baseline pinned at m3 on the member cursor
addmsg "2026-07-18 10:01" "other:sender" "msg-one"
addmsg "2026-07-18 10:02" "other:sender" "msg-two"
addmsg "2026-07-18 10:03" "other:sender" "msg-three"
printf '2026-07-18 10:03\n' > "$SD/backend.last-seen"

# T1 — common case: from W1 (tag==member==backend), new mail m4/m5 shown, cursor advances, ONE file
addmsg "2026-07-18 10:04" "other:sender" "msg-four"
addmsg "2026-07-18 10:05" "other:sender" "msg-five"
OUT="$(cd "$W1" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" check 2>/dev/null)"
okc  "T1 shows new m4" "$OUT" "msg-four"
nokc "T1 no re-dump of m3" "$OUT" "msg-three"
ok   "T1 member cursor advanced" "$(seen backend)" "2026-07-18 10:05"

# T2 + T3 — DRIFT: from W2 (tag=other:beta, member=backend) add m6; must read the MEMBER cursor
addmsg "2026-07-18 10:06" "other:sender" "msg-six"
OUT="$(cd "$W2" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" check 2>/dev/null)"
okc  "T2 drift shows new m6" "$OUT" "msg-six"
nokc "T2 drift NO re-dump of m5" "$OUT" "msg-five"     # cursor was at m5 (member), not reset
nokc "T2 drift NO re-dump of m1" "$OUT" "msg-one"      # the loss/re-dump the whole change prevents
ok   "T2 member cursor advanced to m6" "$(seen backend)" "2026-07-18 10:06"
ok   "T3 dual-write: drifted tag file also current" "$(seen other:beta)" "2026-07-18 10:06"

# T4 — migration: fresh state, ONLY a legacy tag cursor exists (no member cursor) -> carried over
rm -f "$SD/backend.last-seen" "$SD/other:beta.last-seen" "$SD/backend.pending" "$SD/other:beta.pending"
printf '2026-07-18 10:05\n' > "$SD/other:beta.last-seen"   # legacy cursor at the drifted tag
OUT="$(cd "$W2" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" check 2>/dev/null)"
ok   "T4 migration seeded member cursor" "$(seen backend)" "2026-07-18 10:06"   # advanced from migrated 10:05 -> 10:06
okc  "T4 shows only post-migration mail" "$OUT" "msg-six"
nokc "T4 no re-dump before the migrated baseline" "$OUT" "msg-four"

# T5 — UNBOUND session (no join / not the bound pid): behaves as TODAY, keyed on the tag
rm -f "$SD"/*.last-seen "$SD"/*.pending
printf '2026-07-18 10:05\n' > "$SD/other:beta.last-seen"
OUT="$(cd "$W2" && bash "$BUS" check 2>/dev/null)"   # no CLAUDE_PID_OVERRIDE -> my_member falls back to tag
ok   "T5 unbound advances the TAG cursor" "$(seen other:beta)" "2026-07-18 10:06"
okc  "T5 unbound shows new mail" "$OUT" "msg-six"

echo "---"; echo "cursor-rekey: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
