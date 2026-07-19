#!/usr/bin/env bash
# Integration test: the REAL bus/bus.sh seeds the PID-join from its session-start / prompt-check
# hooks, and `whoami --member` resolves the durable member (v4 step 3). Jailed via HOME so no real
# bus-state is touched. CLAUDE_PID_OVERRIDE stands in for a claude ancestor the test doesn't have.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BUS="$HERE/../bus/bus.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export HOME="$TMP"
mkdir -p "$HOME/.claude/bus-state" "$HOME/Documents/claude-bus"
export BUS_FILE="$HOME/Documents/claude-bus/messages.md"; : > "$BUS_FILE"
STATE="$HOME/.claude/bus-state"; PIDSID="$STATE/pid-sid"; MEMBERS="$STATE/members"
WORK="$HOME/work/myproj"; mkdir -p "$WORK"

pass=0 fail=0
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }
sid_for(){ awk -F'\t' -v p="$1" '$1==p{print $2}' "$PIDSID" 2>/dev/null; }

TAG="$(cd "$WORK" && bash "$BUS" whoami)"

# 1. session-start with a hook payload seeds claude_pid -> session_id
echo '{"session_id":"sid-xyz","cwd":"'"$WORK"'","hook_event_name":"SessionStart"}' \
  | (cd "$WORK" && CLAUDE_PID_OVERRIDE=99001 bash "$BUS" session-start >/dev/null 2>&1)
ok "session-start seeds the join" "$(sid_for 99001)" "sid-xyz"

# 2. whoami --member falls back to the TAG while unbound (registry has no row yet)
ok "unbound -> tag fallback" "$(cd "$WORK" && CLAUDE_PID_OVERRIDE=99001 bash "$BUS" whoami --member)" "$TAG"

# 3. bind sid-xyz -> backend; whoami --member now returns the durable member
printf 'sid-xyz\tbackend\tpeer\tmyproj\n' > "$MEMBERS"
ok "bound -> member" "$(cd "$WORK" && CLAUDE_PID_OVERRIDE=99001 bash "$BUS" whoami --member)" "backend"

# 4. the member is stable even from a DIFFERENT cwd (drifted tag) — same pid override, other dir
OTHER="$HOME/work/myproj/results"; mkdir -p "$OTHER"
ok "member stable across cd" "$(cd "$OTHER" && CLAUDE_PID_OVERRIDE=99001 bash "$BUS" whoami --member)" "backend"

# 5. plain `whoami` is UNCHANGED (back-compat — the resource-watchdog depends on it)
ok "plain whoami unchanged" "$(cd "$WORK" && CLAUDE_PID_OVERRIDE=99001 bash "$BUS" whoami)" "$TAG"

# 6. prompt-check also seeds the join (a second pid/sid), and both coexist (collision-safe)
echo '{"session_id":"sid-two","cwd":"'"$WORK"'","hook_event_name":"UserPromptSubmit"}' \
  | (cd "$WORK" && CLAUDE_PID_OVERRIDE=99002 bash "$BUS" prompt-check >/dev/null 2>&1)
ok "prompt-check seeds the join" "$(sid_for 99002)" "sid-two"
ok "first pid still resolves" "$(sid_for 99001)" "sid-xyz"

# 7. no override, plain shell (no claude ancestor / real pid not in the jailed join) -> tag, no hang
ok "no-ancestor whoami --member -> tag" "$(cd "$WORK" && bash "$BUS" whoami --member)" "$TAG"

# 8. session-start with NO stdin payload does not hang and writes no bogus row
before="$(wc -l < "$PIDSID" | tr -d ' ')"
(cd "$WORK" && CLAUDE_PID_OVERRIDE=99003 bash "$BUS" session-start < /dev/null >/dev/null 2>&1)
after="$(wc -l < "$PIDSID" | tr -d ' ')"
ok "empty-payload session-start writes nothing" "$after" "$before"

echo "---"; echo "pid-join integration: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
