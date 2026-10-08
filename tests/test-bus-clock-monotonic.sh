#!/usr/bin/env bash
# THE BUS CLOCK — header timestamps that never go backwards.
#
# Delivery is decided by STRING-comparing local-time stamps, which is only a valid time
# comparison while the wall clock increases. MEASURED against the real bus.sh: on a DST
# fall-back night, 2 of 4 messages sent AFTER a cursor was set were skipped permanently —
# stamped below the cursor while being an hour later in real time. The RTC-regression case
# is worse and unbounded: every stamp below every cursor, the fleet reports "No new
# messages" forever, and the rotation-gap recovery cannot fire because it triggers on
# `last < cur_oldest` and here `last` is ahead.
#
# ⚠️ THE TESTS THAT MATTER ARE THE ONES PROVING THE FIX CANNOT ITSELF LOSE MAIL. Three
# designs were rejected because they were WORSE than the bug, each demonstrated:
#   1. `date -d "$ts +1 second"` parses +1 as a UTC OFFSET -> a stamp ~6h in the PAST, rc=0.
#      That is the clamp's only firing path, so it would have converted "late" into "lost"
#      fleet-wide with a green exit code. `TZ=UTC date -d ...` is wrong the same way.
#   2. Even correct tz-aware arithmetic is non-monotonic at the fold: 01:59:59 CDT +1s
#      FORMATS as 01:00:00 CST. The increment must be naive calendar arithmetic.
#   3. Deriving "newest" by grepping the log is CONTENT-POISONABLE: `^## [0-9]` matches 1540
#      lines of the live log where only 1529 are headers, and a body quoting a future header
#      would ratchet the clock forward and lose everything until wall-clock caught up.
#      Hence: writer-owned state file, never the log.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUS="${BUS_SH:-$ROOT/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# Extract the clock block FROM the shipped script — never retype it, or this is a mirror.
python3 - "$BUS" "$T/clock.sh" <<'EX'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
i = s.index('_BUS_CLOCK="')
m = re.search(r"\n_cursor_commit_delivered\(\)", s[i:])
open(sys.argv[2], "w", encoding="utf-8").write(s[i:i + m.start()])
EX
[ -s "$T/clock.sh" ] && bash -n "$T/clock.sh" && ok "extracted the clock block from bus.sh; syntax clean" \
  || { no "could not extract the clock block (renamed?)"; printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"; exit 1; }

export _CURSOR_SD="$T/state"; mkdir -p "$_CURSOR_SD"
source "$T/clock.sh"
CLK="$_CURSOR_SD/.bus-clock"

# ── the increment: naive, fold-crossing, fail-safe ──────────────────────────────────────
[ "$(_bus_ts_plus1 '2026-11-01 01:59:59')" = "2026-11-01 02:00:00" ] \
  && ok "+1s crosses the DST fold FORWARD (date -d returns 2026-10-31 20:00:00 here)" \
  || no "+1s across the fold wrong: $(_bus_ts_plus1 '2026-11-01 01:59:59')"
[ "$(_bus_ts_plus1 '2026-10-07 19:08')" = "2026-10-07 19:08:01" ] \
  && ok "+1s on a MINUTE-precision stamp yields seconds" || no "minute-precision +1s wrong"
[ -z "$(_bus_ts_plus1 'not a timestamp')" ] && ok "garbage input -> empty (caller fails safe)" \
  || no "garbage input produced a value"
[ -z "$(_bus_ts_plus1 '')" ] && ok "empty input -> empty" || no "empty input produced a value"

# ── normal operation: the helper is identity and never warns ────────────────────────────
rm -f "$CLK"
a="$(_bus_ts 2>"$T/w1")"; sleep 1.1; b="$(_bus_ts 2>"$T/w2")"
[ -n "$a" ] && [ -n "$b" ] && [[ "$b" > "$a" ]] && ok "normal: stamps advance monotonically" \
  || no "normal operation not monotonic ($a then $b)"
[ ! -s "$T/w1" ] && [ ! -s "$T/w2" ] && ok "normal: silent (no spurious warnings)" || no "warned during normal operation"
[ "$(cat "$CLK")" = "$b" ] && ok "normal: state file tracks the last emitted stamp" || no "state file not updated"
[ "${#a}" = 19 ] && ok "emits full second precision" || no "stamp is not 19 chars: '$a'"

# ── THE BUG: wall clock goes backwards (DST fold / RTC regression) ──────────────────────
# Stored stamp is slightly AHEAD of now, i.e. the clock just fell back.
ahead="$(_bus_ts_plus1 "$(date -d '+45 minutes' '+%Y-%m-%d %H:%M:%S')")"
printf '%s\n' "$ahead" > "$CLK"
got="$(_bus_ts 2>"$T/w3")"
[[ "$got" > "$ahead" ]] && ok "clock went BACKWARDS -> emits a stamp strictly above the last one" \
  || no "backwards clock produced '$got', not above '$ahead' — THIS IS THE LOSS CASE"
[ -s "$T/w3" ] && ok "backwards clock WARNS on stderr (never silent)" || no "clamped silently"
[ "$(cat "$CLK")" = "$got" ] && ok "clamped value is persisted (so the next send stays ordered)" \
  || no "clamp not persisted — the next send would regress"

# repeated clamps must keep advancing, never plateau (a plateau = same-stamp collisions)
p1="$(_bus_ts 2>/dev/null)"; p2="$(_bus_ts 2>/dev/null)"; p3="$(_bus_ts 2>/dev/null)"
[[ "$p2" > "$p1" ]] && [[ "$p3" > "$p2" ]] && ok "successive clamps keep advancing (+1s each)" \
  || no "clamped stamps plateaued: $p1 $p2 $p3"

# ── the two slow-path events must be told apart ────────────────────────────────────────
# now == stored (same second, routine under load) must be SILENT; now < stored (the clock
# actually moved backwards) must be LOUD. Warning on the routine case trains people to
# ignore the line that matters.
rm -f "$CLK"
s1="$(_bus_ts 2>/dev/null)"                       # seeds the clock at "now"
printf '%s\n' "$s1" > "$CLK"                      # force the SAME-SECOND case exactly
s2="$(_bus_ts 2>"$T/w5")"
[[ "$s2" > "$s1" ]] && ok "same-second send still gets a distinct, greater stamp" \
  || no "same-second send collided: $s1 then $s2"
[ ! -s "$T/w5" ] && ok "same-second send is SILENT (routine, not an alarm)" \
  || no "same-second send warned: $(head -1 "$T/w5")"
# and the genuinely-backwards case must still shout
printf '%s\n' "$(_bus_ts_plus1 "$(date -d '+20 minutes' '+%Y-%m-%d %H:%M:%S')")" > "$CLK"
_bus_ts 2>"$T/w6" >/dev/null
grep -q 'CLOCK WENT BACKWARDS' "$T/w6" && ok "a backwards clock is still LOUD and named" \
  || no "backwards clock did not warn distinctly"

# ── THE SANITY BOUND: an absurd stored clock must NOT ratchet ───────────────────────────
# This is the content-poisoning defence: if something ever writes a far-future stamp, the
# clock must refuse to follow it rather than dragging every future message along.
printf '%s\n' "$(date -d '+30 days' '+%Y-%m-%d %H:%M:%S')" > "$CLK"
now_real="$(date '+%Y-%m-%d %H:%M:%S')"
got2="$(_bus_ts 2>"$T/w4")"
[[ ! "$got2" > "$(date -d '+1 day' '+%Y-%m-%d %H:%M:%S')" ]] \
  && ok "stored clock 30 days ahead -> REFUSES to ratchet, emits real time" \
  || no "ratcheted into the future: '$got2' — a poisoned clock would lose all mail"
[ -s "$T/w4" ] && ok "refusal is LOUD (names the discrepancy)" || no "refused silently"

# ── corrupted / missing state must never break a send ───────────────────────────────────
for bad in "garbage" "" "## 2026-11-01 01:30:00 [other:quoted]" "9999-99-99 99:99:99"; do
  printf '%s\n' "$bad" > "$CLK"
  v="$(_bus_ts 2>/dev/null)"
  [ "${#v}" = 19 ] || { no "corrupt state '$bad' produced a bad stamp: '$v'"; continue; }
done
ok "corrupt state file always still yields a well-formed stamp (never empty, never aborts)"
rm -f "$CLK"
v="$(_bus_ts 2>/dev/null)"; [ "${#v}" = 19 ] && ok "missing state file -> plain wall clock" || no "missing state broke the stamp"

# A stamp must NEVER be empty: `## ` with no timestamp matches no header regex, so the
# message would silently merge into the previous message's body.
chmod 500 "$_CURSOR_SD" 2>/dev/null || true
v="$(_bus_ts 2>/dev/null)"
chmod 700 "$_CURSOR_SD" 2>/dev/null || true
[ "${#v}" = 19 ] && ok "unwritable state dir -> still a valid stamp (degrades, never empties)" \
  || no "unwritable state dir produced '$v'"

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
