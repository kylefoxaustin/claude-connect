#!/usr/bin/env bash
# Fleet-health alert dismissal (Kyle, 2026-10-06: "i don't think the dismiss x actually
# works to get rid of a msg").
#
# It worked, and it persisted. The KEY was the problem: `stale:<tag>:<unread_count>`.
# Dismissing "these 20" stored a key that ONE further message invalidated, so on a fleet
# with live senders the row returned within seconds and the button read as broken.
#
# The original intent was sound -- never silently mute a condition that is getting worse
# -- and only the threshold was wrong: a 21st message is a new fact but not a new
# DECISION. The rule is now identity-keyed with a MATERIAL-change test: the row returns
# when the count doubles, or after a week.
#
# ⚠️ The function under test is EXTRACTED FROM app.js, never re-typed here. A copy of the
# logic would pass while the shipped code did anything at all -- that is a mirror, not a
# test, and this repo has been burned by one before.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/frontend/app.js"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }

command -v node >/dev/null 2>&1 || { echo "  SKIP: node not installed"; exit 0; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
node -e '
const fs = require("fs");
const src = fs.readFileSync(process.argv[1], "utf8");
// pull the real constant + function out of the shipped bundle
const c = src.match(/const ALERT_REDISPLAY_MS = [^;]+;/);
const f = src.match(/function alertIsDismissed\(d, key, n\) \{[\s\S]*?\n\}/);
if (!c || !f) { console.error("EXTRACT_FAILED"); process.exit(3); }
fs.writeFileSync(process.argv[2], c[0] + "\n" + f[0] + "\nmodule.exports={alertIsDismissed};\n");
' "$APP" "$T/mod.js" 2>"$T/err" || { no "could not extract alertIsDismissed from app.js (renamed?)"; cat "$T/err"; echo; printf '  %d passed, %d failed\n' "$PASS" "$((FAIL))"; exit 1; }
ok "extracted alertIsDismissed from the shipped app.js"

run(){ node -e '
const {alertIsDismissed} = require(process.argv[1]);
const now = Date.now();
const DAY = 24*3600*1000;
let bad = 0;
const t = (label, got, want) => {
  if (got !== want) { console.log("  FAIL " + label + " (got " + got + ")"); bad++; }
  else console.log("  ok   " + label);
};
const d = { "stale:campmatch": { at: now, n: 20 } };
t("same count stays dismissed",              alertIsDismissed(d,"stale:campmatch",20), true);
t("ONE more message stays dismissed (the bug)", alertIsDismissed(d,"stale:campmatch",21), true);
t("a 25% rise stays dismissed",              alertIsDismissed(d,"stale:campmatch",25), true);
t("DOUBLING brings it back",                 alertIsDismissed(d,"stale:campmatch",40), false);
t("far worse brings it back",                alertIsDismissed(d,"stale:campmatch",100), false);
t("a tag never dismissed is shown",          alertIsDismissed(d,"stale:other",5), false);
t("dismissal expires after a week",          alertIsDismissed({"s":{at:now-8*DAY,n:20}},"s",20), false);
t("six days old is still dismissed",         alertIsDismissed({"s":{at:now-6*DAY,n:20}},"s",20), true);
// the identity key must carry NO magnitude, or none of the above can ever match
t("zero-count record never divides by zero", alertIsDismissed({"s":{at:now,n:0}},"s",99), true);
process.exit(bad ? 1 : 0);
' "$1"; }

if out="$(run "$T/mod.js")"; then
  echo "$out" | sed 's/^/  /' | sed 's/^  ok/  ok/'
  PASS=$((PASS+9))
else
  echo "$out" | sed 's/^/  /'
  FAIL=$((FAIL+1))
fi

# The whole point is that the SHIPPED key is identity-only. If a magnitude ever creeps
# back into it, every assertion above becomes vacuous while still passing.
if grep -qE 'withDismiss\(row, `stale:\$\{c\.tag\}`' "$APP"; then
  ok "stale key is identity-only in the shipped code"
else
  no "the stale dismiss key carries a magnitude again — dismissal will stop sticking"
fi

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
