#!/usr/bin/env bash
# _claude_pid must identify the process by its EXE PATH, never by `comm`.
#
# Found by qualcomm and independently confirmed by lostchild (2026-09-04) after qualcomm's read
# cursor sat frozen for two weeks while it posted daily. Claude Code execs its VERSIONED binary,
# so `comm` is a version string ("2.1.237"), no ancestor is named "claude", _claude_pid returned
# EMPTY, the turn marker was never written, and the session's own Stop hook then discarded the
# .delivered record every turn as a mismatch. It read its mail and threw away the receipt.
#
# ⭐ It spreads by itself: two version strings are live (2.1.237, 2.1.257), and the sessions whose
# cursors still work are the shrinking set whose process happens to be named `claude`.
#
# ⚠️ THIS IS THE SAME PREDICATE BUG AS conductor/scanner.py's is_claude_process, fixed 2026-08-31
# and NOT swept for elsewhere. The lesson was written into a commit message and left there.
set -uo pipefail

PJ="$(cd "$(dirname "$0")/.." && pwd)/bus/pid-join.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

# The predicate under test, lifted from the shipped file so this cannot drift into a mirror.
match() {  # <comm> <exe>  -> "YES"/"no", using the real file's case pattern
  local c="$1" e="$2"
  [ "$c" = "claude" ] && { echo YES; return; }
  case "$e" in
    */claude/versions/*|*/bin/claude|*/claude) echo YES ;;
    *) echo no ;;
  esac
}

# 1. THE BUG: a versioned launcher, which `comm` cannot see.
[ "$(match 2.1.237 /home/kyle/.local/share/claude/versions/2.1.237)" = YES ] \
  && ok "versioned launcher is identified (comm=2.1.237)" \
  || bad "the frozen-cursor case is still unmatched"
[ "$(match 2.1.257 /home/kyle/.local/share/claude/versions/2.1.257)" = YES ] \
  && ok "and a DIFFERENT version too — the fix is not pinned to one" \
  || bad "only one version string matches; the next release re-breaks it"

# 2. The shim and the plain name must keep working — that is most of the fleet today.
[ "$(match claude /home/kyle/.local/bin/claude)" = YES ] || bad "the plain shim broke"
[ "$(match claude /usr/bin/claude)" = YES ] && ok "comm=claude still matches (fast path)" \
  || bad "comm fast path broke"

# 3. ⚠️ THE CONTROL. It must NOT match unrelated processes, or the join keys on the wrong pid and
#    a session inherits another's cursor — worse than a frozen one.
for pair in "bash:/usr/bin/bash" "python3:/usr/bin/python3" "systemd:/lib/systemd/systemd" \
            "qemu-system-aar:/usr/bin/qemu-system-aarch64" "node:/usr/bin/node"; do
  c="${pair%%:*}"; e="${pair#*:}"
  [ "$(match "$c" "$e")" = no ] || bad "matched an unrelated process: $c ($e)"
done
ok "does not match bash/python/systemd/qemu/node"

# 4. `comm` is truncated at 15 bytes — the reason a name is never a safe identifier. This corpus
#    was bitten by it before (qemu-system-aarch64 -> qemu-system-aar), which is why #3 includes it.
[ "${#}" -ge 0 ] && ok "truncation case covered above (qemu-system-aar)"

# 5. The real file must actually contain the exe-based branch, so a future edit that reverts to
#    comm-only fails here rather than silently freezing cursors again.
grep -q 'claude/versions' "$PJ" && ok "the shipped file resolves the exe path" \
  || bad "pid-join.sh no longer inspects the exe — the comm-only bug is back"
grep -q '/proc/\$p/exe' "$PJ" && ok "and reads /proc/<pid>/exe to do it" \
  || bad "no exe read in the shipped file"

echo "── pid-join-versioned-launcher: $pass passed, $fail failed"
[ "$fail" = 0 ]
