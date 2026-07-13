#!/usr/bin/env bash
# Tests for the member registry resolver (v4 §3.4). Jailed: its own MEMBERS_FILE, touches nothing live.
set -u
J="$(mktemp -d)"
export MEMBERS_FILE="$J/members"
. ~/Documents/GitHub/claude-connect/bus/member-registry.sh

pass=0; fail=0
ck() { if [ "$2" = "$3" ]; then echo "  OK  $1"; pass=$((pass+1)); else echo "  XX  $1 : got[$2] want[$3]"; fail=$((fail+1)); fi; }

printf '# session_id\tmember\trole\tproject\n' > "$MEMBERS_FILE"
printf 'sid-aaa\tbackend\tpeer\tkeyhole\n'      >> "$MEMBERS_FILE"
printf 'sid-bbb\tdocs\tobserver\tpersonal-ai\n' >> "$MEMBERS_FILE"
printf 'sid-ccc\timage_gen\ttrusted\t\n'        >> "$MEMBERS_FILE"   # no project column
printf 'sid-ddd\tsvc1\t\t\n'                    >> "$MEMBERS_FILE"   # no role -> default peer

# --- bound sessions resolve to their durable member + role ---
ck "member_of bound (backend)"        "$(member_of sid-aaa)"  "backend"
ck "role_of bound (peer)"             "$(role_of sid-aaa)"    "peer"
ck "member_of bound (docs)"           "$(member_of sid-bbb)"  "docs"
ck "role_of observer"                 "$(role_of sid-bbb)"    "observer"
ck "role_of trusted"                  "$(role_of sid-ccc)"    "trusted"
ck "role missing -> defaults to peer" "$(role_of sid-ddd)"    "peer"
ck "is_bound true"                    "$(is_bound sid-aaa && echo Y || echo N)" "Y"

# --- the durable member is STABLE regardless of caller-supplied fallback (a cd cannot change it) ---
ck "bound member ignores cd fallback" "$(member_of sid-aaa other:some-adjacent-repo)" "backend"

# --- unbound session_id: falls back to the caller's tag, role defaults to peer (the ratchet) ---
ck "unbound -> fallback tag"          "$(member_of sid-UNKNOWN other:whoami)" "other:whoami"
ck "unbound -> role peer"             "$(role_of sid-UNKNOWN)" "peer"
ck "unbound is_bound false"           "$(is_bound sid-UNKNOWN && echo Y || echo N)" "N"
ck "empty sid is_bound false"         "$(is_bound '' && echo Y || echo N)" "N"

# --- no registry file at all: everything falls back safely (nothing breaks before Conductor binds) ---
rm -f "$MEMBERS_FILE"
ck "no file -> fallback tag"          "$(member_of sid-aaa other:fromcwd)" "other:fromcwd"
ck "no file -> role peer"             "$(role_of sid-aaa)" "peer"

echo; echo "  === $pass passed, $fail failed ==="
rm -rf "$J"
[ "$fail" -eq 0 ]
