#!/usr/bin/env bash
# END-TO-END: a DST fall-back night must not lose mail, driven through the REAL send and
# check paths rather than a model of them.
#
# BEFORE the bus clock, measured with this exact scenario: of 4 messages sent after a
# cursor was set, 2 were delivered and 2 were SKIPPED PERMANENTLY — stamped below the
# cursor while being an hour later in real time, and unreachable by any command afterwards
# (`--all` reads only the live log; the rotation-gap recovery applies the same
# strict-greater filter).
#
# ⚠️ THE ISOLATION GUARD BELOW IS NOT CEREMONY. The first version of this test wrote FIVE
# MESSAGES INTO THE PRODUCTION BUS, because of this:
#
#     HOME=$H BUS_FILE=$BF printf '%s\n' "$msg" | bash bus.sh send -     # WRONG
#
# The `VAR=x` prefix binds to `printf`, not to `bash` on the other side of the pipe — so
# every "sandboxed" send ran against the real environment. A sandbox that can reach
# production is not a sandbox, so this file asserts its own isolation before sending
# anything, and again afterwards.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUS="${BUS_SH:-$ROOT/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

H="$T/home"; BF="$T/bus.md"; P="$T/proj/testmail"; S="$T/proj/sender"
mkdir -p "$H/.claude/bus-state" "$P" "$S"
echo "other:testmail" > "$H/.claude/bus-state/active-tags"
: > "$BF"
REAL_BUS="$HOME/Documents/claude-bus/messages.md"
REAL_SIZE_BEFORE="$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)"

# Correct form: the env prefix is on the side of the pipe that RUNS bus.sh.
# Send from a DIFFERENT directory, so the sender tag differs from the reader's. `check`
# never echoes your own posts (by design), so a test that sends and reads under one tag
# measures that rule rather than the thing it means to test — it reported 0 delivered and
# looked exactly like mail loss.
send(){ printf '%s\n' "$1" | (cd "$S" && HOME="$H" BUS_FILE="$BF" bash "$BUS" send - >/dev/null 2>>"$T/err"); }
check(){ (cd "$P" && HOME="$H" BUS_FILE="$BF" bash "$BUS" check 2>>"$T/err"); }
cd "$P" || exit 1

# ── the isolation guard, BEFORE anything is written ─────────────────────────────────────
send "to:testmail — isolation probe"
if [ "$(wc -c < "$BF")" -gt 0 ]; then ok "writes land in the SANDBOX bus"; else no "sandbox bus is empty — send is not reaching it"; fi
if [ "$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)" = "$REAL_SIZE_BEFORE" ]; then
  ok "the REAL bus is untouched (isolation holds)"
else
  no "THE REAL BUS GREW — this test is not isolated; aborting"; printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"; exit 1
fi
: > "$BF"; rm -f "$H/.claude/bus-state"/*.last-seen "$H/.claude/bus-state"/*.delivered \
             "$H/.claude/bus-state/.bus-clock" 2>/dev/null || true

# ── the DST night ───────────────────────────────────────────────────────────────────────
# First pass through the 01:00 hour.
for m in "FIRST-pass A" "FIRST-pass B" "FIRST-pass C"; do send "to:testmail — $m"; done
check >/dev/null                                   # cursor is staged...
CUR="$H/.claude/bus-state/other:testmail.last-seen"
# ...and committed here. The two-phase commit defers to the turn's Stop hook, so a test
# that measured the watermark inside the same turn as the check would observe nothing and
# conclude, wrongly, that the cursor was frozen. That mistake has been made three times on
# this fleet; the clock state is what this test actually needs, so take it directly.
CLOCK="$H/.claude/bus-state/.bus-clock"
[ -s "$CLOCK" ] && ok "bus clock is being maintained by the real send path" || no "no .bus-clock written"
printf '%s\n' "$(cat "$CLOCK")" > "$CUR"           # cursor := newest delivered, as a real Stop would

# THE FOLD: wall clock jumps back an hour. Simulated by advancing the bus clock state,
# which is equivalent — the clamp's condition is `now <= stored`.
python3 - "$CLOCK" <<'PY'
import sys, datetime
p = sys.argv[1]
cur = open(p).read().strip()
d = datetime.datetime.strptime(cur, "%Y-%m-%d %H:%M:%S") + datetime.timedelta(minutes=50)
open(p, "w").write(d.strftime("%Y-%m-%d %H:%M:%S") + "\n")
PY

# Second pass: these are an hour LATER in real time but the wall clock reads lower.
for m in "SECOND-pass D" "SECOND-pass E"; do send "to:testmail — $m"; done

OUT="$(check)"
n="$(grep -c 'SECOND-pass' <<<"$OUT")"
[ "$n" = 2 ] && ok "both post-fold messages DELIVERED (2/2; was 2 of 4 lost before the clock)" \
  || no "only $n of 2 post-fold messages delivered — still losing mail"

# every stamp in the log must be strictly increasing, which is the invariant the readers assume
python3 - "$BF" <<'PY'
import re, sys
hdr = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) \[')
ts = [m.group(1) for m in (hdr.match(l) for l in open(sys.argv[1], encoding="utf-8", errors="replace")) if m]
bad = [(a, b) for a, b in zip(ts, ts[1:]) if not b > a]
print("MONOTONIC" if not bad else f"OUT-OF-ORDER: {bad[:3]}")
PY
[ "$(python3 -c "
import re,sys
hdr=re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) \[')
ts=[m.group(1) for m in (hdr.match(l) for l in open('$BF',encoding='utf-8',errors='replace')) if m]
print(sum(1 for a,b in zip(ts,ts[1:]) if not b>a))")" = 0 ] \
  && ok "every header in the log is strictly increasing" || no "log contains out-of-order headers"

grep -q 'CLOCK WENT BACKWARDS' "$T/err" && ok "the fold was reported, not silently absorbed" \
  || no "clock went backwards with no warning"

# ── the isolation guard again, AFTER ────────────────────────────────────────────────────
[ "$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)" = "$REAL_SIZE_BEFORE" ] \
  && ok "real bus still untouched at exit" || no "THE REAL BUS GREW DURING THIS TEST"

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
