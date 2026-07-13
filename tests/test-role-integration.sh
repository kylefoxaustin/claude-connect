#!/usr/bin/env bash
# Integration test: role pre-check wired into persist-gate.sh. Jailed.
set -u
GATE=~/Documents/GitHub/claude-connect/bus/persist-gate.sh
J="$(mktemp -d)"
export BUS_STATE_DIR="$J/bus-state"; mkdir -p "$BUS_STATE_DIR"
CH="$J/claude"; mkdir -p "$CH"
pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  OK  $1"; pass=$((pass+1)); else echo "  XX  $1 exit=$2 want=$3"; fail=$((fail+1)); fi; }

run() {  # session_id tool file_path -> exit code
  local sid="$1" tool="$2" fp="$3"
  printf '{"session_id":"%s","tool_name":"%s","tool_input":{"file_path":"%s"},"cwd":"/tmp"}' "$sid" "$tool" "$fp" \
    | CLAUDE_CONFIG_DIR="$CH" bash "$GATE" >/dev/null 2>&1; echo $?
}
runbash() {  # session_id command -> exit code
  local sid="$1" cmd="$2"
  printf '{"session_id":"%s","tool_name":"Bash","tool_input":{"command":"%s"},"cwd":"/tmp"}' "$sid" "$cmd" \
    | CLAUDE_CONFIG_DIR="$CH" bash "$GATE" >/dev/null 2>&1; echo $?
}

# === A) NO members file -> role check is skipped, gate behaves as today ===
rm -f "$BUS_STATE_DIR/members"
ck "no-roles: Edit a normal file ALLOWED (today)"     "$(run any Edit /tmp/proj/main.py)" "0"
ck "no-roles: Edit settings.json still GATED"         "$(run any Edit "$CH/settings.json")" "2"

# === B) members file: sid-obs is OBSERVER, sid-peer is PEER ===
printf 'sid-obs\tobserver\tobserver\tproj\n' >  "$BUS_STATE_DIR/members"
printf 'sid-peer\tbackend\tpeer\tproj\n'      >> "$BUS_STATE_DIR/members"

ck "observer: Edit a NORMAL file DENIED by role"      "$(run sid-obs Edit /tmp/proj/main.py)" "2"
ck "observer: Write a normal file DENIED by role"     "$(run sid-obs Write /tmp/proj/x.py)"   "2"
ck "observer: Read is not gated here (exit 0)"        "$(run sid-obs Read /tmp/proj/main.py)" "0"
ck "peer: Edit a normal file ALLOWED (falls through)" "$(run sid-peer Edit /tmp/proj/main.py)" "0"
ck "peer: Edit settings.json still GATED (persist)"   "$(run sid-peer Edit "$CH/settings.json")" "2"
ck "unbound sid: Edit normal file ALLOWED (peer dflt)" "$(run sid-nobody Edit /tmp/proj/main.py)" "0"

# Observer Bash: exact write-tools are enforced; a Bash write is deferred to the OS floor, so a
# NON-gated Bash command from an observer is NOT denied at this hook (falls through, exit 0).
ck "observer: plain Bash (non-gated) falls through"   "$(runbash sid-obs 'echo hello')" "0"

echo; echo "  === $pass passed, $fail failed ==="
rm -rf "$J"
[ "$fail" -eq 0 ]
