#!/usr/bin/env bash
# ROTATION MUST NOT DESTROY A MESSAGE, and must not strand one either.
#
# The old rotation was `cp` then `cat >`. MEASURED, 16 concurrent writers with a rotation
# fired mid-stream: 20 messages lost per 9600 — copied to the archive, then truncated away,
# present in NEITHER file. The replacement never overwrites anything and measured 0 per
# 9600 with the writers left completely unlocked.
#
# ⚠️ WHY THERE IS NO WRITER LOCK, recorded because the obvious design is wrong twice over:
#   - `>>` is O_APPEND; a concurrent appender cannot lose another writer's bytes. The loss
#     was never an append problem, it was rotate truncating a path writers still held.
#   - An earlier attempt — `mv` plus a lock on the ROTATOR ONLY — measured WORSE (5 lost
#     per 1200), because a writer opening the path after the rename creates a fresh file
#     that the following `cat >` still truncates.
#   "Lock both sides reaches zero" was therefore not evidence that appends need locking;
#   it was evidence that excluding writers during a truncation window works. Removing the
#   truncation removes the need for the exclusion.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUS="${BUS_SH:-$ROOT/bus/bus.sh}"
PASS=0; FAIL=0
ok(){ printf '  ok   %s\n' "$1"; PASS=$((PASS+1)); }
no(){ printf '  FAIL %s\n' "$1"; FAIL=$((FAIL+1)); }
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
REAL_BUS="$HOME/Documents/claude-bus/messages.md"
REAL_BEFORE="$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)"

H="$T/home"; BD="$T/bus"; BF="$BD/messages.md"
mkdir -p "$H/.claude/bus-state" "$BD" "$T/s1" "$T/s2"
printf 'other:s1\nother:s2\n' > "$H/.claude/bus-state/active-tags"
: > "$BF"
snd(){ printf '%s\n' "$2" | (cd "$T/$1" && HOME="$H" BUS_FILE="$BF" bash "$BUS" send - >/dev/null 2>>"$T/err"); }
rot(){ (cd "$T/s1" && HOME="$H" BUS_FILE="$BF" bash "$BUS" rotate "$@" 2>>"$T/err"); }

# ── isolation first; this suite writes through the real send path ───────────────────────
snd s1 "to:s2 — isolation probe"
[ "$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)" = "$REAL_BEFORE" ] \
  && ok "isolated from the real bus" \
  || { no "THE REAL BUS GREW — aborting"; exit 1; }

# ── the basic contract ──────────────────────────────────────────────────────────────────
for i in 1 2 3 4 5; do snd s1 "to:s2 — pre-$i"; done
rot >/dev/null
arch="$(ls "$BD"/messages-*.md 2>/dev/null | head -1)"
[ -n "$arch" ] && ok "an archive was created" || no "no archive"
[ "$(grep -ac 'pre-' "$arch" 2>/dev/null)" = 5 ] && ok "all 5 pre-rotation messages are in the archive" \
  || no "archive holds $(grep -ac 'pre-' "$arch" 2>/dev/null) of 5"
[ "$(grep -ac 'pre-' "$BF")" = 0 ] && ok "the live log no longer holds them" || no "messages duplicated into the live log"
[ "$(grep -a '^## 20' "$BF" | head -1 | grep -c 'system')" = 1 ] \
  && ok "the rotation notice is the FIRST header in the new log" \
  || no "first header is not the [system] notice — the recovery trigger leans on this"

# ── ⚠️ THE #1 SILENT FAILURE: a crashed rotation must not strand messages ───────────────
# `.rot.tmp` matches neither the live path nor the `messages-*.md` glob, so a rotation
# killed between the rename and the archive leaves a month in a file that check, catchup,
# the gap recovery, Conductor and History are all blind to — while every signal reads
# healthy. The fixed (non-mktemp) name is what makes this recoverable.
printf '\n## 2026-10-08 09:00:00 [other:s1]\n\nto:s2 — stranded by a crash\n' > "$BD/.rot.tmp"
rot >/dev/null
[ "$(cat "$BD"/messages-*.md | grep -ac 'stranded by a crash')" = 1 ] \
  && ok "a crashed rotation's .rot.tmp is recovered on the next rotate" \
  || no "STRANDED: messages left in .rot.tmp, invisible to every reader"
[ ! -e "$BD/.rot.tmp" ] && ok ".rot.tmp is cleaned up after recovery" || no ".rot.tmp left behind"

# ── empty-bus guard still holds ─────────────────────────────────────────────────────────
: > "$BF"; rm -f "$BD/.rot.tmp"
rot 2>&1 | grep -qi 'empty' && ok "an empty bus is refused, not rotated into a junk archive" \
  || no "empty bus was rotated"

# ── THE MEASUREMENT: concurrent writers during a rotation lose nothing ──────────────────
: > "$BF"; rm -f "$BD"/messages-*.md "$BD/.rot.tmp"
for w in 1 2 3 4 5 6; do
  ( for i in $(seq 1 12); do
      printf '%s\n' "to:s2 — c$w-$i" | (cd "$T/s1" && HOME="$H" BUS_FILE="$BF" bash "$BUS" send - >/dev/null 2>&1)
    done ) &
done
sleep 0.4; rot >/dev/null 2>&1; wait
got="$(cat "$BD"/messages-*.md "$BF" 2>/dev/null | grep -ac 'to:s2 — c[0-9]')"
[ "$got" = 72 ] && ok "72/72 messages survive a rotation fired mid-stream (none destroyed)" \
  || no "only $got of 72 survived — rotation is still destroying messages"

# ── stamps remain strictly increasing across the rotation boundary ──────────────────────
python3 - "$BD" "$BF" <<'PY'
import re, sys, glob, os
hdr = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) \[')
ts = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "messages-*.md"))) + [sys.argv[2]]:
    ts += [m.group(1) for m in (hdr.match(l) for l in open(f, encoding="utf-8", errors="replace")) if m]
print(sum(1 for a, b in zip(ts, ts[1:]) if not b > a))
PY
[ "$(python3 - "$BD" "$BF" <<'PY'
import re, sys, glob, os
hdr = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})?) \[')
ts = []
for f in sorted(glob.glob(os.path.join(sys.argv[1], "messages-*.md"))) + [sys.argv[2]]:
    ts += [m.group(1) for m in (hdr.match(l) for l in open(f, encoding="utf-8", errors="replace")) if m]
print(sum(1 for a, b in zip(ts, ts[1:]) if not b > a))
PY
)" = 0 ] && ok "every stamp strictly increases across the rotation boundary" \
  || no "out-of-order stamps across the boundary"

[ "$(wc -c < "$REAL_BUS" 2>/dev/null || echo 0)" = "$REAL_BEFORE" ] \
  && ok "real bus still untouched at exit" || no "THE REAL BUS GREW DURING THIS TEST"

printf '\n  %d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
