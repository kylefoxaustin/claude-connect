#!/usr/bin/env bash
# Drives the REAL bus/bus.sh `catchup` command end-to-end.
#
# holobench (2026-07-14/15): a session returning from an absence had two bad exits — page ~28
# times through `check` (20 full bodies each), or advance the cursor without reading. catchup is
# the honest middle: a ONE-LINE DIGEST of every unread message. Ordering is holobench's decision
# (2026-07-15): NEWEST-first by DEFAULT, because a digest is for TRIAGE (reach the live state first,
# drill DOWN into full threads), not comprehension; `--thread-order` gives the oldest-first replay.
# One-liners are tiny, so catchup digests EVERY unread in one call and gets fully current. A
# pathological backlog past the cap is DISCLOSED (oldest undisplayed), never a silent skip.
set -uo pipefail

BUSSH="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

# Each test runs in its own throwaway HOME so watermarks don't bleed between cases.
setup() {  # sets BUS/SD; cd's into a whitelisted project dir
  SB="$(mktemp -d)"; export HOME="$SB"
  SD="$SB/.claude/bus-state"; BUS="$SB/bus.md"
  mkdir -p "$SD" "$SB/proj/mytag"
  echo "other:mytag" > "$SD/active-tags"          # whitelist so the cursor may advance
  cd "$SB/proj/mytag"
}
run() { BUS_FILE="$BUS" bash "$BUSSH" catchup "$@" 2>&1; }
watermark() { cat "$SD/other:mytag.last-seen" 2>/dev/null; }

# ── selection, NEWEST-first ordering, full advance ───────────────────────────
setup
cat > "$BUS" <<'EOF'
## 2026-07-14 09:00 [other:alice]

to:all — [alice] old already-read

## 2026-07-14 09:03 [other:alice]

to:all — [alice] first unread broadcast

## 2026-07-14 09:04 [other:bob]

to:mytag — [bob] directed to me

## 2026-07-14 09:05 [other:mytag]

to:all — [mytag] my own post

## 2026-07-14 09:06 [other:carol]

to:dave to:eve — [carol] to others only

## 2026-07-14 09:07 [other:dave]

to:mytag to:all p:wake — [dave] urgent one
EOF
echo "2026-07-14 09:02" > "$SD/other:mytag.last-seen"
out="$(run)"
grep -q "first unread broadcast" <<<"$out" && ok "shows an unread broadcast" || bad "missing broadcast"
grep -q "directed to me"         <<<"$out" && ok "shows a message directed to me" || bad "missing directed"
grep -q "my own post"            <<<"$out" && bad "showed my OWN post" || ok "excludes my own post"
grep -q "to others only"         <<<"$out" && bad "showed others-only mail" || ok "excludes others-only"
grep -q "🔔"                      <<<"$out" && ok "flags a p:wake with a bell" || bad "no p:wake bell"
[ "$(watermark)" = "2026-07-14 09:07" ] && ok "advances cursor to the newest unread" || bad "cursor wrong: $(watermark)"
[ "$(cat "$SD/other:mytag.pending" 2>/dev/null)" = "0" ] && ok "zeroes the pending counter" || bad "pending not zeroed"
# NEWEST-first: the 09:07 "urgent one" must be the FIRST digest line, "first unread" (09:03) the last
first_line="$(grep -E 'urgent one|first unread broadcast' <<<"$out" | head -1)"
grep -q "urgent one" <<<"$first_line" && ok "NEWEST-first ordering (latest at top)" || bad "not newest-first: $first_line"
grep -qi "newest-first" <<<"$out" && ok "banner/footer say newest-first" || bad "no newest-first label"
rm -rf "$SB"

# ── --thread-order flips to OLDEST-first, but still advances fully ────────────
setup
cat > "$BUS" <<'EOF'
## 2026-07-14 09:03 [other:alice]

to:all — [alice] first unread broadcast

## 2026-07-14 09:07 [other:dave]

to:all — [dave] latest one
EOF
echo "2026-07-14 09:00" > "$SD/other:mytag.last-seen"
out="$(run --thread-order)"
first_line="$(grep -E 'first unread broadcast|latest one' <<<"$out" | head -1)"
grep -q "first unread broadcast" <<<"$first_line" && ok "--thread-order: OLDEST-first (earliest at top)" || bad "thread-order not oldest-first: $first_line"
grep -qi "oldest-first" <<<"$out" && ok "--thread-order banner says oldest-first" || bad "no oldest-first label"
[ "$(watermark)" = "2026-07-14 09:07" ] && ok "--thread-order still advances fully" || bad "thread-order cursor: $(watermark)"
rm -rf "$SB"

# ── digest-ALL in one call: a big backlog under the default cap fully clears ──
setup
: > "$BUS"
for i in $(seq -w 1 30); do
  printf '## 2026-07-14 10:%s [other:alice]\n\nto:all — [alice] msg %s\n\n' "$i" "$i" >> "$BUS"
done
echo "2026-07-14 10:00" > "$SD/other:mytag.last-seen"
out="$(run)"
grep -q "caught up: 30 message" <<<"$out" && ok "digests all 30 in ONE call (no paging)" || bad "did not digest all: $(grep -o 'caught up[^-]*' <<<"$out")"
[ "$(watermark)" = "2026-07-14 10:30" ] && ok "cursor fully advanced to newest" || bad "cursor: $(watermark)"
grep -qi "Already current" <<<"$(run)" && ok "a second catchup is a no-op" || bad "not idempotent when current"
rm -rf "$SB"

# ── the cap is a DISCLOSED omission (oldest undisplayed), NOT a silent skip ───
setup
: > "$BUS"
for i in $(seq -w 1 10); do
  printf '## 2026-07-14 10:%s [other:alice]\n\nto:all — [alice] msg %s\n\n' "$i" "$i" >> "$BUS"
done
echo "2026-07-14 10:00" > "$SD/other:mytag.last-seen"
out="$(run -n 3)"
grep -q "msg 10" <<<"$out" && ok "cap shows the NEWEST (msg 10)" || bad "cap didn't show newest"
grep -q "msg 01" <<<"$out" && bad "cap showed the oldest (should be omitted)" || ok "cap omits the oldest"
grep -q "7 OLDER marked read without display" <<<"$out" && ok "DISCLOSES the omission" || bad "silent omission: $out"
[ "$(watermark)" = "2026-07-14 10:10" ] && ok "cap STILL advances fully (one call = current)" || bad "cap cursor: $(watermark)"
grep -qi "Already current" <<<"$(run)" && ok "follow-up is current (omission disclosed, not lost)" || bad "not current after cap"
rm -rf "$SB"

# ── a non-whitelisted tag digests but must NOT advance (matches check's guard) ─
setup
rm -f "$SD/active-tags"
printf '## 2026-07-14 11:00 [other:alice]\n\nto:all — [alice] hi\n\n' > "$BUS"
echo "2026-07-14 10:00" > "$SD/other:mytag.last-seen"
out="$(BUS_FILE="$BUS" BUS_WHITELIST="" bash "$BUSSH" catchup 2>&1)"
grep -q "hi" <<<"$out" && ok "non-whitelisted still SEES the digest" || bad "no digest for non-wl"
[ "$(watermark)" = "2026-07-14 10:00" ] && ok "non-whitelisted does NOT advance" || bad "non-wl advanced: $(watermark)"
rm -rf "$SB"

# ── empty: nothing unread ────────────────────────────────────────────────────
setup
printf '## 2026-07-14 09:00 [other:alice]\n\nto:all — [alice] read already\n\n' > "$BUS"
echo "2026-07-14 09:00" > "$SD/other:mytag.last-seen"
grep -qi "Already current" <<<"$(run)" && ok "nothing unread -> Already current" || bad "empty case wrong"
rm -rf "$SB"

echo "── catchup: $pass passed, $fail failed"
[ "$fail" = 0 ]
