#!/usr/bin/env bash
# Role enforcement — the referee's role pre-check (v4 §3.3/§3.4). SOURCE this; it defines a function.
#
# This is the MIDDLE layer of enforcement (§3.4): construction sets the ceiling (an Observer launches
# with the write tools absent), the OS sets the floor (a sandbox), and THIS hook check is the dial —
# mid-flight, keyed on the member's role, which is resolved from the unforgeable session_id via the
# member registry. It runs INSIDE the existing PreToolUse gate, BEFORE the act-specific checks.
#
# ⭐ DEFAULT IS PEER, AND PEER IS BYTE-FOR-BYTE TODAY. An unbound session_id resolves to `peer`
# (member-registry.sh), and `peer` adds NO role-level denial here — the existing push/persist gates
# still apply exactly as before. So a fleet that has set no roles behaves identically to now; roles
# only ever SUBTRACT authority from the Peer baseline, never add friction to it.
#
# role_verdict <role> <tool_name> <is_write:0|1>
#   prints a deny REASON and returns 0  -> the gate must DENY (exit 2)
#   prints nothing and returns 1        -> no role-level objection (fall through to the act gates)
#
# `is_write` is the caller's best-effort "does this Bash command write?" (the persist-gate already
# computes exactly this for its own path — the role check REUSES that signal rather than re-deriving
# it, so there is one write-detector, not two).
role_verdict() {
  local role="$1" tool="$2" is_write="${3:-0}"
  case "$role" in
    observer)
      # The genuinely new safety primitive: read-only BY CONSTRUCTION. A task handed to an Observer
      # has a blast radius bounded before it starts. (Belt: the launch profile should also remove
      # these tools; this is the mid-flight dial + revocation path, §3.4.)
      case "$tool" in
        Edit|Write|MultiEdit|NotebookEdit)
          printf 'role=observer is read-only — %s denied. Revoke/raise the role in Conductor to write.\n' "$tool"
          return 0 ;;
      esac
      if [ "$tool" = "Bash" ] && [ "$is_write" = "1" ]; then
        printf 'role=observer is read-only — this Bash command writes; denied. Raise the role to edit.\n'
        return 0
      fi
      ;;
    service)
      # A service session serves its one job; it does not push and does not reserve unrelated
      # resources. Its write-scope (scratch/output only) is enforced by construction + the OS floor,
      # not fully here (that needs the scratch-dir context) — so at the referee we only assert the
      # part that is unambiguous from the tool alone: no push. Persistent-location writes and pushes
      # are ALREADY gated for everyone; this is a placeholder for the service-specific narrowing that
      # lands with the scratch-dir wiring. TODO(impl): scope writes to the service's output dir.
      : ;;
    peer|trusted|"")
      : ;;   # Peer baseline (and the unbound default) — no role-level denial; act gates still apply.
    *)
      : ;;   # Unknown role -> treat as Peer (safe: the act gates still apply). Warn at the call site.
  esac
  return 1
}
