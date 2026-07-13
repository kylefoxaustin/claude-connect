#!/usr/bin/env bash
# JAILED test of the bus.sh `check` watermark fix. Touches nothing live: its own HOME, its own bus.
set -u
BUS=~/Documents/GitHub/claude-connect/bus/bus.sh
J="$(mktemp -d)"
export HOME="$J/home"
export BUS_PROJECTS_ROOT="$J/no-such-projects-root"   # so cwd is not under it
mkdir -p "$HOME/.claude/bus-state" "$J/proj"
BF="$J/bus.md"; export BUS_FILE="$BF"
cd "$J/proj" || exit 1                                  # TAG -> other:proj
echo "other:proj" > "$HOME/.claude/bus-state/active-tags"
SD="$HOME/.claude/bus-state"

mk() {  # ts sender body...
  printf '## %s [%s]\n%s\n\n' "$1" "$2" "$3" >> "$BF"
}
wm() { cat "$SD/other:proj.last-seen" 2>/dev/null || echo "(none)"; }
pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  OK  $1"; pass=$((pass+1)); else echo "  XX  $1 : got[$2] want[$3]"; fail=$((fail+1)); fi; }

# --- Scenario 1: nothing addressed to me -> nothing shown -> watermark MUST NOT advance ---
: > "$BF"
mk "2026-07-13 08:00" "other:alice" "to:other:bob — hello bob"
mk "2026-07-13 08:01" "other:alice" "to:other:carol — hi carol"
echo "2026-07-13 07:00" > "$SD/other:proj.last-seen"   # baseline before both
OUT="$(bash "$BUS" check 2>&1)"
ck "nothing-for-me: says no new"      "$(echo "$OUT" | grep -c 'No new messages')" "1"
ck "nothing-for-me: watermark UNCHANGED (the mcxn/91 core fix)" "$(wm)" "2026-07-13 07:00"

# --- Scenario 2: --all-tags still shows others' traffic AFTER a default check (mcxn fix) ---
: > "$BF"
mk "2026-07-13 08:00" "other:alice" "to:other:proj — FOR YOU (mine)"
mk "2026-07-13 08:05" "other:alice" "to:other:bob — for bob only (newer)"
echo "2026-07-13 07:00" > "$SD/other:proj.last-seen"
D="$(bash "$BUS" check 2>&1)"
ck "default check shows my msg"       "$(echo "$D" | grep -c 'FOR YOU')" "1"
ck "default check advanced to MINE (08:00), not file-newest (08:05)" "$(wm)" "2026-07-13 08:00"
A="$(bash "$BUS" check --all-tags 2>&1)"
ck "--all-tags STILL shows bob's newer msg (not buried)" "$(echo "$A" | grep -c 'for bob only')" "1"

# --- Scenario 3: large backlog -> pages oldest 20, N REMAIN, advances to 20th; 2nd check drains ---
: > "$BF"
for i in $(seq -w 1 25); do mk "2026-07-13 09:$i" "other:alice" "to:other:proj — msg $i"; done
echo "2026-07-13 08:00" > "$SD/other:proj.last-seen"
P1="$(bash "$BUS" check 2>&1)"
ck "large: shows 20 of 25, 5 REMAIN"  "$(echo "$P1" | grep -c '20 of 25 unread shown')" "1"
ck "large: showed msg 01 (oldest)"    "$(echo "$P1" | grep -c 'msg 01')" "1"
ck "large: did NOT show msg 25"       "$(echo "$P1" | grep -c 'msg 25')" "0"
ck "large: advanced to 20th (09:20)"  "$(wm)" "2026-07-13 09:20"
P2="$(bash "$BUS" check 2>&1)"
ck "2nd check drains the last 5"      "$(echo "$P2" | grep -c 'msg 25')" "1"
ck "2nd check advanced to newest (09:25)" "$(wm)" "2026-07-13 09:25"

# --- Scenario 4: small backlog -> shows all, no cap noise, advances to newest ---
: > "$BF"
mk "2026-07-13 10:00" "other:alice" "to:other:proj — a"
mk "2026-07-13 10:01" "other:alice" "to:other:proj — b"
echo "2026-07-13 09:59" > "$SD/other:proj.last-seen"
S="$(bash "$BUS" check 2>&1)"
ck "small: no REMAIN banner"          "$(echo "$S" | grep -c 'REMAIN')" "0"
ck "small: advanced to newest (10:01)" "$(wm)" "2026-07-13 10:01"

echo; echo "  === $pass passed, $fail failed ==="
rm -rf "$J"
[ "$fail" -eq 0 ]
