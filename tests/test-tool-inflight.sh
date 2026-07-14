#!/usr/bin/env bash
# Drives the REAL bus/tool-inflight.sh — not a reimplementation. A hook tested only through a
# mock is a mirror (FAILURE_MODES Class IV): it passes while the shipped script is broken.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/bus/tool-inflight.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
export BUS_STATE_DIR="$TMP"
IDIR="$TMP/coord/inflight"

pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }

# A hook must NEVER be able to fail a session — every invocation exits 0.
run() { # <mode> <payload> ; echoes exit code
  printf '%s' "$2" | "$HOOK" "$1" >/dev/null 2>&1; echo $?
}

SID="11111111-2222-3333-4444-555555555555"
CWD="/home/kyle/proj"
BASH_PL="{\"session_id\":\"$SID\",\"cwd\":\"$CWD\",\"tool_name\":\"Bash\",\"transcript_path\":\"/t.jsonl\"}"

# 1. capture on Bash writes a marker keyed by session_id
[ "$(run capture "$BASH_PL")" = 0 ] || bad "capture must exit 0"
if [ -f "$IDIR/$SID" ]; then ok "capture(Bash) writes the marker"; else bad "capture(Bash) wrote nothing"; fi
grep -q "cwd=$CWD" "$IDIR/$SID" && grep -q "started_epoch=[0-9][0-9]*" "$IDIR/$SID" \
  && ok "marker has cwd + numeric started_epoch" || bad "marker content wrong"

# 2. resolve removes it (whoever/however the tool ended)
[ "$(run resolve "$BASH_PL")" = 0 ] || bad "resolve must exit 0"
[ ! -f "$IDIR/$SID" ] && ok "resolve removes the marker" || bad "resolve left the marker"

# 3. a non-mutating tool is NOT marked (would be a false 'busy' window)
READ_PL="{\"session_id\":\"$SID\",\"cwd\":\"$CWD\",\"tool_name\":\"Read\",\"transcript_path\":\"/t\"}"
run capture "$READ_PL" >/dev/null
[ ! -f "$IDIR/$SID" ] && ok "capture(Read) writes nothing" || bad "capture(Read) should not mark"

# 4. Edit/Write/MultiEdit/NotebookEdit ARE marked (they can raise the persist/permission gate)
for T in Edit Write MultiEdit NotebookEdit; do
  PL="{\"session_id\":\"tool-$T\",\"cwd\":\"$CWD\",\"tool_name\":\"$T\",\"transcript_path\":\"/t\"}"
  run capture "$PL" >/dev/null
  [ -f "$IDIR/tool-$T" ] && ok "capture($T) writes the marker" || bad "capture($T) wrote nothing"
done

# 5. garbage / empty / missing fields all exit 0 and write nothing new
before=$(ls "$IDIR" 2>/dev/null | wc -l)
[ "$(run capture 'not json at all')" = 0 ] && ok "garbage JSON exits 0" || bad "garbage JSON must exit 0"
[ "$(run capture '')" = 0 ] && ok "empty stdin exits 0" || bad "empty stdin must exit 0"
[ "$(run capture '{\"cwd\":\"/p\",\"tool_name\":\"Bash\"}')" = 0 ] && ok "missing session_id exits 0" || bad "must exit 0"
after=$(ls "$IDIR" 2>/dev/null | wc -l)
[ "$before" = "$after" ] && ok "no marker written on bad input" || bad "bad input wrote a marker"

# 6. a session id with path characters can't escape the directory
EVIL="{\"session_id\":\"../../etc/evil\",\"cwd\":\"/p\",\"tool_name\":\"Bash\",\"transcript_path\":\"/t\"}"
run capture "$EVIL" >/dev/null
[ ! -e "$TMP/etc/evil" ] && ok "path-y session_id is sanitized (no escape)" || bad "session_id escaped the dir"

echo "── tool-inflight: $pass passed, $fail failed"
[ "$fail" = 0 ]
