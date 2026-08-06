#!/usr/bin/env bash
# Wind-down ack — the silent-failure bug, and the dodge it drove the fleet into.
#
# THE BUG (band, 91emulator, mcxn947qemu, imx95-isp — found by living it, 2026-08-05):
#   `unpushed="$(git log --oneline '@{u}..HEAD' | grep -c .)"` prints 0 and EXITS 1 when there is
#   nothing unpushed. With `set -e` that killed _winddown_ack BEFORE it wrote the .done — no
#   output, exit 1, no record. And it SELECTED FOR THE CLEANEST SESSIONS: anything with unpushed
#   commits gave grep a line, exited 0, and acked fine. The tidier you were, the more likely you
#   silently failed to ack.
#
# THE TRAP THIS FILE EXISTS TO AVOID: `set -e` is SUPPRESSED inside a function invoked in a
# `&&`/`||` list or an `if` condition. A test that calls the ack as `ack && echo ok` passes
# against the broken code. bus.sh dispatches from a `case`, where set -e applies. So every check
# here runs the REAL script through its REAL dispatch path. (Same class as the v2.36 pid-join
# bug: a unit test green in a tool-call context while the installed hook failed.)
#
# Run: bash tests/test-winddown-ack.sh
set -u

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()   { printf '  ✅ %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '  ❌ %s\n' "$1"; fail=$((fail+1)); }

ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

export HOME="$ROOT/home"
export BUS_PROJECTS_ROOT="$ROOT/projects"
mkdir -p "$HOME/.claude/bus-state" "$BUS_PROJECTS_ROOT"
export BUS_FILE="$ROOT/messages.md"; : > "$BUS_FILE"
WD="$HOME/.claude/bus-state/coord/wind-down"

# A project with a remote, fully "pushed" and clean — the exact shape that tripped the bug.
# NOTE: we never run `git push`. The remote-tracking ref is written directly with update-ref,
# which produces the identical state for `@{u}` and `--not --remotes` — and keeps this test out
# of the push gate (a real `git push` in a Bash call is gated, correctly).
mk_clean_repo() {
  # NOTE: separate `local` statements. A single `local name="$1" d=".../$name"` expands ALL its
  # words BEFORE assigning any, so $name there is the OUTER (unset) one — an error under `set -u`.
  local name="$1"
  local d="$BUS_PROJECTS_ROOT/$name"
  mkdir -p "$d"
  git init -q "$d" >/dev/null 2>&1
  git -C "$d" symbolic-ref HEAD refs/heads/main
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  echo hello > "$d/f.txt"; git -C "$d" add -A; git -C "$d" commit -qm init
  git -C "$d" remote add origin "$ROOT/remotes/$name.git"      # need not exist; nothing contacts it
  git -C "$d" update-ref refs/remotes/origin/main HEAD          # "already on the remote"
  git -C "$d" config branch.main.remote origin
  git -C "$d" config branch.main.merge refs/heads/main          # sets @{u}
  printf '%s\n' "$d"
}

# Run the REAL script through its REAL `case` dispatch, AS A SESSION whose working directory is
# $sess_dir. The ack resolves the tree to verify from /proc/<claude_pid>/cwd, so we stand up a real
# background process in that directory and name it via the documented CLAUDE_PID_OVERRIDE seam —
# faking the cwd would test our idea of the mechanism instead of the mechanism.
#
# Captures output AND status from ONE invocation: running it twice would let the first call's side
# effects satisfy the second call's assertions, which is its own species of passing for the wrong
# reason.
ACK_OUT=""; ACK_ST=""
run_ack_as_session() {
  local sess_dir="$1"; local shell_dir="$2"; shift 2
  ( cd "$sess_dir" && exec sleep 60 ) & local sp=$!
  local i=0
  while [ ! -e "/proc/$sp/cwd" ] && [ $i -lt 50 ]; do i=$((i+1)); done
  ACK_OUT="$( ( cd "$shell_dir" && CLAUDE_PID_OVERRIDE="$sp" bash "$BUS" shutdown ack "$@" ) 2>&1 )" \
    && ACK_ST=0 || ACK_ST=$?
  kill "$sp" 2>/dev/null || true; wait "$sp" 2>/dev/null || true
}
# The ordinary case: the session's cwd and the shell's cwd are the same directory.
run_ack() { local d="$1"; shift; run_ack_as_session "$d" "$d" "$@"; }

donefile() { ls "$WD"/*.done 2>/dev/null | head -1; }
field()    { grep "^$2=" "$1" 2>/dev/null | cut -d= -f2-; }

echo "== a CLEAN, FULLY-PUSHED repo can ack (THE REGRESSION) =="
D="$(mk_clean_repo alpha)"
rm -rf "$WD"; mkdir -p "$WD"
run_ack "$D" 'alpha done, nothing outstanding'
[ "$ACK_ST" = "0" ] && ok "exit 0 (was exit 1, silently)" || bad "exit was $ACK_ST: $ACK_OUT"
f="$(donefile)"
[ -n "$f" ] && ok ".done record written" || bad "NO .done written — the silent failure"
case "$ACK_OUT" in *"Wound down"*) ok "said so out loud";; *) bad "no success line; got: $ACK_OUT";; esac

echo "== the record is CONFIRMED ON DISK before success is claimed =="
case "$ACK_OUT" in
  *"record confirmed on disk"*) ok "reports its OUTCOME, not its intention";;
  *) bad "no read-back confirmation in: $ACK_OUT";;
esac

echo "== zero unpushed is reported as zero, not as a crash =="
[ "$(field "$f" unpushed)" = "0" ] && ok "unpushed=0 recorded" || bad "unpushed=$(field "$f" unpushed)"

echo "== a repo with UNPUSHED commits still acks, and counts them =="
D2="$(mk_clean_repo beta)"
echo more >> "$D2/f.txt"; git -C "$D2" commit -qam second
rm -rf "$WD"; mkdir -p "$WD"
run_ack "$D2" 'beta done, one unpushed'
[ "$ACK_ST" = "0" ] && ok "exit 0" || bad "exit was $ACK_ST: $ACK_OUT"
[ "$(field "$(donefile)" unpushed)" = "1" ] && ok "counted the unpushed commit" \
  || bad "wrong count: $(field "$(donefile)" unpushed)"

echo "== #7: a branch with NO UPSTREAM is counted (was invisible) =="
D3="$(mk_clean_repo gamma)"
git -C "$D3" checkout -q -b v0.2                  # no upstream, never pushed
echo feature >> "$D3/f.txt"; git -C "$D3" commit -qam 'v0.2 work'
git -C "$D3" checkout -q main                     # ack from the clean, fully-pushed branch
rm -rf "$WD"; mkdir -p "$WD"
run_ack "$D3" 'gamma, but v0.2 is unpushed'
[ "$ACK_ST" = "0" ] && ok "exit 0 from the clean branch" || bad "exit was $ACK_ST: $ACK_OUT"
n="$(field "$(donefile)" unpushed)"
[ "${n:-0}" -ge 1 ] && ok "saw the upstream-less branch (unpushed=$n)" \
                    || bad "MISSED v0.2 — reported unpushed=$n (the drone-sizer hole)"

echo "== UNCOMMITTED tracked work still BLOCKS the ack =="
D4="$(mk_clean_repo delta)"
echo dirty >> "$D4/f.txt"                          # modified, not committed
rm -rf "$WD"; mkdir -p "$WD"
run_ack "$D4" 'delta'
[ "$ACK_ST" != "0" ] && ok "refused (exit $ACK_ST)" || bad "accepted a dirty tree!"
[ -z "$(donefile)" ] && ok "no .done written" || bad "wrote a .done for a dirty tree"
case "$ACK_OUT" in *UNCOMMITTED*) ok "explained why";; *) bad "no explanation: $ACK_OUT";; esac

echo "== untracked scratch does NOT block (c0cff35 behaviour preserved) =="
D5="$(mk_clean_repo epsilon)"
echo scratch > "$D5/NOTES.md"                      # untracked only
rm -rf "$WD"; mkdir -p "$WD"
run_ack "$D5" 'epsilon'
[ "$ACK_ST" = "0" ] && ok "exit 0 with untracked files" || bad "untracked blocked the ack: $ACK_OUT"
[ "$(field "$(donefile)" untracked)" = "1" ] && ok "recorded untracked=1" \
  || bad "untracked not recorded: $(field "$(donefile)" untracked)"

echo "== #5: the /tmp/<tag> DODGE IS CLOSED — a non-git shell dir no longer skips verification =="
# This is the workaround the whole fleet adopted for the set -e bug, and it "worked" by landing in
# a non-git directory, i.e. by skipping every git check. Sessions that acked that way carried
# `verified=tracked-tree-clean` having verified nothing. Now the tree is resolved from the
# SESSION's cwd, which a `cd` inside a tool call cannot move — so a dirty repo is still caught.
D6="$(mk_clean_repo zeta)"
echo dirty >> "$D6/f.txt"                          # uncommitted TRACKED work — must block
DODGE="$ROOT/tmpdodge/zeta"; mkdir -p "$DODGE"     # a non-git dir named after the tag
rm -rf "$WD"; mkdir -p "$WD"
run_ack_as_session "$D6" "$DODGE" 'zeta — acking from /tmp to dodge the check'
[ "$ACK_ST" != "0" ] && ok "refused despite the non-git shell dir (exit $ACK_ST)" \
                     || bad "DODGE STILL WORKS — acked a dirty repo from a non-git dir"
[ -z "$(donefile)" ] && ok "no .done written" || bad "wrote a .done for a dodged dirty tree"
case "$ACK_OUT" in *UNCOMMITTED*) ok "named the real repo's problem";; *) bad "no explanation: $ACK_OUT";; esac

echo "== a clean session acking from elsewhere still SUCCEEDS (the dodge fix must not over-block) =="
D7="$(mk_clean_repo eta)"
ELSEWHERE="$ROOT/tmpdodge/eta"; mkdir -p "$ELSEWHERE"
rm -rf "$WD"; mkdir -p "$WD"
run_ack_as_session "$D7" "$ELSEWHERE" 'eta done'
[ "$ACK_ST" = "0" ] && ok "exit 0 — verification followed the session, not the shell" \
                    || bad "over-blocked a genuinely clean session: $ACK_OUT"

echo "== no claude ancestor (Kyle in a plain terminal) falls back to \$CWD =="
D8="$(mk_clean_repo theta)"
rm -rf "$WD"; mkdir -p "$WD"
ACK_OUT="$( ( cd "$D8" && CLAUDE_PID_OVERRIDE=999999 bash "$BUS" shutdown ack 'theta by hand' ) 2>&1 )" \
  && ACK_ST=0 || ACK_ST=$?
[ "$ACK_ST" = "0" ] && ok "exit 0 using the shell's cwd" || bad "broke the human path: $ACK_OUT"
[ -n "$(donefile)" ] && ok ".done written" || bad "no .done on the fallback path"

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
