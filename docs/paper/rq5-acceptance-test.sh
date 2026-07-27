#!/usr/bin/env bash
# RQ5 acceptance test — BLACK BOX. Grades an arm's implementation of
#   bus.sh project pause <id> / resume <id>
# Usage:  rq5-acceptance-test.sh /path/to/that-arm/bus/bus.sh
# PASS iff this script exits 0. It tests BEHAVIOR only (status reflects pause,
# dispatch respects it) — never how the paused flag is stored. Runs fully jailed
# in a scratch $HOME, so it cannot touch live fleet state.
set -u
BUS="${1:?usage: rq5-acceptance-test.sh <path-to-the-arm bus.sh>}"
[ -f "$BUS" ] || { echo "no bus.sh at $BUS"; exit 3; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
SD="$HOME/.claude/bus-state"; mkdir -p "$SD/coord" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"
export PROJECT_STATE_DIR="$SD/coord/projects"
export ORDER_STATE_DIR="$SD/coord/orders"
DROP="$HOME/drop"; mkdir -p "$DROP"
LEAD="$HOME/w/lead"; OPS="$HOME/w/ops"; mkdir -p "$LEAD" "$OPS"
lead(){ (cd "$LEAD" && bash "$BUS" project "$@" 2>&1); }
ops(){  (cd "$OPS"  && bash "$BUS" project "$@" 2>&1); }
# raw runs that preserve the exit code (for refusal checks)
lead_rc(){ (cd "$LEAD" && bash "$BUS" project "$@" >/dev/null 2>&1); }
jfield(){ python3 -c "import json;p=json.load(open('$PROJECT_STATE_DIR/$1.json'));j=[x for x in p['jobs'] if x['id']=='$2'];print(j[0].get('state','') if j else '')" 2>/dev/null; }

pass=0 fail=0
okc(){ if printf '%s' "$2" | grep -qiF "$3"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — missing [$3] in: $2"; fi; }
nog(){ if printf '%s' "$2" | grep -qiF "$3"; then fail=$((fail+1)); echo "FAIL: $1 — UNEXPECTED [$3] in: $2"; else pass=$((pass+1)); fi; }
ok(){  if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }
rc_nonzero(){ if [ "$2" -ne 0 ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected non-zero exit"; fi; }
rc_zero(){    if [ "$2" -eq 0 ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected zero exit"; fi; }

# ---- setup: drive a project to active with one ready (no-dep) job -------------
ops  new proj 'rq5 pause/resume test'            >/dev/null
ops  nominate proj lead                          >/dev/null
lead accept proj                                 >/dev/null
printf 'A do the thing -> lead\n' | lead plan proj >/dev/null
ops  approve proj                                >/dev/null
lead job add proj jobA to:lead path:$DROP files:a.md -- do the thing >/dev/null
# sanity: the project reached active with a dispatchable job (setup, not the feature)
okc "setup: jobA exists" "$(ops jobs proj)" "jobA"

# ---- 1. pause ---------------------------------------------------------------
lead pause proj; rc=$?; rc_zero "pause exits 0" "$rc"
okc "status shows paused" "$(ops status proj)" "paus"

# ---- 2. dispatch is REFUSED while paused ------------------------------------
out="$(lead dispatch proj jobA)"; lead_rc dispatch proj jobA; rc=$?
rc_nonzero "dispatch refused (non-zero) while paused" "$rc"
okc "refusal names the pause" "$out" "paus"
nog "refusal did not claim dispatched" "$out" "dispatched"
ok  "jobA NOT dispatched while paused" "$(jfield proj jobA)" "planned"
[ -f "$ORDER_STATE_DIR/proj-proj__jobA.json" ] && { echo "FAIL: an order was placed while paused"; fail=$((fail+1)); } || pass=$((pass+1))

# ---- 3. idempotent pause + bad id -------------------------------------------
lead pause proj; rc_zero "pause is idempotent" "$?"
lead_rc pause nonesuch; rc_nonzero "pause of unknown id fails" "$?"
lead_rc resume nonesuch; rc_nonzero "resume of unknown id fails" "$?"

# ---- 4. resume restores dispatch --------------------------------------------
lead resume proj; rc_zero "resume exits 0" "$?"
lead resume proj; rc_zero "resume is idempotent" "$?"
nog "status no longer shows paused" "$(ops status proj)" "paused"
out="$(lead dispatch proj jobA)"
okc "dispatch works after resume" "$out" "dispatched"
ok  "jobA dispatched after resume" "$(jfield proj jobA)" "dispatched"

# ---- verdict ----------------------------------------------------------------
echo "---------------------------------------------"
echo "PASS=$pass  FAIL=$fail"
[ "$fail" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
