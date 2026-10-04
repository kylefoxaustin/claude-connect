#!/usr/bin/env bash
# PostToolUse(Bash) — give back an approval the push gate consumed for a push that
# NEVER REACHED THE REMOTE.
#
# WHY THIS EXISTS. push-gate.sh consumes the token at the PreToolUse layer, before git
# runs. If a separate pre-push hook then vetoes — a corpus gate, a lint gate, anything
# under core.hooksPath — nothing is pushed and Kyle's tap is gone. qualcomm hit this twice
# in two days (2026-10-02 commit 68ff6e3, 2026-10-03 commit 87c28e1) and each bounce cost
# an extra tap. v2.41 already established the principle for a REMOTE rejection:
#   "the rejection is predictable: refuse WITHOUT consuming"
# and wired it only to the remote-sha path. A local hook veto is the same event.
#
# ⭐ THE CONSUME-POINT DOES NOT MOVE. The token is still deleted the instant the gate
# allows, so nothing concurrent can reuse it and the one-push-per-approval property is
# untouched. This only ever restores an approval Kyle really granted, that was consumed
# moments ago, for a commit this script has CONFIRMED is not on the remote.
#
# ⭐ IT ASKS GIT, NOT THE HARNESS. Nothing in this tree reads a hook payload's exit status
# and the field name is unverified here, so this does not depend on one. A successful push
# updates the local remote-tracking ref; a vetoed push does not. That ref is ground truth,
# needs no network, and is the project's own rule: verify the outcome, not the intention.
#
# ⚠️ ONE STEP IS UNVERIFIED ON SILICON, and says so here rather than in a commit message.
# The claim "a pre-push veto leaves the remote-tracking ref unmoved" is SOURCED from git's
# documented behaviour (the ref is updated only after the remote accepts the update), not
# MEASURED — testing it requires a real `git push`, which this repo's own gate correctly
# blocks, and evading the gate to test it is the one thing worth less than the test. If the
# assumption is ever wrong the failure is a REFUSAL to restore, never a spurious grant:
# every branch below defaults to doing nothing.
#
# FAILS SAFE EVERYWHERE. If it cannot tell whether the push landed, it leaves the record
# alone and the approval stays spent — exactly today's behaviour. It can lose a tap. It can
# never create one.
set -uo pipefail

COORD="${COORD_STATE_DIR:-$HOME/.claude/bus-state/coord}"
TOKENS="$COORD/push-tokens"
SPENT="$COORD/push-spent"
WINDOW="${PUSH_SPENT_WINDOW:-600}"

# ---- THE PREFILTER IS THE CHECK ITSELF -------------------------------------------------
# No payload parsing and no content prefilter, deliberately. push-gate.sh's own history
# has two bugs where "a prefilter that could disagree with the real check" let a gated
# write through, and a prefilter that misses HERE silently costs a tap. `push-spent/` is
# empty except for the ~WINDOW seconds after a push attempt, so its emptiness is both the
# cheap path and the real condition — it cannot drift from itself.
[ -d "$SPENT" ] || exit 0
# NOTE: do not touch `set -f` here. An earlier version disabled globbing after this
# emptiness probe, which left the real loop below iterating the literal string
# "$SPENT/*" — so the hook ran, exited 0, and restored nothing. Every refusal test
# still passed, because a hook that does nothing refuses everything.
_any=("$SPENT"/*)
[ -e "${_any[0]:-}" ] || exit 0

now="$(date +%s)"

for rec in "$SPENT"/*; do
  [ -f "$rec" ] || continue
  # Read the record's OWN recorded identity. Re-deriving the repo/key here would be a
  # second copy of push-gate.sh's resolution logic, and two copies of one predicate is
  # how the fleet's `comm == "claude"` bug outlived its own fix by two weeks.
  spent_epoch=""; spent_sha=""; spent_pushdir=""; spent_key=""
  while IFS='=' read -r k v; do
    case "$k" in
      spent_epoch)   spent_epoch="$v" ;;
      spent_sha)     spent_sha="$v" ;;
      spent_pushdir) spent_pushdir="$v" ;;
      spent_key)     spent_key="$v" ;;
    esac
  done < "$rec"

  # Past the window: this is wreckage, not a decision. Drop it rather than restore on
  # stale evidence — an approval resurrected minutes later is one Kyle has stopped
  # expecting, and a grant that reappears unprompted is worse than one that lapsed.
  case "$spent_epoch" in
    ''|*[!0-9]*) rm -f "$rec" 2>/dev/null || true; continue ;;
  esac
  if [ $(( now - spent_epoch )) -gt "$WINDOW" ]; then
    rm -f "$rec" 2>/dev/null || true; continue
  fi

  # Need both to say anything at all.
  [ -n "$spent_sha" ] && [ -n "$spent_pushdir" ] && [ -d "$spent_pushdir" ] || continue
  [ -n "$spent_key" ] || continue

  # GROUND TRUTH: is the approved commit on the remote now? The remote-tracking ref is
  # updated locally only by a push the remote accepted.
  up="$(git -C "$spent_pushdir" rev-parse --verify --quiet '@{u}' 2>/dev/null || true)"
  if [ -z "$up" ]; then
    # No upstream resolvable (detached, explicit refspec to a non-tracking branch, a
    # fresh branch). We cannot tell, so we do not act. The record ages out and the
    # approval stays spent — today's behaviour, not a new failure.
    continue
  fi
  if git -C "$spent_pushdir" merge-base --is-ancestor "$spent_sha" "$up" 2>/dev/null; then
    rm -f "$rec" 2>/dev/null || true      # it LANDED — the approval was correctly used
    continue
  fi

  # It did not land. Give the approval back — but never over a live one: if a token for
  # this key already exists, Kyle has since granted a fresh approval and overwriting it
  # with an older record would move the sha-pin backwards under him.
  if [ -e "$TOKENS/$spent_key" ]; then
    rm -f "$rec" 2>/dev/null || true
    continue
  fi
  mkdir -p "$TOKENS" 2>/dev/null || true
  if grep -v '^spent_' "$rec" > "$TOKENS/$spent_key" 2>/dev/null; then
    rm -f "$rec" 2>/dev/null || true
    printf '%s\n' \
      "↩️  PUSH APPROVAL RESTORED for '$spent_key' — that push never reached the remote" \
      "   (a pre-push hook rejected it), so Kyle's approval was NOT spent. Fix what the" \
      "   hook objected to, then re-run the SAME push. Still one push, still his tap." >&2
  else
    rm -f "$TOKENS/$spent_key" 2>/dev/null || true   # never leave a half-written token
  fi
done
exit 0
