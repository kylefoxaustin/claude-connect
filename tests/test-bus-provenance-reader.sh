#!/usr/bin/env bash
# "I didn't type that /msg-check" — the reader v2.30 never shipped.
#
# v2.30 built the attestation ledger and wired only the WRITER. Conductor faithfully recorded
# every keystroke it injected — 40 entries — and no session was ever told. So a /msg-check from
# Conductor and one from Kyle arrived byte-identical, and on the night of 2026-08-24 95emulator
# triaged the bus SIX times on an instruction Kyle never gave, then reported back to him as
# though he had asked. Nothing broke. Every one of those turns rested on a false premise about
# who was speaking, and a method error that produces good output is invisible by construction.
#
# ⭐ THE ASYMMETRY IS THE POINT: an unattested INJECTABLE prompt is "unknown", never "Kyle".
# The attack on a ledger is OMISSION, so if absence-of-entry meant "the human", suppressing the
# file would BUY an injector Kyle's authority. Absence means "I cannot tell", and omission buys
# nothing.
#
# And it stays quiet for ordinary prompts. Saying "source unverified" under every sentence Kyle
# types is noise, and noise is how a real signal gets discounted.
set -uo pipefail

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
SD="$SB/home/.claude/bus-state"
mkdir -p "$SD" "$SB/claude-connect"
printf 'other:claude-connect\n' > "$SD/active-tags"
printf '## 2026-08-25 08:00:00 [other:x]\n\nfiller.\n' > "$SB/messages.md"
printf '2026-08-25 09:00:00\n' > "$SD/other:claude-connect.last-seen"   # nothing unread: isolate provenance

NOW="$(date +%s)"
entry() {   # <tag> <text> <actor> <age_seconds>
  python3 -c "
import json, sys
print(json.dumps({'ts': $NOW - int(sys.argv[4]), 'target_pid': 4242, 'target_tag': sys.argv[1],
                  'text': sys.argv[2], 'why': '3 unread addressed to it',
                  'source': 'conductor:_inject_text', 'actor': sys.argv[3], 'consumed': False}))
" "$1" "$2" "$3" "$4" > "$SD/injections.jsonl"
}

ctx() {   # <prompt>
  printf '{"prompt":"%s","session_id":"s1"}' "$1" \
    | (cd "$SB/claude-connect" && env HOME="$SB/home" BUS_STATE_DIR="$SD" \
        BUS_FILE="$SB/messages.md" bash "$BUS" prompt-check 2>/dev/null) \
    | python3 -c 'import json,sys
try: print(json.load(sys.stdin)["hookSpecificOutput"]["additionalContext"])
except Exception: print("")'
}

# 1. attested by Conductor -> say so, and say he is not waiting
entry '[other:claude-connect]' '/msg-check' 'conductor' 90
out="$(ctx /msg-check)"
case "$out" in
  *"INJECTED BY CONDUCTOR"*) ok "an attested injection is named as one" ;;
  *) bad "attested injection not reported: ${out:0:90}" ;;
esac
case "$out" in
  *"not waiting"*) ok "and the session is told not to answer a human who isn't there" ;;
  *) bad "no behavioural guidance" ;;
esac
case "$out" in
  *"3 unread addressed to it"*) ok "the recorded REASON is surfaced, not just the fact" ;;
  *) bad "reason missing — 'something injected this' is much less useful than why" ;;
esac

# 2. CONSUME-ONCE. A queue, not a time window: injection->arrival was measured at 6-13 MINUTES,
#    so the entry must be matched and retired, never matched again.
out2="$(ctx /msg-check)"
case "$out2" in
  *"INJECTED BY CONDUCTOR"*) bad "the same attestation fired twice — it was not consumed" ;;
  *"NO attestation"*)        ok "consumed once, and the repeat degrades to unknown" ;;
  *)                         bad "unexpected second read: ${out2:0:90}" ;;
esac

# 3. THE ASYMMETRY: unattested injectable = unknown, explicitly not Kyle
: > "$SD/injections.jsonl"
out3="$(ctx /msg-check)"
case "$out3" in
  *"NO attestation"*) ok "an unattested /msg-check is reported as unknown" ;;
  *) bad "an unattested injectable prompt said nothing: ${out3:0:90}" ;;
esac
case "$out3" in
  *"does not guess"*) ok "and it refuses to guess rather than defaulting to the human" ;;
  *) bad "no explicit refusal to guess" ;;
esac

# 4. QUIET for ordinary prompts — the anti-noise control
[ -z "$(ctx 'okay do the thing')" ] && ok "silent on a prompt Kyle actually typed" \
  || bad "annotated an ordinary prompt — this will train sessions to ignore the line"

# 5. Kyle driving Conductor is NOT the same as Conductor deciding, and the GUIDANCE differs.
#    The first version said "he is not waiting" for every injected turn — right for an unread-mail
#    nudge, actively wrong for a push verdict he had just tapped Approve on. Advice that is right
#    for the common case and wrong for the consequential one is how a line gets ignored.
for actor in 'human:192.168.1.5' 'kyle:192.168.1.5'; do
  entry '[other:claude-connect]' '/msg-check' "$actor" 30
  out5="$(ctx /msg-check)"
  case "$out5" in
    *"KYLE'S OWN DECISION"*) ok "actor=$actor -> attributed to the human" ;;
    *) bad "actor=$actor was reported as an autonomous injection" ;;
  esac
  case "$out5" in
    *"not waiting"*) bad "actor=$actor still told the session nobody is waiting" ;;
    *"report back"*) ok "and told to report back, because he IS waiting" ;;
    *)               bad "no guidance for a human-driven injection" ;;
  esac
done

# 5b. a Conductor-delivered VERDICT is neither of the two extremes: act on it, keep it short.
entry '[other:claude-connect]' '/msg-check' 'conductor' 20
python3 - "$SD/injections.jsonl" <<'FIX'
import json, sys
p = sys.argv[1]
e = json.loads(open(p).read().strip())
e["why"] = "push verdict for claude-connect"
open(p, "w").write(json.dumps(e) + "\n")
FIX
out5b="$(ctx /msg-check)"
case "$out5b" in
  *"reports a decision a human made"*) ok "a delivered verdict is not read as an autonomous nudge" ;;
  *) bad "a push verdict got the generic 'he is not waiting' guidance: ${out5b:0:100}" ;;
esac

# 6. an attestation for a DIFFERENT session must never be claimed by this one
entry '[other:someone-else]' '/msg-check' 'conductor' 60
case "$(ctx /msg-check)" in
  *"INJECTED BY CONDUCTOR"*) bad "claimed another session's attestation" ;;
  *"NO attestation"*)        ok "another session's attestation is not claimed" ;;
  *)                         bad "unexpected: cross-session match" ;;
esac

# 7. AGE. Two horizons, and conflating them mis-attributed a real prompt: 6h is the GC horizon,
#    not a plausible arrival delay (measured worst case: 6-13 MINUTES). A 4.9h-old entry claimed a
#    just-arrived push verdict on 2026-08-26 and reported "attested 17692s before it arrived".
for age in 25000 17692; do
  entry '[other:claude-connect]' '/msg-check' 'conductor' "$age"
  case "$(ctx /msg-check)" in
    *"NO attestation"*) ok "a ${age}s-old entry does not claim this prompt" ;;
    *)                  bad "a ${age}s-old entry claimed a just-arrived prompt" ;;
  esac
done
# and the control: something that plausibly just arrived MUST still match
entry '[other:claude-connect]' '/msg-check' 'conductor' 300
case "$(ctx /msg-check)" in
  *"INJECTED BY CONDUCTOR"*) ok "a 5-minute-old entry still matches (the window is not too tight)" ;;
  *)                         bad "tightening the window broke the normal case" ;;
esac

# ---------------------------------------------------------------------------------------
# 8. THE DOORBELL. Conductor types "push approved: <repo>" instead of 136 characters of prose,
#    and the hook expands it FROM THE GRANT FILE. Two wins, and the second is the bigger one:
#    fewer characters to mangle under a contended display, and an explanation that CANNOT be
#    stale — the old sentence was composed at queue time and typed minutes later, so 95emulator
#    received four notices saying "approved" for a repo with nothing pending.
# ---------------------------------------------------------------------------------------
mkdir -p "$SB/coord/push-tokens"
export COORD_STATE_DIR="$SB/coord"
: > "$SD/injections.jsonl"

printf 'expires=%s\nrepo_name=sgm-bench\nsha=abc123\n' "$(( $(date +%s) + 82800 ))" \
  > "$SB/coord/push-tokens/k"
out8="$(ctx 'push approved: sgm-bench')"
case "$out8" in
  *"PUSH APPROVED"*) ok "a doorbell with an armed grant expands to the real approval" ;;
  *) bad "doorbell not expanded: ${out8:0:110}" ;;
esac
case "$out8" in
  *"h left"*) ok "and reports the grant's OWN remaining time, read just now" ;;
  *)          bad "no TTL from the grant file — the expansion is not from ground truth" ;;
esac

# ⭐ The case the old prose got wrong, four times in one night.
rm -f "$SB/coord/push-tokens/k"
out8b="$(ctx 'push approved: sgm-bench')"
case "$out8b" in
  *"NO ARMED GRANT"*) ok "⭐ a doorbell with NO grant says so instead of claiming approval" ;;
  *"PUSH APPROVED"*)  bad "claimed an approval that no longer exists — the 2026-08-30 bug" ;;
  *)                  bad "unexpected: ${out8b:0:110}" ;;
esac
case "$out8b" in
  *"Do not re-push"*) ok "and tells the session not to act on it" ;;
  *)                  bad "no guidance on a stale doorbell" ;;
esac

echo "── bus-provenance-reader: $pass passed, $fail failed"
[ "$fail" = 0 ]
