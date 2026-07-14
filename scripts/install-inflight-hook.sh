#!/usr/bin/env bash
# install-inflight-hook.sh — install the tool-inflight guard hook into the LIVE fleet.
#
# RUN THIS FROM A PLAIN TERMINAL, not through a Claude session. It writes ~/.claude/bin and
# ~/.claude/settings.json, which the persistence gate (correctly) blocks from inside a Claude
# session — a plain terminal is the documented escape hatch (docs/PERSISTENCE_GATE.md).
#
# Idempotent: re-running it re-copies the script and leaves settings.json unchanged if the
# hooks are already wired. Makes a timestamped backup of settings.json before touching it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BIN="$HOME/.claude/bin"
SETTINGS="$HOME/.claude/settings.json"
SRC="$REPO/bus/tool-inflight.sh"

[ -f "$SRC" ] || { echo "missing $SRC"; exit 1; }

echo "1. copying hook -> $BIN/tool-inflight.sh"
mkdir -p "$BIN"
install -m 0755 "$SRC" "$BIN/tool-inflight.sh"

echo "2. wiring settings.json hooks (idempotent)"
[ -f "$SETTINGS" ] || { echo "no $SETTINGS — is Claude Code set up?"; exit 1; }
cp -p "$SETTINGS" "$SETTINGS.bak-$(date +%Y%m%d-%H%M%S)"

python3 - "$SETTINGS" "$BIN/tool-inflight.sh" <<'PY'
import json, sys

settings_path, hook = sys.argv[1], sys.argv[2]
with open(settings_path) as fh:
    s = json.load(fh)

hooks = s.setdefault("hooks", {})
MATCHER = "Bash|Edit|Write|MultiEdit|NotebookEdit"
changed = False

def has(section, cmd_contains):
    for entry in hooks.get(section, []):
        for h in entry.get("hooks", []):
            if hook in (h.get("command") or "") and cmd_contains in (h.get("command") or ""):
                return True
    return False

# PreToolUse capture
if not has("PreToolUse", "tool-inflight.sh"):
    hooks.setdefault("PreToolUse", []).append({
        "matcher": MATCHER,
        "hooks": [{"type": "command", "command": f"{hook} capture", "timeout": 5}],
    })
    changed = True
    print("   + PreToolUse capture added")
else:
    print("   = PreToolUse capture already present")

# PostToolUse resolve
if not has("PostToolUse", "tool-inflight.sh"):
    hooks.setdefault("PostToolUse", []).append({
        "matcher": MATCHER,
        "hooks": [{"type": "command", "command": f"{hook} resolve", "timeout": 5}],
    })
    changed = True
    print("   + PostToolUse resolve added")
else:
    print("   = PostToolUse resolve already present")

if changed:
    tmp = settings_path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(s, fh, indent=2)
        fh.write("\n")
    import os
    os.replace(tmp, settings_path)
    print("   settings.json updated")
else:
    print("   settings.json unchanged")
PY

echo
echo "Done. The hook is live for NEW tool calls immediately (hooks are read per-call)."
echo "Then restart Conductor so it loads the guard code:  (in the app) quit + 'make native',"
echo "or restart the running app however you launched it."
