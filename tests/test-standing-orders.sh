#!/usr/bin/env bash
# The FLEET STANDING ORDERS must lead EVERY session's SessionStart context — whitelisted or not,
# empty bus or not — so no session (running, idle, stopped, or not yet created) can claim it never
# saw Kyle's law. Drives the REAL bus/bus.sh session-start hook.
set -uo pipefail

BUSSH="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
SO_SRC="$(cd "$(dirname "$0")/.." && pwd)/bus/standing-orders.md"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

setup() {
  SB="$(mktemp -d)"; export HOME="$SB"
  mkdir -p "$SB/.claude/bus-state" "$SB/proj/mytag"
  cp "$SO_SRC" "$SB/.claude/bus-state/standing-orders.md"
  BUS="$SB/bus.md"
  cd "$SB/proj/mytag"
}
# extract additionalContext; returns non-zero if the output isn't valid JSON
ctx() { python3 -c "import sys,json; print(json.load(sys.stdin)['hookSpecificOutput']['additionalContext'])"; }

# A) whitelisted + non-empty bus -> law leads, bus digest follows
setup
echo "other:mytag" > "$SB/.claude/bus-state/active-tags"
printf '## 2026-07-14 10:00 [other:alice]\n\nto:all — [alice] hi\n\n' > "$BUS"
c="$(BUS_FILE="$BUS" bash "$BUSSH" session-start 2>&1 | ctx)" \
  && ok "whitelisted: valid JSON" || bad "whitelisted: invalid JSON"
grep -q 'LAW 1' <<<"$c" && ok "whitelisted: standing orders present" || bad "whitelisted: no law"
grep -q 'Claude Bus' <<<"$c" && ok "whitelisted: bus digest present" || bad "whitelisted: no bus digest"
grep -qi 'report a number you have not measured' <<<"$c" && ok "law 1 headline present" || bad "law 1 headline missing"
grep -q 'HONOR THE RESERVATION' <<<"$c" && ok "law 2 present" || bad "law 2 missing"
rm -rf "$SB"

# B) un-whitelisted -> law STILL leads (universal), but no bus digest (scoped)
setup
c="$(BUS_WHITELIST="" BUS_FILE="$BUS" bash "$BUSSH" session-start 2>&1 | ctx)" \
  && ok "un-whitelisted: valid JSON" || bad "un-whitelisted: no/invalid output (law didn't lead!)"
grep -q 'LAW 1' <<<"$c" && ok "un-whitelisted: standing orders STILL present" || bad "un-whitelisted: law missing"
grep -q 'Claude Bus' <<<"$c" && bad "un-whitelisted leaked the bus digest" || ok "un-whitelisted: no bus digest (scoped)"
rm -rf "$SB"

# C) empty bus (whitelisted) -> law still leads
setup
echo "other:mytag" > "$SB/.claude/bus-state/active-tags"
: > "$BUS"
c="$(BUS_FILE="$BUS" bash "$BUSSH" session-start 2>&1 | ctx)" \
  && ok "empty-bus: valid JSON" || bad "empty-bus: invalid JSON"
grep -q 'LAW 1' <<<"$c" && ok "empty-bus: standing orders present" || bad "empty-bus: law missing"
rm -rf "$SB"

# D) no standing-orders file installed -> hook still works, just no law block (graceful)
setup
echo "other:mytag" > "$SB/.claude/bus-state/active-tags"
rm -f "$SB/.claude/bus-state/standing-orders.md"
printf '## 2026-07-14 10:00 [other:alice]\n\nto:all — [alice] hi\n\n' > "$BUS"
c="$(BUS_FILE="$BUS" bash "$BUSSH" session-start 2>&1 | ctx)" \
  && ok "no-SO-file: hook still emits valid JSON" || bad "no-SO-file: hook broke without the file"
grep -q 'Claude Bus' <<<"$c" && ok "no-SO-file: bus digest still delivered" || bad "no-SO-file: lost the bus digest"
rm -rf "$SB"

echo "── standing-orders: $pass passed, $fail failed"
[ "$fail" = 0 ]
