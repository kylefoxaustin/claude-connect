#!/usr/bin/env bash
# The load-bearing test for the two-phase commit (v4 §2.3.2, impl step 5b). Drives the REAL bus.sh
# and proves the property the 91emulator incident demands: the cursor advances ONLY when the turn
# that emitted the mail completes (its own Stop, matched by promptId). A turn that dies before its
# Stop re-delivers (at-least-once), and a later turn's Stop never commits a dead turn's read.
#   T0 flag OFF (default) — check advances .last-seen directly (step-5a), NO .delivered written.
#   T1 flag ON  — check writes a PENDING .delivered (with the turn marker), .last-seen UNCHANGED.
#   T2 Stop with MATCHING marker commits .delivered -> .last-seen, clears the record.
#   T3 Stop with MISMATCHED marker (a later/other turn) does NOT commit; discards the stale record.
#   T4 crash flow — check then NO stop-commit -> mail RE-DELIVERED on the next check (at-least-once).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BUS="$HERE/../bus/bus.sh"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
SD="$HOME/.claude/bus-state"; mkdir -p "$SD" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"; : > "$BUS_FILE"
TAB="$(printf '\t')"
printf 'backend\n' > "$SD/active-tags"
printf '*/alpha%sbackend\n' "$TAB" > "$SD/tag-map"   # cwd .../alpha -> tag `backend` (== member)
printf 'sid-be%sbackend%speer%salpha\n' "$TAB" "$TAB" "$TAB" > "$SD/members"
printf '77001%ssid-be\n' "$TAB" > "$SD/pid-sid"
W="$HOME/w/alpha"; mkdir -p "$W"
# a transcript for sid-be so _my_transcript (glob by session_id) + _turn_marker work
TXDIR="$HOME/.claude/projects/proj"; mkdir -p "$TXDIR"; TX="$TXDIR/sid-be.jsonl"
mk_tx(){ printf '{"type":"user","promptId":"%s","message":{"role":"user","content":"x"}}\n' "$1" > "$TX"; }

pass=0 fail=0
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }
okc(){ if printf '%s' "$2" | grep -qF "$3"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — missing [$3]"; fi; }
nokc(){ if printf '%s' "$2" | grep -qF "$3"; then fail=$((fail+1)); echo "FAIL: $1 — should NOT contain [$3]"; else pass=$((pass+1)); fi; }
seen(){ cat "$SD/$1.last-seen" 2>/dev/null || echo NONE; }
delivered(){ cat "$SD/$1.delivered" 2>/dev/null || echo NONE; }
run_check(){ (cd "$W" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" check 2>/dev/null); }
run_stop(){ printf '{"session_id":"sid-be","transcript_path":"%s"}' "$TX" \
  | (cd "$W" && CLAUDE_PID_OVERRIDE=77001 bash "$BUS" stop-commit >/dev/null 2>&1); }

addmsg(){ printf '## %s [%s]\n%s\n\n' "$1" "$2" "$3" >> "$BUS_FILE"; }
addmsg "2026-07-18 10:01" "other:sender" "msg-one"
addmsg "2026-07-18 10:02" "other:sender" "msg-two"
printf '2026-07-18 10:02\n' > "$SD/backend.last-seen"   # baseline at m2
mk_tx "turnA"

# T0 — flag OFF: check advances .last-seen directly, writes NO .delivered
addmsg "2026-07-18 10:03" "other:sender" "msg-three"
OUT="$(run_check)"
okc "T0 shows m3" "$OUT" "msg-three"
ok  "T0 advances .last-seen directly" "$(seen backend)" "2026-07-18 10:03"
ok  "T0 writes NO .delivered" "$(delivered backend)" "NONE"

# turn on two-phase for the rest
: > "$SD/two-phase"

# T1 — flag ON: check writes a PENDING .delivered (ts + marker), .last-seen UNCHANGED
addmsg "2026-07-18 10:04" "other:sender" "msg-four"
OUT="$(run_check)"
okc "T1 still shows m4" "$OUT" "msg-four"
ok  "T1 .last-seen NOT advanced (still m3)" "$(seen backend)" "2026-07-18 10:03"
ok  "T1 .delivered written with marker" "$(delivered backend)" "2026-07-18 10:04${TAB}turnA"

# T2 — Stop with the SAME turn marker commits it
run_stop
ok  "T2 Stop commits -> .last-seen advanced" "$(seen backend)" "2026-07-18 10:04"
ok  "T2 .delivered cleared" "$(delivered backend)" "NONE"

# T3 — MISMATCH: check emits (marker turnA), but the turn that commits is a DIFFERENT turn (turnB)
addmsg "2026-07-18 10:05" "other:sender" "msg-five"
OUT="$(run_check)"                       # writes .delivered with marker turnA
ok  "T3 delivered written (turnA)" "$(delivered backend)" "2026-07-18 10:05${TAB}turnA"
mk_tx "turnB"                            # a NEW turn is now current (the emitting turn died)
run_stop                                 # Stop of turnB sees marker turnB != turnA
ok  "T3 mismatched Stop does NOT commit (still m4)" "$(seen backend)" "2026-07-18 10:04"
ok  "T3 stale .delivered discarded" "$(delivered backend)" "NONE"

# T4 — the whole point: after the crash (no valid commit), m5 is RE-DELIVERED on the next check
mk_tx "turnC"
OUT="$(run_check)"
okc "T4 re-delivers m5 (never lost)" "$OUT" "msg-five"
nokc "T4 no re-dump of already-committed m4" "$OUT" "msg-four"

echo "---"; echo "two-phase-commit: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
