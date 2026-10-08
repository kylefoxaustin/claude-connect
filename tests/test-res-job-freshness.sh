#!/usr/bin/env bash
# A lease's `job=` string must carry a freshness contract.
#
# 2026-10-07: rt1180renode needed 32 cores. splat-vla held the GPU with the job string
# "resource profile + accuracy sets". A resource profile is exactly the measurement 32
# spinning cores destroy, so it correctly declined to add load and asked instead. The
# profile had finished an HOUR earlier; what was actually running was a temp-0 accuracy
# pass, where contention changes the ETA and not the numbers. It asked the right question
# about the wrong state of the world, and nothing in the lease could have told it otherwise.
#
# `job=` was written once at acquire and advertised the PLAN, not what was running.
#
# ⚠️ WHY THE STAMP CANNOT BE DERIVED FROM `acquired_epoch`, which was the cheaper design:
# `/keep` extends a lease by calling `_res_write`, which REWRITES `acquired_epoch` to now.
# Lease age would therefore report an hours-stale job string as freshly set — wrong in the
# flattering direction, which is the one nobody checks. That is pinned below.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUS="${BUS_SH:-$ROOT/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
REAL="$HOME/Documents/claude-bus/messages.md"; RB="$(wc -c < "$REAL" 2>/dev/null || echo 0)"

H="$T/home"; BF="$T/bus.md"
mkdir -p "$H/.claude/bus-state" "$T/p1" "$T/p2"
printf 'other:p1\nother:p2\n' > "$H/.claude/bus-state/active-tags"; : > "$BF"
LEASE="$H/.claude/bus-state/resources/testgpu/lease"
r1(){ (cd "$T/p1" && HOME="$H" BUS_FILE="$BF" bash "$BUS" res "$@" 2>&1); }
r2(){ (cd "$T/p2" && HOME="$H" BUS_FILE="$BF" bash "$BUS" res "$@" 2>&1); }
age_stamp(){ python3 - "$LEASE" "$1" <<'PY'
import re, sys, time
p, secs = sys.argv[1], int(sys.argv[2])
s = open(p).read()
s = re.sub(r'job_updated_epoch=\d+', 'job_updated_epoch=%d' % (int(time.time()) - secs), s)
open(p, 'w').write(s)
PY
}

r1 reserve testgpu 2h hard "resource profile + accuracy sets" >/dev/null
grep -q '^job_updated_epoch=' "$LEASE" && ok "reserve stamps job_updated_epoch" || no "no job_updated_epoch written"

# fresh -> the age must NOT be rendered (noise on every line would train people past it)
r2 status testgpu | grep -q '⏱' && no "a fresh job string showed an age" || ok "a fresh job string renders no age"

# stale -> the peer sees it
age_stamp 5400
r2 status testgpu | grep -q '⏱ set 1h 30m ago' \
  && ok "a 90-minute-old job string is rendered as stale to a PEER" \
  || no "stale job age not shown: $(r2 status testgpu | grep -i 'held by')"

# ⚠️ THE CASE THAT DECIDED THE DESIGN: /keep must NOT make a stale job look fresh.
r1 keep testgpu 2h >/dev/null
r2 status testgpu | grep -q '⏱' \
  && ok "/keep extends the lease WITHOUT refreshing the job stamp" \
  || no "/keep laundered a stale job string into a fresh one — acquired_epoch is not a valid proxy"
# and it really did extend
r2 status testgpu | grep -q 'left' && ok "/keep still extended the lease" || no "/keep broke the lease"

# updating the job clears the staleness
r1 job testgpu "temp-0 accuracy pass — contention changes ETA not numbers" >/dev/null
r2 status testgpu | grep -q '⏱' && no "job update did not refresh the stamp" || ok "updating the job clears the stale marker"
r2 status testgpu | grep -q 'temp-0 accuracy pass' && ok "the new job text is what peers see" || no "job text not updated"

# a job update is a DESCRIPTION change, not a renewal — it must not extend the lease
before="$(grep '^expires_epoch=' "$LEASE" | cut -d= -f2)"
sleep 1
r1 job testgpu "set_b accuracy run" >/dev/null
after="$(grep '^expires_epoch=' "$LEASE" | cut -d= -f2)"
[ "$after" -le "$((before + 2))" ] && ok "updating the job does not silently extend the lease" \
  || no "job update extended the lease by $((after - before))s — a description change must not renew"

# the confirmation must name the RESOURCE, not the job text (after `shift`, $1 is the text)
r1 job testgpu "some long description here" | grep -q 'Updated the testgpu job string' \
  && ok "confirmation names the resource, not the job text" \
  || no "confirmation mislabels: $(r1 job testgpu 'x' | head -1)"

# only the holder may rewrite it
# NOTE: capture first, then grep. `set -o pipefail` is on and a refusal legitimately
# exits 1, so `r2 ... | grep -q` returns 1 even when grep MATCHES — the assertion would
# grade the refusal's exit code instead of its message, and report a working refusal as
# a failure. Any test piping from a command that returns non-zero by design has this bug.
_refusal="$(r2 job testgpu "I do not hold this" || true)"
grep -qi "don't hold" <<<"$_refusal" && ok "a non-holder is refused" \
  || no "a non-holder rewrote the job string (got: $_refusal)"
r2 status testgpu | grep -q 'I do not hold this' && no "the refused text landed anyway" || ok "the refused update changed nothing"

# a lease written BEFORE this field existed must render nothing rather than claim freshness
sed -i '/^job_updated_epoch=/d' "$LEASE"
out="$(r2 status testgpu)"
grep -q '⏱' <<<"$out" && no "a lease with no stamp claimed an age" || ok "a pre-existing lease with no stamp renders no age (never guesses)"
grep -q 'held by' <<<"$out" && ok "a pre-existing lease still renders normally" || no "missing stamp broke the line"

[ "$(wc -c < "$REAL" 2>/dev/null || echo 0)" = "$RB" ] && ok "real bus untouched" || no "THE REAL BUS GREW"
printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
