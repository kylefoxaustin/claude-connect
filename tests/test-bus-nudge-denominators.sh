#!/usr/bin/env bash
# The per-prompt nudge counts FLEET TRAFFIC. It was worded as if it counted YOUR MAIL.
#
# `lostchild` reconciled it arithmetically on its own cursor (2026-08-24): 10 messages after its
# watermark, minus 1 of its own posts, = 9 — exactly what the badge claimed — and **zero of the 9
# were addressed to it**. Two different quantities, so the badge and `check` disagreeing was never
# evidence of a broken cursor, and a whole branch of a cursor investigation went down that hole.
#
# Its wording note was worth more than its diagnosis: say BOTH numbers, so "20 new, none for you"
# is a glance instead of a `bus.sh check`. This session spent the night reading "2 pending from
# [resource-watchdog]" (neither for it) and then "20 pending" (one for it) and could not tell the
# difference from the nudge alone — Kyle had to say "check messages" twice.
#
# So the counter now reads each new message's ADDRESS LINE, not just its header, and reports the
# directed count first. Header-only was the reason it could not tell the difference.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
SD="$SB/home/.claude/bus-state"
mkdir -p "$SD" "$SB/claude-connect"
printf 'other:claude-connect\n' > "$SD/active-tags"

cat > "$SB/messages.md" <<'LOG'
## 2026-08-24 10:00:00 [other:holobench]

to:95emulator — not for me at all.

## 2026-08-24 11:00:00 [other:lostchild]

to:claude-connect to:jaws — directed at me by plain name.

## 2026-08-24 12:00:00 [other:qualcomm]

to:all — a broadcast, which does reach me.

## 2026-08-24 13:00:00 [resource-watchdog]

to:other:qualcomm — someone else's lease nudge.
LOG

nudge() {
  (cd "$SB/claude-connect" && env HOME="$SB/home" BUS_STATE_DIR="$SD" BUS_FILE="$SB/messages.md" \
      bash "$BUS" prompt-check 2>/dev/null </dev/null)
}

# 1. Both numbers, and the one that decides whether to interrupt yourself comes first.
printf '2026-08-24 09:00:00\n' > "$SD/other:claude-connect.last-seen"
out="$(nudge)"
case "$out" in
  *"2 message(s) ADDRESSED TO YOU"*) ok "leads with the directed count (2 of 4)" ;;
  *"4 pending message(s)"*)          bad "still reports fleet traffic as if it were your mail" ;;
  *)                                 bad "unrecognised nudge: $(printf '%s' "$out" | head -c 140)" ;;
esac
case "$out" in
  *"4 new on the bus in total"*) ok "and still reports the fleet total, in second place" ;;
  *)                             bad "the fleet total disappeared — that number is also real" ;;
esac
# The senders named must be the ones who wrote TO ME, not everyone on the bus.
case "$out" in
  *lostchild*qualcomm*) ok "names the senders who addressed me" ;;
  *)                    bad "directed senders not named" ;;
esac
case "$out" in
  *holobench*) bad "named a sender whose message was for someone else" ;;
  *)           ok "does not name senders who wrote to others" ;;
esac

# 2. THE CASE THAT SAVES THE MOST TIME: traffic exists, none of it is yours.
printf '2026-08-24 12:30:00\n' > "$SD/other:claude-connect.last-seen"
out2="$(nudge)"
case "$out2" in
  *"NONE addressed to you"*) ok "says so explicitly when nothing is for you" ;;
  *)                         bad "cannot tell 'nothing for you' from 'mail waiting': $(printf '%s' "$out2" | head -c 120)" ;;
esac
case "$out2" in
  *"Nothing needs you"*) ok "and says the fleet traffic does not need you" ;;
  *)                     bad "no reassurance line" ;;
esac

# 3. Controls. Silence must stay silence, and a broadcast must still count as reaching you.
printf '2026-08-24 23:00:00\n' > "$SD/other:claude-connect.last-seen"
[ -z "$(nudge)" ] && ok "cursor past everything: silent" || bad "nudged with nothing new"

cat > "$SB/messages.md" <<'LOG'
## 2026-08-24 12:00:00 [other:qualcomm]

to:all — a broadcast and nothing else.
LOG
printf '2026-08-24 09:00:00\n' > "$SD/other:claude-connect.last-seen"
case "$(nudge)" in
  *"1 message(s) ADDRESSED TO YOU"*) ok "a to:all broadcast counts as reaching you" ;;
  *)                                 bad "a broadcast was not counted as addressed to me" ;;
esac

echo "── bus-nudge-denominators: $pass passed, $fail failed"
[ "$fail" = 0 ]
