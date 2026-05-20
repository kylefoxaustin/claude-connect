#!/bin/bash
# Claude Bus — cross-session message exchange.
# Used by /msg-send, /msg-check, /msg-all slash commands and the
# SessionStart hook in ~/.claude/settings.json.
set -e

# Allow tests/scripts to point at a different file via env var.
# Defaults to the real bus when unset.
BUS_FILE="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
mkdir -p "$(dirname "$BUS_FILE")"
touch "$BUS_FILE"

# Auto-tag by working directory.
# Edit these case branches to map your own project dirs to short tags. Anything
# unmatched falls back to other:<dirname>. Keep the tags here in sync with the
# [bus.tags] table in Conductor's settings.toml so tiles show the same tag.
CWD="${PWD:-$(pwd)}"
case "$CWD" in
  */my-api|*/my-api/*)       TAG="api"    ;;
  */my-web|*/my-web/*)       TAG="web"    ;;
  */my-worker|*/my-worker/*) TAG="worker" ;;
  *)                         TAG="other:$(basename "$CWD")" ;;
esac

# Tags that participate in the AUTOMATIC hooks (SessionStart context injection +
# UserPromptSubmit nudges). This whitelist keeps the bus out of unrelated
# sessions; un-whitelisted tags can still use the slash commands manually.
BUS_WHITELIST="api|web|worker"

# True if the given tag is in BUS_WHITELIST (a `|`-separated list).
is_whitelisted() { case "|$BUS_WHITELIST|" in *"|$1|"*) return 0 ;; *) return 1 ;; esac; }

# Helper: after a read/send/session-start, mark the newest message as "seen"
# for THIS session tag so prompt-check doesn't re-flag it. No-op outside bus tags.
mark_seen_if_bus_tag() {
  is_whitelisted "$TAG" || return 0
  local STATE_DIR="$HOME/.claude/bus-state"
  mkdir -p "$STATE_DIR"
  local NEWEST
  NEWEST="$(grep -E '^## [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} \[' "$BUS_FILE" 2>/dev/null | tail -1 | awk '{print $2 " " $3}')"
  if [ -n "$NEWEST" ]; then
    echo "$NEWEST" > "$STATE_DIR/$TAG.last-seen"
    echo "0"       > "$STATE_DIR/$TAG.pending"
  fi
}

cmd="${1:-help}"
shift || true

case "$cmd" in
  send)
    if [ $# -eq 0 ]; then
      echo "ERROR: /msg-send requires a message" >&2
      exit 2
    fi
    TS="$(date '+%Y-%m-%d %H:%M')"
    {
      echo ""
      echo "## $TS [$TAG]"
      echo ""
      echo "$*"
    } >> "$BUS_FILE"
    echo "Sent message tagged [$TAG] at $TS."
    mark_seen_if_bus_tag
    ;;

  check)
    # Used by slash command and session-start hook.
    # Tail the recent log; caller decides what to do with it.
    echo "=== My session tag: [$TAG] ==="
    echo
    tail -80 "$BUS_FILE"
    mark_seen_if_bus_tag
    ;;

  all)
    wc -l "$BUS_FILE"
    echo
    cat "$BUS_FILE"
    ;;

  session-start)
    # Called by SessionStart hook. Emits JSON with the latest bus
    # contents as additionalContext so the new session knows what
    # the OTHER session has said while it was offline.
    #
    # Scoped: only fires for whitelisted tags so the bus doesn't
    # pollute unrelated Claude Code sessions.
    is_whitelisted "$TAG" || exit 0   # Anywhere else — no-op silently
    if [ ! -s "$BUS_FILE" ]; then
      mark_seen_if_bus_tag
      exit 0
    fi
    LATEST="$(tail -60 "$BUS_FILE")"
    ESCAPED="$(printf '%s' "$LATEST" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": "Claude Bus — recent messages from the cross-session log (your tag: [$TAG]). Read these before responding so you know what the OTHER session has been saying while you were offline:\n\n$(echo "$ESCAPED" | sed 's/^"//;s/"$//')"
  }
}
EOF
    mark_seen_if_bus_tag
    ;;

  prompt-check)
    # Called by UserPromptSubmit hook. Counts new messages on the bus
    # that arrived AFTER last-seen AND are not from this session's tag.
    # If count > 0, emits JSON with a one-line additionalContext nudge
    # so Claude knows pending messages exist (without injecting content).
    # Silent + no-op outside the bus whitelist.
    is_whitelisted "$TAG" || exit 0

    STATE_DIR="$HOME/.claude/bus-state"
    mkdir -p "$STATE_DIR"
    LAST_SEEN_FILE="$STATE_DIR/$TAG.last-seen"
    PENDING_FILE="$STATE_DIR/$TAG.pending"

    if [ -f "$LAST_SEEN_FILE" ]; then
      LAST_SEEN="$(cat "$LAST_SEEN_FILE")"
    else
      # First run for this tag — treat "now" as the baseline so we
      # don't flood the session with historical messages. The
      # SessionStart hook already injected recent context separately.
      LAST_SEEN="$(date '+%Y-%m-%d %H:%M')"
      echo "$LAST_SEEN" > "$LAST_SEEN_FILE"
    fi

    # Parse header lines: "## YYYY-MM-DD HH:MM [tag]"
    # Keep only those with timestamp > LAST_SEEN and tag != [$TAG]
    NEW_MSGS="$(grep -E '^## [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2} \[' "$BUS_FILE" 2>/dev/null \
      | awk -v last="$LAST_SEEN" -v me="[$TAG]" '
        {
          ts  = $2 " " $3
          tag = $4
          if (ts > last && tag != me) print ts " " tag
        }
      ' || true)"

    if [ -z "$NEW_MSGS" ]; then
      echo "0" > "$PENDING_FILE"
      exit 0
    fi

    COUNT="$(printf '%s\n' "$NEW_MSGS" | wc -l | tr -d ' ')"
    echo "$COUNT" > "$PENDING_FILE"

    SENDERS="$(printf '%s\n' "$NEW_MSGS" | awk '{print $3}' | sort -u | tr '\n' ' ' | sed 's/ *$//')"
    NEWEST="$(printf '%s\n' "$NEW_MSGS" | tail -1 | awk '{print $1 " " $2}')"

    NOTE="Claude Bus — $COUNT pending message(s) from $SENDERS on the cross-session log since you last checked (newest: $NEWEST). Content NOT shown. At a natural pause in your current work, mention to the user that pending messages exist and ask whether to check them now; run /msg-check once approved."
    ESCAPED="$(printf '%s' "$NOTE" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": $ESCAPED
  }
}
EOF
    ;;

  rotate)
    # Archive the current bus to messages-YYYY-MM.md and start fresh.
    # Keeps the header block intact so usage instructions stay visible.
    if [ ! -s "$BUS_FILE" ]; then
      echo "Bus is empty, nothing to rotate."
      exit 0
    fi

    ARCHIVE_MONTH="${1:-$(date '+%Y-%m')}"
    ARCHIVE_FILE="$(dirname "$BUS_FILE")/messages-${ARCHIVE_MONTH}.md"

    if [ -f "$ARCHIVE_FILE" ]; then
      # Append to existing archive for that month instead of clobbering
      {
        echo ""
        echo "<!-- appended $(date '+%Y-%m-%d %H:%M') -->"
        echo ""
        cat "$BUS_FILE"
      } >> "$ARCHIVE_FILE"
      echo "Appended current bus to existing archive: $ARCHIVE_FILE"
    else
      cp "$BUS_FILE" "$ARCHIVE_FILE"
      echo "Archived current bus to: $ARCHIVE_FILE"
    fi

    # Reset bus with just the header + fresh marker
    cat > "$BUS_FILE" <<HEADER
# Claude Bus — Cross-Session Messages

Append-only log of messages between Claude Code sessions on this machine.
Newest messages at the bottom. Each message is tagged with its sender session.

Sessions are identified by working directory (see the case-table in bus.sh):
  • named tags (e.g. \`[api]\`, \`[web]\`) = dirs you mapped in bus.sh
  • \`[other:<cwd>]\` = any other session

Usage (from any session):
  \`/msg-send <your message>\`  — append a message to this log
  \`/msg-check\`                 — read the latest messages
  \`/msg-all\`                   — dump the full log
  \`/msg-rotate\`                — archive this log to messages-YYYY-MM.md

---

## $(date '+%Y-%m-%d %H:%M') [system]

Bus rotated. Previous log archived to \`$(basename "$ARCHIVE_FILE")\`.

HEADER
    echo "Bus reset. New log at: $BUS_FILE"
    ;;

  help|*)
    cat <<EOF
Claude Bus
  bus.sh send <text>         Append a message to the bus
  bus.sh check               Print the last 80 lines (used by /msg-check)
  bus.sh all                 Print the entire log (used by /msg-all)
  bus.sh rotate [YYYY-MM]    Archive to messages-YYYY-MM.md, start fresh
  bus.sh session-start       Hook output: emit additionalContext JSON
                             (no-op outside the BUS_WHITELIST tags)
  bus.sh prompt-check        Hook output: per-prompt check. Emits a
                             one-line additionalContext nudge if new
                             messages arrived since last check.
                             No content shown; Claude is expected to
                             mention + ask before running /msg-check.
                             No-op outside the bus whitelist.
EOF
    ;;
esac
