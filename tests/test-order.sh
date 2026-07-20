#!/usr/bin/env bash
# Jailed lifecycle test for the agentic-delivery ORDER primitive (bus/order.sh). Two identities —
# the requester (tipometer) and the service (imagegen) — via two cwds, because the whole point is
# that they are DIFFERENT actors: a service cannot grade its own delivery. Proves the state machine,
# the actor permissions, and the load-bearing invariant: `deliver` refuses until the files LANDED.
set -u
BUS=/home/kyle/Documents/GitHub/claude-connect/bus/bus.sh
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
SD="$HOME/.claude/bus-state"; mkdir -p "$SD/coord" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"
export ORDER_STATE_DIR="$SD/coord/orders"
REQ="$HOME/w/tipometer"; SVC="$HOME/w/imagegen"; mkdir -p "$REQ" "$SVC"
DROP="$HOME/drop"; mkdir -p "$DROP"
# identities derive from cwd basename: other:tipometer -> tipometer, other:imagegen -> imagegen
req(){ (cd "$REQ" && bash "$BUS" order "$@" 2>&1); }
svc(){ (cd "$SVC" && bash "$BUS" order "$@" 2>&1); }

pass=0 fail=0
okc(){ if printf '%s' "$2" | grep -qiF "$3"; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — missing [$3] in: $2"; fi; }
state(){ req status "$1" | python3 -c "import sys,json;print(json.load(sys.stdin)['state'])" 2>/dev/null; }
rev(){ req status "$1" | python3 -c "import sys,json;print(json.load(sys.stdin)['revision'])" 2>/dev/null; }
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }

# 1. place (requester owns the ticket)
okc "place" "$(req place o1 to:imagegen path:$DROP files:a.png,b.png format:'512 RGBA' accept:'cast-in')" "Placed order 'o1'"
ok  "state PLACED" "$(state o1)" "PLACED"

# 2. a non-addressed service cannot claim; the addressed one can
okc "wrong service can't claim" "$(req claim o1)" "addressed to imagegen"          # requester isn't the service
okc "addressed service claims" "$(svc claim o1 eta:8m)" "Claimed order 'o1'"
ok  "state CLAIMED" "$(state o1)" "CLAIMED"

# 3. THE INVARIANT: deliver refuses while the files are not on disk
okc "deliver refuses w/o files" "$(svc deliver o1)" "NOT DELIVERED"
ok  "still not DELIVERED" "$(state o1)" "CLAIMED"

# 4. a non-service cannot deliver
okc "requester cannot deliver" "$(req deliver o1)" "only the claiming service"

# 5. write the files -> deliver VERIFIES and transitions
printf 'x' > "$DROP/a.png"; printf 'y' > "$DROP/b.png"
okc "deliver verifies landing" "$(svc deliver o1)" "VERIFIED 2 file"
ok  "state DELIVERED" "$(state o1)" "DELIVERED"

# 6. a service cannot accept its own delivery; the requester can reject with a reason
okc "service cannot accept" "$(svc accept o1)" "only the requester"
okc "reject needs a reason" "$(req reject o1)" "needs a specific"
okc "reject with reason" "$(req reject o1 still reads pasted, not cast-in)" "back to COOKING"
ok  "state COOKING after reject" "$(state o1)" "COOKING"
ok  "revision bumped" "$(rev o1)" "1"
okc "reason retained in history" "$(req status o1)" "still reads pasted"

# 7. re-deliver the revision, requester accepts -> CLOSED
okc "re-deliver rev1" "$(svc deliver o1)" "VERIFIED"
okc "requester accepts" "$(req accept o1)" "CONFIRMED and CLOSED"
ok  "state CLOSED" "$(state o1)" "CLOSED"

# 8. revision ceiling surfaces to the human
req place o2 to:imagegen path:$DROP files:a.png >/dev/null
svc claim o2 >/dev/null
for i in 1 2 3 4 5 6; do svc deliver o2 >/dev/null; req reject o2 "nope $i" >/dev/null; done
okc "ceiling warns to pull Kyle in" "$(svc deliver o2; req reject o2 'again')" "pulling Kyle in"

# 9. list shows orders
okc "list shows orders" "$(req list)" "o1"

echo "---"; echo "order: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
