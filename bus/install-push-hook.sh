#!/usr/bin/env bash
# Arm the pre-push enforcement layer. Run this from a PLAIN TERMINAL (not through a Claude session)
# — it writes to ~/.claude/bin (persistence-gated) and sets a GLOBAL git config, both of which are
# consequential, outlive-the-session changes that are deliberately the human's to make.
#
#   Install:    bash bus/install-push-hook.sh
#   Uninstall:  bash bus/install-push-hook.sh --uninstall
#   Status:     bash bus/install-push-hook.sh --status
#
# WHAT IT DOES, and why each piece is safe:
#   1. Installs bus/git-hooks/pre-push -> ~/.claude/git-hooks/pre-push. This is the REAL enforcer:
#      it fires on every `git push` from every repo, regardless of how the push was invoked, closing
#      the scripted/aliased bypass in the PreToolUse gate.
#   2. Refreshes ~/.claude/bin/push-gate.sh (backing up the old one) so the tool-layer gate drops the
#      short-lived CLAIM the hook needs to not double-deny an already-approved direct push.
#   3. Sets `git config --global core.hooksPath ~/.claude/git-hooks` — the one line that ARMS it.
#      REFUSES to clobber a core.hooksPath you already set to something else (it would disable your
#      other global hooks); in that case it tells you to drop the pre-push file into your dir instead.
#      A repo that ships its OWN pre-push hook is preserved — the installed hook chains to it first.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_HOOK="$ROOT/bus/git-hooks/pre-push"
SRC_GATE="$ROOT/bus/push-gate.sh"
HOOKDIR="$HOME/.claude/git-hooks"
DEST_HOOK="$HOOKDIR/pre-push"
DEST_GATE="$HOME/.claude/bin/push-gate.sh"

green(){ printf '\033[32m%s\033[0m\n' "$1"; }
red(){ printf '\033[31m%s\033[0m\n' "$1"; }

status() {
  echo "── pre-push enforcement status ──"
  local hp; hp="$(git config --global --get core.hooksPath || true)"
  echo "core.hooksPath (global): ${hp:-<unset>}"
  [ -x "$DEST_HOOK" ] && green "hook installed:  $DEST_HOOK" || red "hook MISSING:    $DEST_HOOK"
  if [ "$hp" = "$HOOKDIR" ] && [ -x "$DEST_HOOK" ]; then green "ARMED ✓ — pushes are enforced by the pre-push hook."
  else red "NOT ARMED — scripted pushes are NOT yet gated."; fi
  grep -q 'push-claims' "$DEST_GATE" 2>/dev/null && green "tool-gate has the claim hand-off" || red "tool-gate is the OLD version (no claim hand-off)"
}

case "${1:-}" in
  --status) status; exit 0 ;;
  --uninstall)
    hp="$(git config --global --get core.hooksPath || true)"
    [ "$hp" = "$HOOKDIR" ] && git config --global --unset core.hooksPath && echo "unset core.hooksPath"
    rm -f "$DEST_HOOK" && echo "removed $DEST_HOOK"
    echo "Done. (push-gate.sh left in place — it is harmless without the hook.)"
    exit 0 ;;
  ""|--install) : ;;
  *) echo "usage: $0 [--install|--uninstall|--status]"; exit 2 ;;
esac

[ -f "$SRC_HOOK" ] || { red "missing $SRC_HOOK — run from the repo"; exit 1; }

# 1. hook
mkdir -p "$HOOKDIR"
install -m755 "$SRC_HOOK" "$DEST_HOOK"
green "installed hook -> $DEST_HOOK"

# 2. refresh the tool-layer gate (back up first)
if [ -f "$SRC_GATE" ]; then
  mkdir -p "$(dirname "$DEST_GATE")"
  if [ -f "$DEST_GATE" ] && ! cmp -s "$SRC_GATE" "$DEST_GATE"; then
    cp "$DEST_GATE" "$DEST_GATE.bak.$(date +%Y%m%d%H%M%S)"; echo "backed up existing push-gate.sh"
  fi
  if install -m755 "$SRC_GATE" "$DEST_GATE"; then
    green "refreshed tool-gate -> $DEST_GATE (claim hand-off)"
  else
    red "FAILED to install $DEST_GATE — fix the path and re-run"; exit 1
  fi
fi

# 3. arm core.hooksPath (refuse to clobber a different existing value)
CUR="$(git config --global --get core.hooksPath || true)"
if [ -z "$CUR" ]; then
  git config --global core.hooksPath "$HOOKDIR"
  green "armed: core.hooksPath -> $HOOKDIR"
elif [ "$CUR" = "$HOOKDIR" ]; then
  echo "core.hooksPath already points here — nothing to change."
else
  red "core.hooksPath is already set to: $CUR"
  echo "   NOT overwriting it (that would disable your other global hooks). To arm, either:"
  echo "     • copy the hook into your dir:  install -m755 '$SRC_HOOK' '$CUR/pre-push'  (chain if one exists), or"
  echo "     • point it here if you have no other global hooks:  git config --global core.hooksPath '$HOOKDIR'"
fi
echo
status
