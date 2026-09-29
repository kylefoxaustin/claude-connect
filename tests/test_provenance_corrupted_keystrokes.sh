#!/usr/bin/env bash
# Regression test: the provenance reader must still attribute a Conductor injection when
# the KEYSTROKES ARRIVED CORRUPTED.
#
# 2026-09-29, found by qualcomm. Kyle really tapped Approve; Conductor attested the
# injection before typing (actor=human:<ip>, consumed=false) and typed the doorbell. A
# stuck-key repeat put a flood of "1" in front of it, so the prompt was
# "1111…push approved: qualcomm". The reader matched with `!=` — exact string equality —
# so it did not match, the entry stayed unconsumed, and a GENUINE injection presented to
# the session as UNATTESTED. qualcomm escalated it as possible approval-spoofing and
# refused to push, which is the correct behaviour and the reason nothing broke.
#
# The defect is that the reader exact-matched text delivered over a channel this project
# already documents as corrupting text (xdotool keysym repeats, the "waits for youuuuu"
# x130 class). The fix is a suffix match, which fails safe in the loosened direction: the
# worst case is telling a session that something Kyle really typed came from Conductor,
# i.e. erring toward DISTRUSTING an instruction, never toward trusting an unattested one.
#
# Cases 3 and 4 are the negative controls. Loosening a match on a security-adjacent ledger
# is only safe if it still refuses the things it should; a test that only shows the fix
# working is not evidence the fix is bounded.
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
T=$(mktemp -d); PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }

# lift the reader out of its heredoc so it can be driven directly
python3 - "$ROOT/bus/bus.sh" "$T/prov.py" <<'EXTRACT'
import re, sys
s = open(sys.argv[1], encoding="utf-8").read()
start = s.index("<<'PROVPY'"); b = s.index("\n", start) + 1
m = re.search(r'^PROVPY$', s[b:], re.M)
open(sys.argv[2], "w", encoding="utf-8").write(s[b:b + m.start()])
EXTRACT
[ -s "$T/prov.py" ] && ok "extracted the provenance reader" || { no "could not extract reader"; exit 1; }

fresh(){ python3 - "$T" <<'MK'
import json, sys, time
open(sys.argv[1] + "/injections.jsonl", "w").write(json.dumps({
    "ts": time.time() - 120, "target_pid": 1, "target_tag": "[other:qualcomm]",
    "text": "push approved: qualcomm", "why": "push verdict for qualcomm",
    "source": "conductor:_inject_text", "actor": "human:100.100.1.32",
    "consumed": False}) + "\n")
MK
}
run(){ BUS_PC_SD="$T" BUS_PC_TAG='[other:qualcomm]' \
  BUS_PC_PAYLOAD="$(python3 -c 'import json,sys;print(json.dumps({"prompt":sys.argv[1]}))' "$1")" \
  python3 "$T/prov.py" 2>&1; }
flood(){ python3 -c "print('1'*180 + 'push approved: qualcomm')"; }

# 1 — no regression on the clean path
fresh; out=$(run "push approved: qualcomm")
grep -q 'PROVENANCE' <<<"$out" && ok "exact text still attributed (no regression)" || no "clean path lost attribution"

# 2 — the bug itself
fresh; out=$(run "$(flood)")
grep -q 'PROVENANCE' <<<"$out" && ok "corrupted keystrokes ARE attributed" || no "corrupted prompt not attributed (the bug)"
grep -q 'KEYSTROKE CORRUPTION' <<<"$out" && ok "corruption is disclosed, not silently tolerated" || no "no corruption warning"
# the banner must echo the ATTESTED text, never the raw prompt: printing the flood would
# dump the corruption into the session's context and make the banner the bigger problem
[ "$(grep -c '111111' <<<"$out")" = 0 ] && ok "banner echoes attested text, not the flood" || no "banner replayed the flood"

# 3 — NEGATIVE CONTROL: an unrelated prompt must never be attributed
fresh; out=$(run "please push the qualcomm repo for me")
[ -z "$out" ] && ok "negative control: unrelated prompt stays SILENT" || no "falsely attributed an unrelated prompt"

# 4 — NEGATIVE CONTROL: right shape, wrong repo. The suffix match must not blur repos.
fresh; out=$(run "$(python3 -c "print('1'*50 + 'push approved: someotherrepo')")")
[ -z "$out" ] && ok "negative control: wrong repo stays SILENT" || no "suffix match blurred across repos"

# 5 — consumed exactly once, so the entry cannot attach itself to a later turn
fresh; run "$(flood)" >/dev/null
c=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]+'/injections.jsonl'))['consumed'])" "$T")
[ "$c" = "True" ] && ok "entry consumed on the degraded path too" || no "degraded match did not consume (got $c)"

rm -rf "$T"
printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
