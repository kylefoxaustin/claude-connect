#!/usr/bin/env bash
# ROTATION CATCH-UP (Kyle, 2026-07-22): when the bus rotates, unread messages between a
# reader's watermark and the new log's start move into a messages-YYYY-MM.md archive. A plain
# `check` reads only the current log and would ADVANCE the watermark PAST those archived
# messages without ever showing them — silent mail loss. `check` must detect the gap, show the
# unread archive messages, and be self-limiting (no re-dump on the next check). Drives the REAL
# bus/bus.sh.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export HOME="$SB/home"
mkdir -p "$HOME/.claude/bus-state" "$HOME/Documents/GitHub/testproj"
export BUS_PROJECTS_ROOT="$HOME/Documents/GitHub"
BUSDIR="$SB/bus"; mkdir -p "$BUSDIR"
export BUS_FILE="$BUSDIR/messages.md"

echo "other:testproj" > "$HOME/.claude/bus-state/active-tags"          # whitelist → watermark advances
printf '2026-07-20 15:00\n' > "$HOME/.claude/bus-state/other:testproj.last-seen"

# Archive: two UNREAD (after 15:00) + one already-read (before 15:00). Out of file order on purpose.
cat > "$BUSDIR/messages-2026-07.md" <<'EOF'
# archive
## 2026-07-20 16:00 [other:alice]

to:all — [alice] pre-rotation broadcast ALPHA

## 2026-07-20 17:00 [other:bob]

to:testproj — [bob] pre-rotation DIRECTED BETA

## 2026-07-20 14:00 [other:carol]

to:testproj — [carol] ALREADYREAD before the watermark
EOF

# Current log (post-rotation): the [system] notice + a fresh directed message.
cat > "$BUS_FILE" <<'EOF'
# Claude Bus

## 2026-07-21 21:07 [system]

Bus rotated. Previous log archived to `messages-2026-07.md`.

## 2026-07-22 05:00 [other:dave]

to:testproj — [dave] post-rotation GAMMA
EOF

run_check() { ( cd "$HOME/Documents/GitHub/testproj" && bash "$BUS" check ) 2>/dev/null; }

OUT="$(run_check)"
grep -q 'ALPHA'  <<<"$OUT" && ok "archive broadcast ALPHA recovered" || bad "ALPHA missing (mail lost!)"
grep -q 'BETA'   <<<"$OUT" && ok "archive directed BETA recovered"   || bad "BETA missing (mail lost!)"
grep -q 'GAMMA'  <<<"$OUT" && ok "current-log GAMMA shown"           || bad "GAMMA missing"
grep -q 'Bus rotated' <<<"$OUT" && ok "system rotation notice shown" || bad "system notice missing"
grep -q 'ALREADYREAD' <<<"$OUT" && bad "showed an already-read archive msg" || ok "already-read archive msg NOT reshown"
grep -qi 'before the last bus rotation' <<<"$OUT" && ok "catch-up notice printed" || bad "no catch-up notice"

WM="$(cat "$HOME/.claude/bus-state/other:testproj.last-seen")"
[ "$WM" = "2026-07-22 05:00" ] && ok "watermark advanced to newest shown (05:00)" || bad "watermark wrong: '$WM'"

# Self-limiting: a second check must NOT re-dump the archive.
OUT2="$(run_check)"
grep -q 'No new messages' <<<"$OUT2" && ok "re-check: nothing new" || bad "re-check produced output: $OUT2"
grep -q 'ALPHA' <<<"$OUT2" && bad "archive RE-DUMPED on 2nd check" || ok "archive not re-dumped (self-limiting)"

# No gap (watermark within the current log) must NOT read the archive at all.
printf '2026-07-21 21:07\n' > "$HOME/.claude/bus-state/other:testproj.last-seen"
OUT3="$(run_check)"
grep -q 'GAMMA' <<<"$OUT3" && ok "no-gap: current message still shown" || bad "no-gap: GAMMA missing"
grep -q 'ALPHA' <<<"$OUT3" && bad "no-gap: read the archive needlessly" || ok "no-gap: archive left alone"

# A brand-new reader (no watermark) must not trigger archive reads either.
rm -f "$HOME/.claude/bus-state/other:testproj.last-seen"
OUT4="$(run_check)"
grep -q 'ALPHA' <<<"$OUT4" && bad "new reader: dumped the archive" || ok "new reader: no archive dump"

# catchup (the "returning after absence" path) must cross the rotation too.
printf '2026-07-20 15:00\n' > "$HOME/.claude/bus-state/other:testproj.last-seen"
OUT5="$( ( cd "$HOME/Documents/GitHub/testproj" && bash "$BUS" catchup ) 2>/dev/null )"
grep -q '16:00' <<<"$OUT5" && ok "catchup: archive 16:00 recovered" || bad "catchup: 16:00 missing"
grep -q '17:00' <<<"$OUT5" && ok "catchup: archive 17:00 recovered" || bad "catchup: 17:00 missing"
grep -q '14:00' <<<"$OUT5" && bad "catchup: showed already-read 14:00" || ok "catchup: already-read not shown"

echo "── bus-rotation-catchup: $pass passed, $fail failed"
[ "$fail" = 0 ]
