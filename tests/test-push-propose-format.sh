#!/usr/bin/env bash
# `push propose` silently deleted most of its input and reported success.
#
# docs, 2026-10-10, via Kyle: there was NO format spec or hint anywhere in the tool. The
# convention is short-form, `why:` is enforced, brevity is not — so a session carrying an old
# verbose template drifts with no signal. docs emitted a long multi-line block for ~a DOZEN
# pushes before Kyle caught it BY EYE.
#
# ⚠️ Reading the parser showed something docs did not report, and it is worse than the missing
# hint: ONLY lines beginning `why:` or `else:` are read, and every other line was DISCARDED
# SILENTLY while the tool printed "📤 Proposed a push". MEASURED before the fix — a body with
# two lines of real context stored `why=short reason` and dropped both, exit 0.
#
# That is the same shape as everything else in this arc: a tool reporting its INTENTION rather
# than its OUTCOME (cf. `send` printing "Sent" whether or not anything landed, v2.30).
#
# Warnings, never refusals: blocking a push over formatting is worse than a verbose proposal.
# Drives the REAL bus/bus.sh.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
P=0; F=0
ok(){ P=$((P+1)); echo "  ok   $1"; }
bad(){ F=$((F+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
mkdir -p "$T/.claude/bus-state"
GA=(-c user.name=t -c user.email=t@e -c commit.gpgsign=false -c init.defaultBranch=master)
# NOTE: built with clone, never `git push` — a push in this script is intercepted by the
# tool-layer gate before the test can run, and it files a phantom request as a side effect.
git "${GA[@]}" init -q "$T/a"
( cd "$T/a" && echo a > f && git "${GA[@]}" add f && git "${GA[@]}" commit -qm A )
git "${GA[@]}" clone -q "$T/a" "$T/b" 2>/dev/null
( cd "$T/b" && echo b >> f && git "${GA[@]}" commit -qam B )

PROPDIR="$T/.claude/bus-state/coord/push-proposals"
run(){ ( cd "$T/b" && HOME="$T" bash "$BUS" push propose - 2>&1 ); }
clean(){ rm -f "$PROPDIR"/* 2>/dev/null || true; }
stored(){ cat "$PROPDIR"/* 2>/dev/null; }

# 1. THE DEFECT: unmatched content lines are named, not swallowed
clean
out="$(run <<'EOF'
why: short reason
This whole line is important context I expect Kyle to read.
And so is this one.
else: keep digging
EOF
)"
echo "$out" | grep -q "2 line(s) were NOT included" && ok "names HOW MANY lines were dropped" \
  || bad "dropped lines are still silent"
echo "$out" | grep -q "dropped: This whole line" && ok "quotes the dropped text (so it can be recovered)" \
  || bad "does not show WHAT was dropped"
echo "$out" | grep -q "Kyle will NOT see those" && ok "states the consequence, not just the count" \
  || bad "no consequence stated"

# 2. ...and it is still FILED. A warning must not become a refusal.
stored | grep -q '^why=short reason$' && ok "warned, but the proposal still filed" \
  || bad "the warning turned into a refusal"

# 3. over-length why: warns, still files
clean
long="$(printf 'x%.0s' $(seq 1 260))"
out="$(run <<EOF
why: $long
EOF
)"
echo "$out" | grep -q "is 260 characters" && ok "over-long why: is measured and reported" \
  || bad "no brevity warning"
stored | grep -q '^why=' && ok "over-long why: still filed (warn, never refuse)" \
  || bad "brevity check refused the push"

# 4. ⚠️ A CLEAN PROPOSAL MUST STAY SILENT. A warning that fires on correct input is noise,
#    and noise is how a real signal gets discounted — this repo's own stated lesson.
clean
out="$(run <<'EOF'
why: tests pass
else: keep digging
EOF
)"
echo "$out" | grep -qE "were NOT included|characters" && bad "warned on a well-formed proposal" \
  || ok "well-formed proposal produces no warning"
echo "$out" | grep -q "Proposed a push" && ok "and still succeeds" || bad "clean proposal broke"

# 5. blank lines are formatting, not content — they must not be reported as dropped
clean
out="$(run <<'EOF'
why: tests pass

else: keep digging
EOF
)"
echo "$out" | grep -q "were NOT included" && bad "a blank line was reported as dropped content" \
  || ok "blank lines are not counted as dropped content"

# 6. the required-field check must still come FIRST
clean
out="$(run <<'EOF'
some prose with no why line at all
EOF
)" || true
echo "$out" | grep -q "needs a 'why:' line" && ok "a body with no why: is still refused" \
  || bad "the why: requirement regressed"

# 7. the usage text must state the format (docs' actual request: make it DISCOVERABLE)
u="$( cd "$T/b" && HOME="$T" bash "$BUS" push propose bogus-arg 2>&1 || true )"
echo "$u" | grep -q "only these two prefixes are read\|Only these two prefixes are read" \
  && ok "usage states that other lines are not read" || bad "usage does not state the format"

echo "── push-propose-format: $P passed, $F failed"
[ "$F" -eq 0 ]
