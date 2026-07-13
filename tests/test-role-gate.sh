#!/usr/bin/env bash
# Tests for the role enforcement pre-check (v4 §3.3/§3.4). Pure function, no state.
set -u
. ~/Documents/GitHub/claude-connect/bus/role-gate.sh
pass=0; fail=0
# verdict <role> <tool> <is_write> -> "DENY" or "ALLOW"
verdict() { if role_verdict "$1" "$2" "${3:-0}" >/dev/null; then echo DENY; else echo ALLOW; fi; }
ck() { if [ "$2" = "$3" ]; then echo "  OK  $1"; pass=$((pass+1)); else echo "  XX  $1 : got[$2] want[$3]"; fail=$((fail+1)); fi; }

# --- OBSERVER: read-only by construction ---
ck "observer denies Edit"            "$(verdict observer Edit)"          "DENY"
ck "observer denies Write"           "$(verdict observer Write)"         "DENY"
ck "observer denies MultiEdit"       "$(verdict observer MultiEdit)"     "DENY"
ck "observer denies NotebookEdit"    "$(verdict observer NotebookEdit)"  "DENY"
ck "observer denies a WRITING Bash"  "$(verdict observer Bash 1)"        "DENY"
ck "observer ALLOWS a reading Bash"  "$(verdict observer Bash 0)"        "ALLOW"
ck "observer ALLOWS a read tool"     "$(verdict observer Read)"          "ALLOW"
ck "observer ALLOWS Grep"            "$(verdict observer Grep)"          "ALLOW"

# --- PEER: the baseline == today. NEVER a role-level denial (act gates still apply separately) ---
ck "peer allows Edit"                "$(verdict peer Edit)"              "ALLOW"
ck "peer allows Write"               "$(verdict peer Write)"            "ALLOW"
ck "peer allows a writing Bash"      "$(verdict peer Bash 1)"           "ALLOW"

# --- TRUSTED: also no role-level denial (elevation handled elsewhere) ---
ck "trusted allows Edit"             "$(verdict trusted Edit)"          "ALLOW"

# --- UNBOUND / unknown role -> treated as Peer (safe; act gates still apply) ---
ck "empty role allows Edit"          "$(verdict '' Edit)"               "ALLOW"
ck "unknown role allows Edit"        "$(verdict frobnicate Edit)"       "ALLOW"

# --- SERVICE: no push handled at act gate; role-gate adds no Edit denial (writes-in-scratch TBD) ---
ck "service allows Edit (scratch TBD)" "$(verdict service Edit)"        "ALLOW"

echo; echo "  === $pass passed, $fail failed ==="
[ "$fail" -eq 0 ]
