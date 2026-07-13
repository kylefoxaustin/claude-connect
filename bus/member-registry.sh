#!/usr/bin/env bash
# Member registry — the durable-principal resolver (v4 §3.4). SOURCE this; it defines functions.
#
# A MEMBER is the durable worker/conversation. `session_id` (harness-minted, unforgeable, stable
# across --continue) is its credential; the member is the principal that a role and a read-cursor
# attach to. The project is a SOFT label on the member, not its identity — so a session can extend
# its mandate into an adjacent repo and stay the same member (the flexibility Kyle values), and a
# `cd` can never change who it is (the tag-drift class, closed).
#
# THE REGISTRY IS A DATA FILE the referee reads FIRST — the tag-map pattern (v2.32.1), so a script
# migration can never touch the bindings. One TAB-separated line per bound session:
#
#     <session_id>\t<member>\t<role>\t<project>
#
#   • member  — the durable name (e.g. `backend`). Human-facing; assigned/confirmed by Conductor,
#               NOT derived from the directory. Stable across a `cd`.
#   • role    — observer | service | peer | trusted   (default: peer, the compat-window ratchet).
#   • project — a display hint only.  '#'-prefixed and blank lines are ignored.
#
# Binding is blunt because the ambiguous case is not one the operator creates on purpose (§3.4):
# --continue preserves session_id -> same member; a fresh `claude` is a new session_id -> a new
# member. Two session_ids = two members, full stop. An UNBOUND session_id falls back to the
# caller-supplied name (the tag) with role `peer` — visible-and-warned, ratcheting to `observer`
# once launch-binding has run clean (see §3.4).

MEMBERS_FILE="${MEMBERS_FILE:-${BUS_STATE_DIR:-$HOME/.claude/bus-state}/members}"

# _mr_lookup <session_id> -> echoes "member<TAB>role" for the FIRST matching row, or nothing.
_mr_lookup() {
  local sid="$1" s m r p
  [ -n "$sid" ] && [ -r "$MEMBERS_FILE" ] || return 1
  while IFS="$(printf '\t')" read -r s m r p; do
    case "$s" in ''|'#'*) continue ;; esac
    if [ "$s" = "$sid" ] && [ -n "$m" ]; then
      printf '%s\t%s\n' "$m" "${r:-peer}"
      return 0
    fi
  done < "$MEMBERS_FILE"
  return 1
}

# member_of <session_id> [fallback_name] -> the durable member name.
# Unbound -> the fallback (the caller's tag/project), so nothing breaks before Conductor binds.
member_of() {
  local hit; hit="$(_mr_lookup "$1")" && { printf '%s\n' "${hit%%$'\t'*}"; return 0; }
  printf '%s\n' "${2:-}"
}

# role_of <session_id> -> the member's role. Unbound default is `peer` (the compat-window ratchet,
# §3.4); NEVER silently grant more than that to an identity the registry has never seen.
role_of() {
  local hit; hit="$(_mr_lookup "$1")" && { printf '%s\n' "${hit#*$'\t'}"; return 0; }
  printf '%s\n' "peer"
}

# is_bound <session_id> -> 0 if this session_id has a registry row, else 1. Callers use this to
# warn loudly on an unbound session (the fallback is the ALARM, not the default — image_gen's rule).
is_bound() { _mr_lookup "$1" >/dev/null 2>&1; }
