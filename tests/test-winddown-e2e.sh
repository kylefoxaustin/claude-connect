#!/usr/bin/env bash
# Wind-down END-TO-END rehearsal — the whole protocol against the real script, in a jail.
#
# The unit checks in test-winddown-ack.sh cover one function. This drives the sequence Kyle
# actually performs: begin -> (sessions ack, in the states a real fleet is in) -> status ->
# the operator reads who is closable. It exists because the 2026-08-05 shakedown failed at the
# JOINS, not inside any one function: the ack died silently, so `status` under-counted, so the
# fleet looked un-acked, so Kyle chased ~25 sessions by hand.
#
# Everything runs against a scratch $HOME. Nothing touches the live bus or the real fleet.
#
# Run: bash tests/test-winddown-e2e.sh
set -u

BUS="$(cd "$(dirname "$0")/.." && pwd)/bus/bus.sh"
pass=0; fail=0
ok()  { printf '  ✅ %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '  ❌ %s\n' "$1"; fail=$((fail+1)); }

ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT
export HOME="$ROOT/home"
export BUS_PROJECTS_ROOT="$ROOT/projects"
export BUS_FILE="$ROOT/messages.md"
mkdir -p "$HOME/.claude/bus-state" "$BUS_PROJECTS_ROOT"; : > "$BUS_FILE"
WD="$HOME/.claude/bus-state/coord/wind-down"

mk_repo() {                     # <name> [dirty|unpushed|branch]
  local name="$1"; local kind="${2:-clean}"
  local d="$BUS_PROJECTS_ROOT/$name"
  mkdir -p "$d"; git init -q "$d" >/dev/null 2>&1
  git -C "$d" symbolic-ref HEAD refs/heads/main
  git -C "$d" config user.email t@t; git -C "$d" config user.name t
  echo hello > "$d/f.txt"; git -C "$d" add -A; git -C "$d" commit -qm init
  git -C "$d" remote add origin "$ROOT/remotes/$name.git"
  git -C "$d" update-ref refs/remotes/origin/main HEAD
  git -C "$d" config branch.main.remote origin
  git -C "$d" config branch.main.merge refs/heads/main
  case "$kind" in
    dirty)    echo uncommitted >> "$d/f.txt" ;;
    unpushed) echo more >> "$d/f.txt"; git -C "$d" commit -qam later ;;
    branch)   git -C "$d" checkout -q -b v0.2; echo feat >> "$d/f.txt"
              git -C "$d" commit -qam 'v0.2'; git -C "$d" checkout -q main ;;
  esac
  printf '%s\n' "$d"
}

# Run bus.sh AS a session living in $1 (the ack resolves the tree from /proc/<claude_pid>/cwd).
# A REAL ancestor named `claude`. The ack walks the actual process tree and (correctly) ignores
# CLAUDE_PID_OVERRIDE, so the only faithful way to test it is to BE a claude child. We copy bash
# to a file called `claude` so /proc/<pid>/comm reads "claude", start it with cwd=$sess_dir, and
# run the ack from inside it — exactly the shape of a real session, including a shell that has
# cd'd somewhere else.
FAKE_CLAUDE="$ROOT/bin/claude"
mkdir -p "$ROOT/bin"; cp "$(command -v bash)" "$FAKE_CLAUDE"

OUT=""; ST=""
# Run bus.sh as a session whose claude process lives in $1, with the shell in $2 (usually the
# same). The inner shell must be a real `bash` child (a subshell fork would keep comm="claude"),
# and `; exit $?` stops `bash -c` from EXEC'ing away the fake claude entirely.
as_session_in() {
  local sess_dir="$1"; local shell_dir="$2"; shift 2
  local args=""; local a
  for a in "$@"; do args="$args \"$a\""; done
  OUT="$( cd "$sess_dir" && "$FAKE_CLAUDE" -c \
      "bash -c 'cd \"\$1\" && bash \"\$2\"$args' _ \"\$1\" \"\$2\"; exit \$?" \
      _ "$shell_dir" "$BUS" 2>&1 )" && ST=0 || ST=$?
}
as_session() { local d="$1"; shift; as_session_in "$d" "$d" "$@"; }

echo "=== ACT 1 — the operator calls the wind-down ==="
LEAD="$(mk_repo conductor clean)"
as_session "$LEAD" shutdown begin
[ "$ST" = "0" ] && ok "begin succeeded" || bad "begin failed: $OUT"
[ -f "$WD/active" ] && ok "wind-down marker written" || bad "no active marker"
grep -q "FLEET WIND-DOWN" "$BUS_FILE" && ok "protocol broadcast to the bus" || bad "nothing on the bus"

echo
echo "=== ACT 2 — a real fleet acks, in the four states a real fleet is in ==="

CLEAN="$(mk_repo alpha clean)"
as_session "$CLEAN" shutdown ack "alpha — everything shipped"
[ "$ST" = "0" ] && ok "CLEAN + fully pushed acked (the case that silently died)" || bad "clean failed: $OUT"

UNP="$(mk_repo beta unpushed)"
as_session "$UNP" shutdown ack "beta — one commit not pushed"
[ "$ST" = "0" ] && ok "unpushed-commits session acked" || bad "unpushed failed: $OUT"

BR="$(mk_repo gamma branch)"
as_session "$BR" shutdown ack "gamma — v0.2 branch parked"
[ "$ST" = "0" ] && ok "upstream-less-branch session acked" || bad "branch failed: $OUT"

DIRTY="$(mk_repo delta dirty)"
as_session "$DIRTY" shutdown ack "delta — trying to sneak out"
[ "$ST" != "0" ] && ok "DIRTY session correctly REFUSED" || bad "a dirty tree acked!"

echo
echo "=== ACT 3 — the dodge that the whole fleet adopted no longer works ==="
DODGE="$ROOT/tmp/delta"; mkdir -p "$DODGE"      # a non-git dir named after the tag
# The session still LIVES in the dirty repo; only its shell has moved. That is the whole dodge.
as_session_in "$DIRTY" "$DODGE" shutdown ack "delta via /tmp"
[ "$ST" != "0" ] && ok "dirty repo still refused (dodge closed)" || bad "DODGE WORKS — dirty acked"
[ ! -f "$WD/delta.done" ] && ok "no delta.done written" || bad "the dodge wrote a .done"

echo
echo "=== ACT 4 — status is the operator's view, and it must be complete ==="
as_session "$LEAD" shutdown status
n_done=$(ls "$WD"/*.done 2>/dev/null | wc -l)
[ "$n_done" = "3" ] && ok "exactly 3 .done records (alpha, beta, gamma)" || bad "expected 3, got $n_done"
for who in alpha beta gamma; do
  case "$OUT" in *"$who"*) ok "status lists $who";; *) bad "status MISSED $who";; esac
done
case "$OUT" in *delta*) bad "status lists delta, which never acked";; *) ok "delta correctly absent";; esac

echo
echo "=== ACT 5 — the records carry what reconstitution needs ==="
gamma_f="$WD/gamma.done"
[ -f "$gamma_f" ] && ok "gamma.done exists" || bad "gamma.done missing"
if [ -f "$gamma_f" ]; then
  n="$(grep '^unpushed=' "$gamma_f" | cut -d= -f2)"
  [ "${n:-0}" -ge 1 ] && ok "gamma's upstream-less v0.2 recorded (unpushed=$n)" \
                      || bad "v0.2 invisible — the drone-sizer hole is back"
  grep -q '^root=' "$gamma_f" && ok "records the repo root for reconstitution" || bad "no root= field"
  grep -q '^summary=' "$gamma_f" && ok "records the session's own summary" || bad "no summary"
fi
grep -c 'WOUND DOWN' "$BUS_FILE" >/dev/null && \
  [ "$(grep -c 'WOUND DOWN' "$BUS_FILE")" = "3" ] && ok "3 wound-down notices on the bus" \
  || bad "bus notices: $(grep -c 'WOUND DOWN' "$BUS_FILE")"

echo
echo "=== ACT 6 — clear ends it ==="
as_session "$LEAD" shutdown clear
[ ! -f "$WD/active" ] && ok "wind-down cleared" || bad "marker survived clear"
as_session "$LEAD" shutdown status
case "$OUT" in *"No fleet wind-down"*) ok "status reports no wind-down";; *) bad "status after clear: $OUT";; esac

echo
echo "  ${pass} passed, ${fail} failed"
[ "$fail" -eq 0 ]
