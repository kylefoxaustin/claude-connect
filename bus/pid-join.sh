#!/usr/bin/env bash
# PID-join bridge — resolve a bus.sh invocation's durable MEMBER (v4 §2.3 / Part 5 step 3).
# SOURCE this; it defines functions. Pairs with member-registry.sh (member_of).
#
# THE PROBLEM: bus.sh runs as a plain command and NEVER sees session_id — only hooks do (it
# arrives in the hook's stdin JSON payload). But the read-cursor must key on the durable MEMBER
# (session_id -> member, via the registry), NOT the drift-prone cwd tag, or a session that cd's
# loses its mail (the tag-drift class §2.3/§3.4 exists to close).
#
# THE BRIDGE (the v2.30 provenance pattern): a hook that HAS session_id records claude_pid ->
# session_id; any later bus.sh invocation walks up its OWN process ancestry to the same `claude`
# ancestor and looks the session_id back up. Two independent parties, joined on the PID neither
# forges. Because the key is the live PROCESS, it is COLLISION-SAFE BY CONSTRUCTION: two claudes in
# one repo have distinct pids and distinct session_ids where the cwd-derived tag cannot tell them
# apart — the failure holobench measured.
#
# TWO SAFETY PROPERTIES, both load-bearing:
#   • CONDUCTOR-INDEPENDENT — the join is written by the session's OWN hooks (which run whether or
#     not Conductor is up), and member_of() falls back to the caller's tag when the registry has no
#     binding yet. So the cursor keeps working exactly as today when Conductor is off. It must: the
#     cursor is bus.sh's, not Conductor's.
#   • FAIL-TO-TAG — every step degrades to the tag fallback (no claude ancestor, no join row, no
#     registry, unbound session). my_member "$TAG" == "$TAG" today; == the durable member once
#     Conductor binds. Nothing breaks before that, nothing breaks without Conductor.

PIDJOIN_FILE="${PIDJOIN_FILE:-${BUS_STATE_DIR:-$HOME/.claude/bus-state}/pid-sid}"

# _claude_pid — the pid of the `claude` process THIS bus.sh (or hook) runs under, by walking the
# process ancestry until comm=claude. Same walk _owner_pid uses for leases: it deliberately finds
# the `claude` process (which dies with the session), NOT the `bash -c "... claude; exec bash"`
# wrapper (which SURVIVES claude's death and would name a corpse). Empty if not under a claude.
_claude_pid() {
  # Test seam: a jailed integration test has no real `claude` in its ancestry, so it sets
  # CLAUDE_PID_OVERRIDE to name one. Advisory only — the pid-join confers NO authority (it just
  # picks the cursor key), so an override can never escalate anything; it is not a security seam.
  [ -n "${CLAUDE_PID_OVERRIDE:-}" ] && { printf '%s' "$CLAUDE_PID_OVERRIDE"; return 0; }
  #
  # ⚠️ NEVER IDENTIFY THE PROCESS BY `comm`. Found by qualcomm and independently confirmed by
  # lostchild, 2026-09-04, after qualcomm's read cursor sat frozen for two weeks.
  #
  # Claude Code execs its VERSIONED binary directly, so `comm` is a version string:
  #     hop 1  pid=2396401  comm='bash'
  #     hop 2  pid=3844859  comm='2.1.237'   <- the claude process
  #     exe of 3844859: /home/kyle/.local/share/claude/versions/2.1.237
  # No hop is named "claude", so this returned EMPTY -> my_session_id empty -> _turn_marker empty
  # -> the writer staged "<ts><TAB>" with no marker -> Stop held a REAL marker from its payload ->
  # mismatch -> `rm -f` -> the cursor could never advance. Not a broken Stop hook: a marker that
  # was never written. The session read its mail and threw away the receipt every single turn.
  #
  # ⭐ AND IT SPREADS ON ITS OWN. Two version strings are live right now (2.1.237, 2.1.257) and
  # lostchild's cursor works only because its process happens to still be literally named
  # `claude`. Every session that restarts onto a versioned launcher freezes, one at a time,
  # silently. 170 of 188 pid-join rows are dead for the same reason.
  #
  # `comm` is also truncated at 15 bytes, which bit this corpus before
  # (`qemu-system-aarch64` -> `qemu-system-aar`). So: resolve the EXE PATH and identify the
  # install, never the name. Same fix, same day, as conductor/scanner.py's is_claude_process —
  # which is the part that stings: that lesson was written down on 2026-08-31 and not swept for
  # elsewhere, and this file had the identical predicate the whole time.
  local p="$$" c e i
  for i in 1 2 3 4 5 6 7 8; do
    [ -r "/proc/$p/comm" ] || break
    c="$(cat "/proc/$p/comm" 2>/dev/null || true)"
    [ "$c" = "claude" ] && { printf '%s' "$p"; return 0; }
    e="$(readlink "/proc/$p/exe" 2>/dev/null || true)"
    case "$e" in
      */claude/versions/*|*/bin/claude|*/claude) printf '%s' "$p"; return 0 ;;
    esac
    p="$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null || true)"
    case "$p" in ''|0|1) break ;; esac
  done
  printf '%s' ''
}

# pidjoin_record <session_id> — write "claude_pid<TAB>session_id", REPLACING any prior row for this
# pid (a pid is recycled after a session dies, so the old row would be a lie). No-op if there is no
# session_id or no claude ancestor. Called by the session-start / prompt-check hooks, which carry
# session_id in their stdin payload. Never fails the caller (returns 0) — a provenance breadcrumb
# must never be able to abort a hook.
pidjoin_record() {
  local sid="$1" pid tmp dir
  [ -n "$sid" ] || return 0
  pid="$(_claude_pid)"
  [ -n "$pid" ] || return 0
  dir="$(dirname "$PIDJOIN_FILE")"
  mkdir -p "$dir" 2>/dev/null || return 0
  tmp="$PIDJOIN_FILE.$$.tmp"
  # drop any stale row for THIS pid (awk, so no TAB-escaping fragility), append the fresh one,
  # atomic-replace. On any failure, clean the temp and leave the old file intact.
  { [ -r "$PIDJOIN_FILE" ] && awk -F'\t' -v pid="$pid" '$1!=pid' "$PIDJOIN_FILE" 2>/dev/null
    printf '%s\t%s\n' "$pid" "$sid"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "$PIDJOIN_FILE" 2>/dev/null || rm -f "$tmp" 2>/dev/null
  return 0
}

# pidjoin_sid_of_pid <pid> — the session_id recorded for a claude pid, or nothing (exit 1).
pidjoin_sid_of_pid() {
  local pid="$1" p s
  [ -n "$pid" ] && [ -r "$PIDJOIN_FILE" ] || return 1
  while IFS="$(printf '\t')" read -r p s; do
    [ "$p" = "$pid" ] && [ -n "$s" ] && { printf '%s\n' "$s"; return 0; }
  done < "$PIDJOIN_FILE"
  return 1
}

# my_session_id — this session's id via the pid-join, or nothing.
my_session_id() { pidjoin_sid_of_pid "$(_claude_pid)"; }

# my_member <fallback_tag> — THIS SESSION'S DURABLE MEMBER (the cursor keys on this in step 5).
# pid-join -> session_id -> member_of() -> member, or the fallback tag at any missing link
# (no claude ancestor, no join row, registry absent/unbound). Requires member-registry.sh sourced;
# if member_of is not defined, returns the fallback unchanged.
my_member() {
  local fallback="$1" sid
  sid="$(my_session_id 2>/dev/null || true)"
  if [ -n "$sid" ] && command -v member_of >/dev/null 2>&1; then
    member_of "$sid" "$fallback"
  else
    printf '%s\n' "$fallback"
  fi
}
