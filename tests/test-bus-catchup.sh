#!/usr/bin/env bash
# Drives the REAL bus/bus.sh `catchup` command end-to-end.
#
# holobench (2026-07-14): a session returning from an absence had two bad exits — page ~28
# times through `check` (20 full bodies each), or advance the cursor without reading. catchup
# is the honest middle: a ONE-LINE DIGEST of every unread message, oldest-first (so advancing
# the cursor to the last line shown is always sound), bounded so it can't truncate-then-skip.
set -uo pipefail

BUSSH="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

# Each test runs in its own throwaway HOME so watermarks don't bleed between cases.
setup() {  # -> echoes the scratch dir; sets BUS/SD; cd's into a whitelisted project dir
  SB="$(mktemp -d)"; export HOME="$SB"
  SD="$SB/.claude/bus-state"; BUS="$SB/bus.md"
  mkdir -p "$SD" "$SB/proj/mytag"
  echo "other:mytag" > "$SD/active-tags"          # whitelist so the cursor may advance
  cd "$SB/proj/mytag"
}
run() { BUS_FILE="$BUS" bash "$BUSSH" catchup "$@" 2>&1; }
watermark() { cat "$SD/other:mytag.last-seen" 2>/dev/null; }

# ── selection + advance ──────────────────────────────────────────────────────
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
[ "$(watermark)" = "2026-07-14 09:07" ] && ok "advances cursor to newest shown" || bad "cursor wrong: $(watermark)"
[ "$(cat "$SD/other:mytag.pending" 2>/dev/null)" = "0" ] && ok "zeroes the pending counter" || bad "pending not zeroed"
# oldest-first ordering
[ "$(grep -n 'first unread\|directed to me\|urgent one' <<<"$out" | head -1 | grep -c 'first unread')" = 1 ] \
  && ok "oldest-first ordering" || bad "not oldest-first"
rm -rf "$SB"

# ── paging is resumable and the advance is SOUND (never past what was shown) ──
setup
: > "$BUS"
for i in $(seq -w 1 10); do
  printf '## 2026-07-14 10:%s [other:alice]\n\nto:all — [alice] msg %s\n\n' "$i" "$i" >> "$BUS"
done
echo "2026-07-14 10:00" > "$SD/other:mytag.last-seen"
o1="$(run -n 3)"
grep -q "3 of 10 unread digested" <<<"$o1" && ok "page 1 reports remaining" || bad "page1 footer"
[ "$(watermark)" = "2026-07-14 10:03" ] && ok "page 1 advances only to msg 3" || bad "page1 cursor: $(watermark)"
grep -q "msg 04" <<<"$o1" && bad "page1 leaked msg 4 (skip risk)" || ok "page 1 does not overshow"
run -n 3 >/dev/null                       # page 2
[ "$(watermark)" = "2026-07-14 10:06" ] && ok "page 2 advances to msg 6" || bad "page2 cursor: $(watermark)"
o3="$(run)"                               # page 3 (default cap clears the rest)
grep -q "caught up" <<<"$o3" && ok "final page reports caught up" || bad "no caught-up"
[ "$(watermark)" = "2026-07-14 10:10" ] && ok "cursor fully advanced" || bad "final cursor: $(watermark)"
grep -qi "Already current" <<<"$(run)" && ok "a second catchup is a no-op" || bad "not idempotent when current"
rm -rf "$SB"

# ── a non-whitelisted tag digests but must NOT advance (matches check's guard) ─
setup
rm -f "$SD/active-tags"                    # not whitelisted; BUS_WHITELIST empty
printf '## 2026-07-14 11:00 [other:alice]\n\nto:all — [alice] hi\n\n' > "$BUS"
echo "2026-07-14 10:00" > "$SD/other:mytag.last-seen"
BUS_WHITELIST="" out="$(BUS_FILE="$BUS" BUS_WHITELIST="" bash "$BUSSH" catchup 2>&1)"
grep -q "hi" <<<"$out" && ok "non-whitelisted still SEES the digest" || bad "no digest for non-wl"
[ "$(watermark)" = "2026-07-14 10:00" ] && ok "non-whitelisted does NOT advance" || bad "non-wl advanced: $(watermark)"
rm -rf "$SB"

echo "── catchup: $pass passed, $fail failed"
[ "$fail" = 0 ]
