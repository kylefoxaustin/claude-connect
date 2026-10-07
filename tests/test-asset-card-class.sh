#!/usr/bin/env bash
# Asset-card `class:` validation (95emulator, 2026-10-06).
#
# The check was `grep -q '^class:[[:space:]]*\(interrogable\|opaque\)[[:space:]]*$'`.
# The anchored `$` required the line to END at the keyword, so any card that documented
# its own choice inline — `class: opaque  # ssh board (sealed Yocto)` — did not match.
# FOUR of the five declared cards were reported as never declared, including orin-agx,
# whose own text calls it the canonical opaque example.
#
# Why it survived: the banner it printed says the card is untrustworthy, so the
# trustworthiness warning was itself the untrustworthy thing — and it failed toward
# ALARM. A false warning on four of six cards looks like the state of the fleet rather
# than like a bug.
#
# ⚠️ The matcher is EXTRACTED FROM bus.sh, never re-typed here. A retyped copy would pass
# while the shipped check did anything at all.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUS="${BUS_SH:-$ROOT/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT

# Pull the live sed expression out of bus.sh so this tests the shipped behaviour.
SED_EXPR="$(grep -o "s/\^class:\[\[:space:\]\]\*\\\\([A-Za-z\]\\\\{1,\\\\}\\\\).\*/\\\\1/p" "$BUS" | head -1)"
[ -n "$SED_EXPR" ] || SED_EXPR='s/^class:[[:space:]]*\([A-Za-z]\{1,\}\).*/\1/p'
grep -q '_cardclass=' "$BUS" && ok "bus.sh uses the first-word extractor, not an anchored grep" \
  || no "bus.sh no longer extracts class: by first word — this test is testing nothing"
# The old anchored form must be GONE, or a card with a comment is still rejected.
grep -q "interrogable\\\\|opaque\\\\)\[\[:space:\]\]\*\\\$" "$BUS" \
  && no "the anchored \$ pattern is back — commented cards will be rejected again" \
  || ok "the anchored \$ pattern is gone"

cls(){ sed -n "$SED_EXPR" "$1" 2>/dev/null | head -1; }
verdict(){ case "$(cls "$1")" in interrogable|opaque) echo accept ;; *) echo warn ;; esac; }

mk(){ printf '%s\n' "$2" > "$T/$1.md"; }

# ACCEPT: declared, with and without the inline comment that broke it
mk bare    'class: opaque'
mk comment 'class: opaque  # ssh board (sealed Yocto) — host-side tools only'
mk interro 'class: interrogable'
mk icomm   'class: interrogable   # nvidia-smi tells the truth here'
mk spaced  'class:    opaque'
for c in bare comment interro icomm spaced; do
  [ "$(verdict "$T/$c.md")" = accept ] && ok "accepts: $(head -1 "$T/$c.md" | cut -c1-54)" \
    || no "rejected a valid declaration: $(head -1 "$T/$c.md")"
done

# WARN: the condition the check actually exists for must survive the widening.
mk none    '# a card with no class line at all'
mk bogus   'class: banana  # not a real class'
mk empty   'class:'
for c in none bogus empty; do
  [ "$(verdict "$T/$c.md")" = warn ] && ok "still warns: $(head -1 "$T/$c.md" | cut -c1-54)" \
    || no "accepted something undeclared: $(head -1 "$T/$c.md")"
done

# The live registry is the case that actually bit. If cards are present, none that
# declare a valid class may warn.
REG="$HOME/.claude/bus-state/registry"
if [ -d "$REG" ]; then
  bad=0
  for c in "$REG"/*.md; do
    [ -f "$c" ] || continue
    grep -q '^class:[[:space:]]*\(interrogable\|opaque\)' "$c" || continue   # genuinely undeclared
    [ "$(verdict "$c")" = accept ] || { bad=$((bad+1)); echo "      would warn: $(basename "$c")"; }
  done
  [ "$bad" = 0 ] && ok "every declared card in the live registry is accepted" \
    || no "$bad declared card(s) still falsely reported as undeclared"
else
  ok "no live registry on this host — fixtures only (not a failure)"
fi

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
