#!/usr/bin/env bash
# The @-mention routing hook (UserPromptSubmit). Routes a leading/trailing @<registered session>
# and BLOCKS the prompt; leaves everything else untouched; FAILS OPEN. Drives the REAL hook.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/bus/prompt-route.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export BUS_STATE_DIR="$SB/bus-state"
RDIR="$BUS_STATE_DIR/coord/prompt-routes"
mkdir -p "$BUS_STATE_DIR/coord"
printf 'other:qualcomm\nother:image_gen\nother:me\n' > "$BUS_STATE_DIR/active-tags"
printf '# hdr\nSID-ME\tother:me\tpeer\tother:me\n'   > "$BUS_STATE_DIR/members"

payload() { python3 -c 'import json,sys;print(json.dumps({"session_id":sys.argv[1],"user_input":sys.argv[2]}))' "$1" "$2"; }
run()     { payload "$1" "$2" | bash "$HOOK" 2>/dev/null; }   # stdout = hook decision JSON (or empty)
routes()  { ls "$RDIR"/*.json 2>/dev/null | wc -l | tr -d ' '; }
clr()     { rm -f "$RDIR"/*.json 2>/dev/null || true; }
newest()  { ls -t "$RDIR"/*.json 2>/dev/null | head -1; }

# 1. leading @known -> BLOCK + route file with the right target + stripped message
clr; out="$(run SID-OTHER "@qualcomm rerun the benchmark")"
echo "$out" | grep -q '"decision": *"block"' && ok "leading @known: blocks" || bad "leading @known: no block"
[ "$(routes)" = 1 ] && ok "leading @known: route filed" || bad "leading @known: no route file"
f="$(newest)"; grep -q '"target": *"qualcomm"' "$f" && grep -q '"message": *"rerun the benchmark"' "$f" \
  && ok "leading: target+message correct" || bad "leading: wrong target/message ($(cat "$f"))"

# 2. TRAILING @known -> route, message is everything before it
clr; out="$(run SID-OTHER "yeah I agree lets do it @qualcomm")"
echo "$out" | grep -q '"decision": *"block"' && ok "trailing @known: blocks" || bad "trailing @known: no block"
f="$(newest)"; grep -q '"message": *"yeah I agree lets do it"' "$f" && ok "trailing: message stripped of @tag" || bad "trailing: wrong message ($(cat "$f" 2>/dev/null))"

# 3. trailing with punctuation
clr; run SID-OTHER "lets ship it @image_gen!" >/dev/null
f="$(newest)"; [ -n "$f" ] && grep -q '"target": *"image_gen"' "$f" && ok "trailing + punctuation: routes to image_gen" || bad "trailing+punct failed"

# 4. MID-SENTENCE @known -> NOT routed (talking about it)
clr; out="$(run SID-OTHER "the @qualcomm session found a bug")"
[ -z "$out" ] && [ "$(routes)" = 0 ] && ok "mid-sentence @known: NOT routed" || bad "mid-sentence wrongly routed"

# 5. leading @UNKNOWN tag -> NOT routed
clr; out="$(run SID-OTHER "@notasession do the thing")"
[ -z "$out" ] && [ "$(routes)" = 0 ] && ok "unknown @tag: NOT routed" || bad "unknown tag wrongly routed"

# 6. @self -> NOT routed (handled here)
clr; out="$(run SID-ME "@me look at this")"
[ -z "$out" ] && [ "$(routes)" = 0 ] && ok "@self: NOT routed" || bad "@self wrongly routed"

# 7. a normal prompt with no @ -> untouched
clr; out="$(run SID-OTHER "please run the tests")"
[ -z "$out" ] && [ "$(routes)" = 0 ] && ok "normal prompt: untouched" || bad "normal prompt disturbed"

# 8. FAIL-OPEN on garbage payload
clr; out="$(printf 'not json at all' | bash "$HOOK" 2>/dev/null; echo "rc=$?")"
echo "$out" | grep -q 'rc=0' && ok "garbage payload: exits 0 (fail-open)" || bad "garbage payload didn't fail open"
[ "$(routes)" = 0 ] && ok "garbage payload: routed nothing" || bad "garbage routed something"

echo "── prompt-route-hook: $pass passed, $fail failed"
[ "$fail" = 0 ]
