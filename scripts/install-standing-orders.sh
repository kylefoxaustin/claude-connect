#!/usr/bin/env bash
# install-standing-orders.sh — set Kyle's fleet standing orders in stone in the LIVE fleet.
#
# RUN FROM A PLAIN TERMINAL (not a Claude session): it writes ~/.claude/bin and
# ~/.claude/bus-state, which the persistence gate blocks from inside a session by design.
#
# Two parts: (1) install the law file so every session's SessionStart hook can read it;
# (2) splice the updated session-start case (which prepends the law) from the repo into the
# live bus.sh. The session-start hook is tag-agnostic, so the repo's version drops in verbatim.
# Idempotent, backs up, rolls back on a parse error.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LIVE="$HOME/.claude/bin/bus.sh"
SO_DST="$HOME/.claude/bus-state/standing-orders.md"

[ -f "$REPO/bus/standing-orders.md" ] || { echo "missing $REPO/bus/standing-orders.md"; exit 1; }
[ -f "$LIVE" ] || { echo "no live bus.sh at $LIVE"; exit 1; }

echo "1. installing the law file -> $SO_DST"
install -Dm644 "$REPO/bus/standing-orders.md" "$SO_DST"

if grep -q 'FLEET STANDING ORDERS' "$LIVE"; then
  echo "= live bus.sh session-start already injects the standing orders — file refreshed, done."
  exit 0
fi

BK="$LIVE.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$LIVE" "$BK"
echo "2. backed up live -> $BK"

python3 - "$REPO/bus/bus.sh" "$LIVE" <<'PY'
import sys
src_path, live_path = sys.argv[1], sys.argv[2]

def extract_case(lines, label):
    """Return (start, end_exclusive) of a `  <label>)` ... `    ;;` case block."""
    start = next(i for i, l in enumerate(lines) if l.rstrip() == f"  {label})")
    # the case ends at the `    ;;` that precedes the NEXT top-level case (two-space indent + `)`)
    nxt = next(i for i in range(start + 1, len(lines))
               if l_is_case_label(lines[i]) and lines[i].rstrip() != f"  {label})")
    j = nxt - 1
    while lines[j].strip() == "":
        j -= 1
    assert lines[j].strip() == ";;", f"expected ;; before next case, got {lines[j]!r}"
    return start, j + 1

def l_is_case_label(l):
    import re
    return bool(re.match(r"^  [a-z][a-z0-9-]*\)\s*$", l))

src  = open(src_path).read().splitlines(keepends=True)
live = open(live_path).read().splitlines(keepends=True)

s0, s1 = extract_case(src, "session-start")
l0, l1 = extract_case(live, "session-start")
new_block = src[s0:s1]

live[l0:l1] = new_block
open(live_path, "w").write("".join(live))
print("   spliced the updated session-start case into live bus.sh")
PY

echo "3. syntax-checking"
if bash -n "$LIVE"; then
  echo "   OK — the standing orders now lead every session's context. Restart nothing; the"
  echo "   next SessionStart (a new session, or the next relaunch) reads them."
else
  echo "   PARSE ERROR — rolling back to $BK"
  cp -p "$BK" "$LIVE"
  exit 1
fi
