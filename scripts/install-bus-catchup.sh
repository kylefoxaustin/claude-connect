#!/usr/bin/env bash
# install-bus-catchup.sh — splice the tested `catchup` command into the LIVE ~/.claude/bin/bus.sh.
#
# RUN FROM A PLAIN TERMINAL (not a Claude session): it writes ~/.claude/bin, which the
# persistence gate blocks from inside a session by design (docs/PERSISTENCE_GATE.md).
#
# The live bus.sh and the repo copy differ (real vs sanitized tags), so this SPLICES rather
# than copies: it lifts the `catchup)` case verbatim from the repo (the tested source of truth)
# and inserts it, plus two one-line discoverability edits. Idempotent, backs up first, and
# rolls back if the result doesn't parse.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$REPO/bus/bus.sh"
LIVE="$HOME/.claude/bin/bus.sh"

[ -f "$SRC" ]  || { echo "missing repo copy: $SRC"; exit 1; }
[ -f "$LIVE" ] || { echo "no live bus.sh at $LIVE"; exit 1; }

if grep -q '^  catchup)' "$LIVE"; then
  echo "= live bus.sh already has 'catchup' — nothing to do."
  exit 0
fi

BK="$LIVE.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$LIVE" "$BK"
echo "1. backed up live -> $BK"

python3 - "$SRC" "$LIVE" <<'PY'
import re, sys

src_path, live_path = sys.argv[1], sys.argv[2]
src  = open(src_path).read().splitlines(keepends=True)
live = open(live_path).read()

# 1) Extract the `catchup)` case block from the repo copy: from the line `  catchup)` up to and
#    including the `    ;;` that immediately precedes the `  all)` case.
start = next(i for i, l in enumerate(src) if l.rstrip() == "  catchup)")
end = next(i for i in range(start + 1, len(src)) if src[i].rstrip() == "  all)")
# back up over blank lines to the `    ;;` that closes catchup
j = end - 1
while src[j].strip() == "":
    j -= 1
assert src[j].strip() == ";;", f"expected ;; before all), got {src[j]!r}"
block = "".join(src[start:j + 1]) + "\n"

# 2) Insert the block before the live `  all)` case.
assert "\n  all)\n" in live, "live bus.sh has no `all)` case anchor"
live = live.replace("\n  all)\n", "\n" + block + "  all)\n", 1)

# 3) Discoverability: point the check paging footer at catchup.
old_footer = ('    print("--- %d of %d unread shown (oldest first) · %d REMAIN — run `check` again. ---"\n'
              '          % (len(sel), total_unread, remaining))')
new_footer = ('    print("--- %d of %d unread shown (oldest first) · %d REMAIN — run `check` again, "\n'
              '          "or `bus.sh catchup` to digest them all at once. ---"\n'
              '          % (len(sel), total_unread, remaining))')
if old_footer in live:
    live = live.replace(old_footer, new_footer, 1)

# 4) Help text.
old_help = "  bus.sh check               Print the last 80 lines (used by /msg-check)\n"
new_help = ("  bus.sh check               New messages addressed to you since last check\n"
            "  bus.sh catchup [-n N]      Digest ALL unread at once (oldest-first) & get current\n")
if old_help in live:
    live = live.replace(old_help, new_help, 1)

open(live_path, "w").write(live)
print("   spliced catchup case + footer + help")
PY

echo "2. syntax-checking the result"
if bash -n "$LIVE"; then
  echo "   OK — live bus.sh parses. 'bus.sh catchup' is now available."
else
  echo "   PARSE ERROR — rolling back to $BK"
  cp -p "$BK" "$LIVE"
  exit 1
fi
