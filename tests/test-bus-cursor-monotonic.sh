#!/usr/bin/env bash
# A read cursor may only ever move FORWARD, and a turn's pending advance is the FURTHEST
# point that turn reached — not the last one it happened to write.
#
# Both defects were found by a Fable adversarial pass on 2026-08-24 and observed live, while
# chasing what looked like a three-week frozen cursor. The freeze turned out to be nothing:
# image_gen's session was CLOSED (its transcript has 116 records on Jul 28, 3 on Aug 6 — all
# of them `/exit` — and nothing until Aug 24). No turns means no reads means no commits. But
# the hunt turned up two genuine defects on the way:
#
# 1. NON-MONOTONIC COMMIT. `_cursor_commit_delivered` wrote the pending timestamp into
#    `.last-seen` unconditionally, so a commit could move a watermark BACKWARDS and
#    re-deliver mail already marked read. Live: image_gen hand-repaired its cursor to
#    2026-08-23 21:32:06 while a record from earlier in the SAME turn (2026-08-02 14:03:23,
#    left behind because a later `check` found nothing new and exited before overwriting it)
#    was still pending. Marker matched, so the Stop hook committed the OLDER value over the
#    repair. That is the real cause of "my cursor keeps reverting" — which image_gen
#    reasonably but wrongly blamed on the timestamp regex.
#
# 2. LAST-WRITER-WINS ON `.delivered`. `check` and `catchup` share one slot per member, so a
#    smaller advance silently discarded a bigger one. Live: `catchup -n 300` advanced to
#    2026-08-23 21:32:06 and printed "Now current", then a `check` in the same turn wrote its
#    first-page newest over it. No mail is lost — at-least-once redelivery — but
#    catchup-then-check in one turn was a no-op and "Now current" was false by turn-end.
#
# ⭐ Note what the fixes do NOT do: neither one would have moved image_gen's cursor. A closed
# session has no turns. Fixing the two things you found while looking for a third is fine;
# claiming they explain the thing you were looking for is not.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
SD="$SB/home/.claude/bus-state"
mkdir -p "$SD" "$SB/claude-connect" "$SB/home/.claude/projects/p"
printf 'other:claude-connect\n' > "$SD/active-tags"
: > "$SD/two-phase"

SID="11111111-2222-3333-4444-555555555555"
TX="$SB/home/.claude/projects/p/$SID.jsonl"
MARK="prompt-under-test"
printf '{"type":"user","promptId":"%s","timestamp":"2026-08-24T12:00:00Z"}\n' "$MARK" > "$TX"

CUR="$SD/other:claude-connect.last-seen"
DEL="$SD/other:claude-connect.delivered"

stop_commit() {   # drive the REAL Stop handler with a real payload
  printf '{"session_id":"%s","transcript_path":"%s"}' "$SID" "$TX" \
    | (cd "$SB/claude-connect" && env HOME="$SB/home" BUS_STATE_DIR="$SD" \
        BUS_FILE="$SB/messages.md" bash "$BUS" stop-commit >/dev/null 2>&1)
}

: > "$SB/messages.md"

# ---------------------------------------------------------------------------------------
# 1. THE REGRESSION: a pending advance OLDER than the cursor must not be committed.
# ---------------------------------------------------------------------------------------
printf '2026-08-23 21:32:06\n' > "$CUR"
printf '2026-08-02 14:03:23\t%s\n' "$MARK" > "$DEL"
stop_commit
got="$(cat "$CUR")"
[ "$got" = "2026-08-23 21:32:06" ] \
  && ok "an older pending advance does not move the cursor backwards" \
  || bad "cursor went BACKWARDS to '$got' (was 2026-08-23 21:32:06)"
[ -f "$DEL" ] && bad "the stale record was left behind" || ok "the record is consumed either way"

# ---------------------------------------------------------------------------------------
# 2. THE CONTROL. Without this, "never moves backwards" is satisfied by never moving.
# ---------------------------------------------------------------------------------------
printf '2026-08-02 14:03:23\n' > "$CUR"
printf '2026-08-23 21:32:06\t%s\n' "$MARK" > "$DEL"
stop_commit
[ "$(cat "$CUR")" = "2026-08-23 21:32:06" ] \
  && ok "a newer pending advance still commits (the cursor does move)" \
  || bad "a legitimate forward commit did not land: $(cat "$CUR")"

# ---------------------------------------------------------------------------------------
# 3. Mixed precision. The bus carries both HH:MM and HH:MM:SS; the compare must order them.
# ---------------------------------------------------------------------------------------
printf '2026-08-23 16:12\n' > "$CUR"
printf '2026-08-23 16:12:30\t%s\n' "$MARK" > "$DEL"
stop_commit
[ "$(cat "$CUR")" = "2026-08-23 16:12:30" ] \
  && ok "seconds-precision beats the same minute (mixed dialect ordered correctly)" \
  || bad "mixed-precision compare is wrong: $(cat "$CUR")"

# ---------------------------------------------------------------------------------------
# 4. A record from a DIFFERENT turn is still discarded, not merged. The forward-only rule
#    must not accidentally resurrect a dead turn's emission.
# ---------------------------------------------------------------------------------------
printf '2026-08-02 14:03:23\n' > "$CUR"
printf '2026-08-23 21:32:06\tsome-other-turn\n' > "$DEL"
stop_commit
[ "$(cat "$CUR")" = "2026-08-02 14:03:23" ] \
  && ok "a dead turn's record is discarded, not committed" \
  || bad "committed a record belonging to a turn that never completed"

# ---------------------------------------------------------------------------------------
# 5. Defect 2, driven through the REAL `catchup` and `check`.
#
# ⚠️ The first version of this section reimplemented the merge rule inside the test and
#    asserted against its own copy. It passed on the unfixed tree — of course it did: it was
#    testing the test. A check that gets its logic from the thing it is checking is a mirror,
#    and mutation testing is blind to it by construction. So this drives bus.sh itself.
# ---------------------------------------------------------------------------------------
python3 - "$SB/messages.md" <<'MSGS'
import sys
open(sys.argv[1], "w").write("".join(
    f"## 2026-08-{1 + i // 10:02d} {10 + i % 10:02d}:00:0{i % 10} [other:sender{i % 3}]\n\n"
    f"to:claude-connect — message {i}.\n\n" for i in range(40)))
MSGS

busrun() { (cd "$SB/claude-connect" && env HOME="$SB/home" BUS_STATE_DIR="$SD" \
             BUS_FILE="$SB/messages.md" bash "$BUS" "$@" >/dev/null 2>&1); }

printf '2026-08-01 00:00:00\n' > "$CUR"; rm -f "$DEL"
busrun catchup -n 300
far="$(cut -f1 < "$DEL" 2>/dev/null)"
busrun check
after="$(cut -f1 < "$DEL" 2>/dev/null)"

[ -n "$far" ] && ok "catchup wrote a pending advance ($far)" \
              || bad "catchup wrote no .delivered record — the rest of this block proves nothing"
[ "$after" = "$far" ] \
  && ok "a check in the same turn does not walk catchup's advance back" \
  || bad "check overwrote catchup: $far -> $after (catchup's 'Now current' was false by turn-end)"

echo "── bus-cursor-monotonic: $pass passed, $fail failed"
[ "$fail" = 0 ]
