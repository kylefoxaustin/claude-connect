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

# NOTE: this REPLACES an already-installed catchup case as well as inserting a new one, so it can
# ship an UPDATE (e.g. the newest-first / --thread-order revision), not just a first install.
if grep -q '^  catchup)' "$LIVE"; then
  echo "= live bus.sh already has 'catchup' — it will be REPLACED with the repo version (an update)."
fi

BK="$LIVE.bak-$(date +%Y%m%d-%H%M%S)"
cp -p "$LIVE" "$BK"
echo "1. backed up live -> $BK"

python3 - "$SRC" "$LIVE" <<'PY'
import re, sys

src_path, live_path = sys.argv[1], sys.argv[2]
src  = open(src_path).read().splitlines(keepends=True)
live = open(live_path).read().splitlines(keepends=True)

def case_bounds(lines, label, nextlabel):
    """(start, end_exclusive) of `  <label>)` … the `    ;;` that closes it, located as the last
    bare `;;` before `  <nextlabel>)`. The inner flag-parse `case` uses inline `... ;;`, never a
    bare `;;` line, so this finds the OUTER close, not an inner one."""
    start = next(i for i, l in enumerate(lines) if l.rstrip() == f"  {label})")
    end   = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == f"  {nextlabel})")
    j = end - 1
    while lines[j].strip() == "":
        j -= 1
    assert lines[j].strip() == ";;", f"expected ;; before {nextlabel}), got {lines[j]!r}"
    return start, j + 1

# Repo catchup case (the source of truth).
s0, s1 = case_bounds(src, "catchup", "all")
block  = src[s0:s1]

# Replace an existing catchup case, else insert before `  all)`.
if any(l.rstrip() == "  catchup)" for l in live):
    l0, l1 = case_bounds(live, "catchup", "all")
    live[l0:l1] = block + ["\n"]
    print("   replaced the existing catchup case")
else:
    ai = next(i for i, l in enumerate(live) if l.rstrip() == "  all)")
    live[ai:ai] = block + ["\n"]
    print("   inserted the catchup case")

text = "".join(live)

# Discoverability: refresh the `bus.sh catchup …` help line(s) in usage() from the repo, whatever
# they currently say. Best-effort — cosmetic, never fails the install.
help_lines = "".join(l for l in src if re.match(r"^  bus\.sh catchup\b", l))
if help_lines:
    text, n = re.subn(r"(?m)^  bus\.sh catchup\b.*(?:\n  bus\.sh catchup\b.*)*\n",
                      help_lines, text, count=1)
    print("   refreshed catchup help" if n else "   (no catchup help line found to refresh)")

open(live_path, "w").write(text)
PY

echo "2. syntax-checking the result"
if bash -n "$LIVE"; then
  echo "   OK — live bus.sh parses. 'bus.sh catchup' is now available."
else
  echo "   PARSE ERROR — rolling back to $BK"
  cp -p "$BK" "$LIVE"
  exit 1
fi
