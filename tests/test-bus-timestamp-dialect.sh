#!/usr/bin/env bash
# The bus speaks two timestamp dialects, and two call sites only understood one.
#
# Headers used to be `## YYYY-MM-DD HH:MM [tag]`. Interactive posts now carry seconds.
# Two greps in bus.sh matched `HH:MM \[` — minute precision, space, bracket — so they saw
# only the minute-precision minority and kept working. Nothing ever errored.
#
# MEASURED on the live bus, 2026-08-24: 14 of 567 headers matched, and every one of the 14
# came from an automated sender (tenant-watch, resource-watchdog, operator). So:
#   * mark_seen_if_bus_tag (~257) set a first-contact baseline of 2026-08-23 16:12 when the
#     true newest was 2026-08-24 13:21:33 — a brand-new session starts with a fake backlog.
#   * prompt-check (~2571) could only COUNT those 14, so the per-prompt nudge reported
#     "N pending, newest <yesterday's automated message>" while directed mail went unmentioned.
#
# ⭐ CONFIRMED FIRST-HAND, which is why this test exists rather than a comment: two messages
# addressed to claude-connect on 2026-08-24 never appeared in the nudge. Kyle had to say
# "check messages". A counter that cannot see 97% of the log is not a quiet counter, it is a
# broken sensor that reports a plausible number.
#
# Found by image_gen. Census reproduced independently before anything was changed.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
mkdir -p "$SB/home/.claude/bus-state" "$SB/claude-connect"

# A log in BOTH dialects. The two seconds-bearing posts are the ones the old regex drops,
# and one of them is directed mail — the case that actually costs something.
cat > "$SB/messages.md" <<'LOG'
## 2026-08-20 10:00 [resource-watchdog]

to:other:qualcomm — automated, minute precision.

## 2026-08-21 11:30:15 [other:image_gen]

to:claude-connect — DIRECTED, seconds precision. Dropping this is the bug.

## 2026-08-22 09:00 [operator]

minute-precision broadcast.

## 2026-08-23 21:32:06 [other:holobench]

to:95emulator — the true newest, seconds precision.
LOG

printf 'other:claude-connect\n' > "$SB/home/.claude/bus-state/active-tags"
printf '2026-08-21 00:00:00\n'  > "$SB/home/.claude/bus-state/other:claude-connect.last-seen"

nudge() {
  (cd "$SB/claude-connect" && env HOME="$SB/home" BUS_FILE="$SB/messages.md" \
      BUS_STATE_DIR="$SB/home/.claude/bus-state" bash "$BUS" prompt-check 2>/dev/null)
}

out="$(nudge)"

# 1. the count must cover both dialects.
# ⚠️ The wording moved after this was written: the nudge now leads with how many are ADDRESSED
# TO YOU and reports the fleet total second (lostchild's two-denominators finding). So assert on
# the total, which is the number this test is actually about, rather than on a phrase.
case "$out" in
  *"3 new on the bus"*) ok "nudge counts all dialects (3 total, not 1)" ;;
  *"1 new on the bus"*) bad "nudge saw only the minute-precision message — the regex is still HH:MM-only" ;;
  *)                    bad "no recognisable total: $(printf '%s' "$out" | tr -d '\n' | head -c 160)" ;;
esac

# 2. the DIRECTED seconds-precision sender must be named. This is the one that cost a
#    real message today; a count that is right for the wrong reason still hides it.
case "$out" in
  *other:image_gen*) ok "the directed seconds-precision sender is named" ;;
  *)                 bad "directed mail from a seconds-precision sender is invisible" ;;
esac

# 3. "newest" must be the true newest, not the newest thing the regex happened to match
case "$out" in
  *"2026-08-23 21:32:06"*) ok "newest is the true newest" ;;
  *"2026-08-22 09:00"*)    bad "newest pinned to the last minute-precision header" ;;
  *)                       bad "unexpected newest in: $(printf '%s' "$out" | head -c 120)" ;;
esac

# 4. a cursor already past everything must still report nothing — the control. Without it,
#    "counts more" would be satisfied by a counter that simply always counts.
printf '2026-08-24 00:00:00\n' > "$SB/home/.claude/bus-state/other:claude-connect.last-seen"
out2="$(nudge)"
# ⚠️ This used to match on the word "pending", which the nudge no longer contains — so the
# control would have passed no matter what the nudge said. Assert SILENCE, which is the
# property, not a phrase that can be reworded out from under the test.
if [ -z "$out2" ]; then
  ok "cursor past the tail: silent (no false positives)"
else
  bad "nudged with nothing new: $(printf '%s' "$out2" | tr -d '\n' | head -c 140)"
fi

# 5. the shape itself, so nobody reintroduces it in a third call site
if grep -qE "\[0-9\]\{2\}:\[0-9\]\{2\} \\\\\[" "$BUS"; then
  bad "a minute-only header regex is still present in bus.sh"
else
  ok "no minute-only header regex remains anywhere in bus.sh"
fi

echo "── bus-timestamp-dialect: $pass passed, $fail failed"
[ "$fail" = 0 ]
