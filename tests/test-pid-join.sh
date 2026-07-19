#!/usr/bin/env bash
# Jailed unit tests for bus/pid-join.sh (v4 §2.3 / Part 5 step 3 — the PID-join bridge).
# Deterministic: _claude_pid is overridden so no real `claude` process is needed. Tests the
# record/lookup roundtrip, the member resolution + tag fallback, pid-recycle replacement, and the
# collision-safety property (two pids -> two members).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BUS="$HERE/../bus"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export PIDJOIN_FILE="$TMP/pid-sid"
export MEMBERS_FILE="$TMP/members"

. "$BUS/member-registry.sh"
. "$BUS/pid-join.sh"

pass=0 fail=0
ok(){ if [ "$2" = "$3" ]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL: $1 — expected [$3] got [$2]"; fi; }
rows_for_pid(){ awk -F'\t' -v p="$1" '$1==p' "$PIDJOIN_FILE" 2>/dev/null | wc -l | tr -d ' '; }

# Override the ancestry walk so tests are deterministic (the test runs under bash, not claude).
CLAUDE_PID=""
_claude_pid(){ printf '%s' "$CLAUDE_PID"; }

# 1. no claude ancestor -> my_member returns the fallback tag (the Conductor-off / not-under-claude path)
CLAUDE_PID=""
ok "no-ancestor -> fallback tag" "$(my_member other:foo)" "other:foo"

# 2. record + lookup roundtrip
CLAUDE_PID="12345"
pidjoin_record "sid-aaa"
ok "sid recorded" "$(pidjoin_sid_of_pid 12345)" "sid-aaa"
ok "my_session_id" "$(my_session_id)" "sid-aaa"

# 3. unbound sid (registry empty) -> my_member still falls back to the tag
ok "unbound sid -> fallback tag" "$(my_member other:foo)" "other:foo"

# 4. bind the sid -> my_member returns the DURABLE member
printf 'sid-aaa\tbackend\tpeer\tkeyhole\n' > "$MEMBERS_FILE"
ok "bound sid -> member" "$(my_member other:foo)" "backend"

# 5. the member is STABLE even when the fallback tag has drifted (the whole point)
ok "member stable vs cd-drifted tag" "$(my_member other:keyhole-results)" "backend"

# 6. re-record the SAME pid REPLACES (pid recycled after a session dies — old row would be a lie)
pidjoin_record "sid-bbb"
ok "one row per pid after re-record" "$(rows_for_pid 12345)" "1"
ok "re-record updates the sid" "$(pidjoin_sid_of_pid 12345)" "sid-bbb"

# 7. COLLISION SAFETY: two pids -> two sids, each resolves independently (tag cannot do this)
CLAUDE_PID="22222"; pidjoin_record "sid-ccc"
ok "pid 12345 keeps its sid" "$(pidjoin_sid_of_pid 12345)" "sid-bbb"
ok "pid 22222 has its own sid" "$(pidjoin_sid_of_pid 22222)" "sid-ccc"

# 8. empty session_id is a no-op (no bogus row)
CLAUDE_PID="33333"; pidjoin_record ""
ok "empty sid records nothing" "$(pidjoin_sid_of_pid 33333 || echo NONE)" "NONE"

# 9. no claude ancestor -> record is a no-op even with a real sid
CLAUDE_PID=""; before="$(wc -l < "$PIDJOIN_FILE" | tr -d ' ')"
pidjoin_record "sid-ddd"
after="$(wc -l < "$PIDJOIN_FILE" | tr -d ' ')"
ok "no-ancestor record is a no-op" "$after" "$before"

# 10. member-registry NOT sourced -> my_member still returns the fallback (degrade, don't crash)
(
  unset -f member_of _mr_lookup 2>/dev/null || true
  CLAUDE_PID="12345"
  ok(){ if [ "$2" = "$3" ]; then :; else echo "FAIL: $1 — expected [$3] got [$2]"; exit 3; fi; }
  # re-source only pid-join in this subshell without member-registry
  . "$BUS/pid-join.sh"
  _claude_pid(){ printf '%s' "12345"; }
  [ "$(my_member other:foo)" = "other:foo" ] || { echo "FAIL: no-registry -> fallback"; exit 3; }
) && pass=$((pass+1)) || fail=$((fail+1))

echo "---"; echo "pid-join: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
