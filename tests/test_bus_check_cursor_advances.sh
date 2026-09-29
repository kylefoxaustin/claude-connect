#!/usr/bin/env bash
# Regression test for bus.sh:2177 — `check` crashed with NameError after printing its
# success footer, so the cursor never advanced and a backlog was UNWALKABLE.
#
# WHY THIS TEST EXISTS, AND WHY THE OLD ONES MISSED IT (95emulator's finding):
# the original suite asserted that OUTPUT APPEARED. Display and cursor-advance are
# different code paths -- the advance sits behind WL==1 -- so every display assertion
# passed while the watermark never moved. An advance you never watch advancing is
# indistinguishable from one that never happens.
#
# So every assertion here is on the CURSOR, not on stdout. The test also carries a
# NEGATIVE CONTROL: it reconstructs the bug and requires the harness to catch it,
# because a test that cannot fail is not evidence that the code is right.
#
# BUS_SH overrides which copy is tested, so this can verify an INSTALL:
#     BUS_SH=~/.claude/bin/bus.sh bash tests/test_bus_check_cursor_advances.sh
# It runs against a scratch HOME and a scratch bus, so it never reads, advances, or
# consumes any real session's mail. Verifying an install by running `bus.sh check`
# against the live bus does not work and is not safe: the tag comes from the CWD, so
# from a home directory it resolves to a tag with no mail and no cursor moves no matter
# what is installed -- and from a real project directory it would consume that session's
# mail to satisfy a test.
set -u
BUS="${BUS_SH:-$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }

setup(){  # $1 = message count
  T=$(mktemp -d); H="$T/home"; BF="$T/bus.md"
  mkdir -p "$H/.claude/bus-state" "$T/proj/testmail"
  echo "other:testmail" > "$H/.claude/bus-state/active-tags"   # WL=1, else the advance is skipped
  : > "$BF"
  for i in $(seq 1 "$1"); do i=$(printf %02d "$i");
    printf '\n## 2026-09-26 10:%s:00 [other:sender]\n\nto:testmail — message %s body\n' "$i" "$i" >> "$BF"
  done
  CUR="$H/.claude/bus-state/other:testmail.last-seen"
  echo "2026-09-26 09:00:00" > "$CUR"
}
check(){ (cd "$T/proj/testmail" && HOME="$H" BUS_FILE="$BF" bash "${1:-$BUS}" check 2>&1); }

# 1. the cursor advances at all, and to the newest message shown
setup 5
OUT=$(check); [ "$(cat "$CUR")" = "2026-09-26 10:05:00" ] \
  && ok "cursor advances to the newest shown message" \
  || no "cursor did not advance (got '$(cat "$CUR")')"
echo "$OUT" | grep -q 'NameError' && no "NameError in check output" || ok "no NameError"

# 2. a second check makes progress instead of re-showing the same batch
check | grep -q 'No new messages' && ok "second check reports nothing new (progress)" \
  || no "second check re-showed the same batch"

# 3. NEGATIVE CONTROL — rebuild the defect; the harness MUST catch it
setup 5
BUGGY="$T/buggy.sh"; sed '2177s/sel\[-1\]/shown[-1]/' "$BUS" > "$BUGGY"
if ! cmp -s "$BUS" "$BUGGY"; then
  check "$BUGGY" >/dev/null 2>&1
  [ "$(cat "$CUR")" = "2026-09-26 09:00:00" ] \
    && ok "negative control: reconstructed bug leaves the cursor stuck (harness can detect it)" \
    || no "negative control FAILED TO FAIL -- this test cannot detect the bug it guards"
else
  no "negative control could not be built (line 2177 moved; update this test)"
fi

# 4. the capped path never advances past an undisplayed message
setup 25   # CAP=20 in the check path
OUT=$(check)
[ "$(echo "$OUT" | grep -c 'message .* body')" = 20 ] && ok "capped: shows CAP=20 of 25" || no "capped: wrong count"
[ "$(cat "$CUR")" = "2026-09-26 10:20:00" ] \
  && ok "capped: cursor stops at the 20th -- never past an undisplayed message" \
  || no "capped: cursor at '$(cat "$CUR")', expected 10:20:00"
echo "$OUT" | grep -q '5 REMAIN' && ok "capped: discloses the remainder" || no "capped: remainder undisclosed"
OUT2=$(check)
[ "$(echo "$OUT2" | grep -c 'message .* body')" = 5 ] \
  && ok "capped: round 2 delivers exactly the remaining 5 (25/25, no loss, no dup)" \
  || no "capped: round 2 delivered wrong count"

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
