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

# True if the given tag is auto-notified ("active"). Prefers the data-file
# whitelist that Conductor manages (~/.claude/bus-state/active-tags, one tag per
# line — toggled from the dashboard); falls back to BUS_WHITELIST when absent.
is_whitelisted() {
  local f="$HOME/.claude/bus-state/active-tags"
  if [ -f "$f" ]; then
    grep -qxF "$1" "$f"
  else
    case "|$BUS_WHITELIST|" in *"|$1|"*) return 0 ;; *) return 1 ;; esac
  fi
}

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

# ---- GPU reservation (single shared GPU; lease lives in bus-state) ----------
# A cooperative lease so sessions self-coordinate GPU access without asking
# each other. State is a flat key=value file; acquire/release are atomic via
# flock. Expiry is lazy (checked on access) — no daemon needed for the basics.
GPU_DIR="${GPU_STATE_DIR:-$HOME/.claude/bus-state/gpu}"
GPU_LEASE="$GPU_DIR/lease"
GPU_LOCK="$GPU_DIR/.lock"

_gpu_now() { date +%s; }
_gpu_dur_secs() {  # 30m | 2h | 45s | bare number = minutes
  case "$1" in
    *h) echo $(( ${1%h} * 3600 )) ;;
    *m) echo $(( ${1%m} * 60 )) ;;
    *s) echo $(( ${1%s} )) ;;
    ''|*[!0-9]*) echo 0 ;;
    *)  echo $(( $1 * 60 )) ;;
  esac
}
_gpu_human() {  # seconds -> "1h 20m" / "18m" / "40s"
  local s=$1 h m; [ "$s" -lt 0 ] && s=0
  h=$(( s/3600 )); m=$(( (s%3600)/60 ))
  if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi
}
_gpu_field() { grep -E "^$1=" "$GPU_LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_gpu_active() {  # lease exists and not expired
  [ -f "$GPU_LEASE" ] || return 1
  local exp; exp="$(_gpu_field expires_epoch)"
  [ -n "$exp" ] && [ "$(_gpu_now)" -lt "$exp" ]
}
_gpu_remaining() { local exp; exp="$(_gpu_field expires_epoch)"; echo $(( ${exp:-0} - $(_gpu_now) )); }
_gpu_write() {  # owner mode secs job
  local now exp; now="$(_gpu_now)"; exp=$(( now + $3 ))
  { echo "owner=$1"; echo "mode=$2"; echo "acquired_epoch=$now"; echo "expires_epoch=$exp"
    echo "last_active_epoch=$now"; echo "job=$4"; echo "requested_by="; } > "$GPU_LEASE"
}
_gpu_held_line() {  # assumes _gpu_active; the one-liner every awareness surface uses
  local owner mode job req rem idle_since idletxt
  owner="$(_gpu_field owner)"; mode="$(_gpu_field mode)"; job="$(_gpu_field job)"
  req="$(_gpu_field requested_by)"; rem="$(_gpu_human "$(_gpu_remaining)")"
  idle_since="$(_gpu_field idle_since_epoch)"; idletxt=""   # set by the idle watchdog
  if [ -n "$idle_since" ]; then
    local idle=$(( $(_gpu_now) - idle_since ))
    [ "$idle" -ge 300 ] && idletxt=" · idle $(_gpu_human "$idle")"
  fi
  if [ "$owner" = "$TAG" ]; then
    local msg="GPU: YOU hold it ($mode · ~$rem left$idletxt)."
    [ -n "$req" ] && msg="$msg  ⚠ [$req] has REQUESTED it — /gpu-release to yield, or keep it if you still need it."
    [ -n "$idletxt" ] && [ -z "$req" ] && msg="$msg  ⚠ idle — the watchdog may nudge/reclaim it; /gpu-release if your job's done."
    echo "$msg"
  else
    echo "GPU: held by [$owner] ($mode · ~$rem left${job:+ · $job}$idletxt)."
  fi
}
gpu_reserve() {
  local dur="${1:-}" mode="${2:-}"; shift 2 2>/dev/null || true; local job="${*:-}"
  case "$mode" in soft|hard) ;; *) echo "usage: /gpu-reserve <duration> <soft|hard> [\"job\"]"; return 2 ;; esac
  local secs; secs="$(_gpu_dur_secs "$dur")"
  [ "$secs" -gt 0 ] || { echo "bad duration '$dur' (use 30m, 2h, 45s, or a number of minutes)"; return 2; }
  mkdir -p "$GPU_DIR"
  ( flock 9
    if _gpu_active; then
      local owner; owner="$(_gpu_field owner)"
      if [ "$owner" = "$TAG" ]; then
        _gpu_write "$TAG" "$mode" "$secs" "$job"
        echo "Updated your GPU lease: $mode for $(_gpu_human "$secs")."
      else
        echo "GPU is HELD by [$owner] ($(_gpu_field mode), ~$(_gpu_human "$(_gpu_remaining)") left) — NOT reserved."
        echo "→ /gpu-request to ask them to yield, or wait for it to free."
        return 1
      fi
    else
      _gpu_write "$TAG" "$mode" "$secs" "$job"
      echo "Reserved the GPU: $mode for $(_gpu_human "$secs"). Job: ${job:-(none)}."
    fi
  ) 9>"$GPU_LOCK"
}
gpu_release() {
  mkdir -p "$GPU_DIR"
  ( flock 9
    if _gpu_active && [ "$(_gpu_field owner)" = "$TAG" ]; then
      rm -f "$GPU_LEASE"; echo "Released the GPU."
    elif _gpu_active; then
      echo "You don't hold the GPU ([$(_gpu_field owner)] does) — not released."; return 1
    else
      rm -f "$GPU_LEASE"; echo "GPU is already free."
    fi
  ) 9>"$GPU_LOCK"
}
gpu_keep() {  # extend your own lease from now
  local dur="${1:-}"; local secs; secs="$(_gpu_dur_secs "$dur")"
  [ "$secs" -gt 0 ] || { echo "usage: /gpu-keep <duration>"; return 2; }
  mkdir -p "$GPU_DIR"
  ( flock 9
    if _gpu_active && [ "$(_gpu_field owner)" = "$TAG" ]; then
      _gpu_write "$TAG" "$(_gpu_field mode)" "$secs" "$(_gpu_field job)"
      echo "Extended your GPU lease: $(_gpu_human "$secs") from now."
    else
      echo "You don't hold the GPU — nothing to extend."; return 1
    fi
  ) 9>"$GPU_LOCK"
}
gpu_request() {  # flag the current owner that you want it (they see it on their next turn)
  mkdir -p "$GPU_DIR"
  ( flock 9
    if ! _gpu_active; then echo "GPU is FREE — just /gpu-reserve it."; return 0; fi
    local owner; owner="$(_gpu_field owner)"
    [ "$owner" = "$TAG" ] && { echo "You already hold the GPU."; return 0; }
    sed -i "s/^requested_by=.*/requested_by=$TAG/" "$GPU_LEASE"
    echo "Flagged [$owner] that you want the GPU ($(_gpu_field mode) hold). They'll see it on their next turn."
  ) 9>"$GPU_LOCK"
}
gpu_status() {  # verbose, for /gpu-status
  if _gpu_active; then
    _gpu_held_line
    echo "  (acquired $(date -d "@$(_gpu_field acquired_epoch)" '+%H:%M' 2>/dev/null), expires $(date -d "@$(_gpu_field expires_epoch)" '+%H:%M' 2>/dev/null))"
  else
    echo "GPU: FREE — /gpu-reserve <duration> <soft|hard> [\"job\"] to claim it."
  fi
}
gpu_hook_line() { _gpu_active && _gpu_held_line || true; }  # silent when free
gpu_dispatch() {
  set +e   # gpu subcommands manage their own exit codes / booleans
  case "${1:-status}" in
    reserve) shift; gpu_reserve "$@" ;;
    release) gpu_release ;;
    keep)    shift; gpu_keep "$@" ;;
    request) gpu_request ;;
    status)  gpu_status ;;
    line)    gpu_hook_line ;;
    *) echo "usage: bus.sh gpu {reserve <dur> <soft|hard> [job]|release|keep <dur>|request|status}"; return 2 ;;
  esac
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

  gpu)
    gpu_dispatch "$@"
    exit $?
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
      NOTE=""
    else
      COUNT="$(printf '%s\n' "$NEW_MSGS" | wc -l | tr -d ' ')"
      echo "$COUNT" > "$PENDING_FILE"
      SENDERS="$(printf '%s\n' "$NEW_MSGS" | awk '{print $3}' | sort -u | tr '\n' ' ' | sed 's/ *$//')"
      NEWEST="$(printf '%s\n' "$NEW_MSGS" | tail -1 | awk '{print $1 " " $2}')"
      NOTE="Claude Bus — $COUNT pending message(s) from $SENDERS on the cross-session log since you last checked (newest: $NEWEST). Content NOT shown. At a natural pause in your current work, mention to the user that pending messages exist and ask whether to check them now; run /msg-check once approved."
    fi

    # GPU reservation awareness: one line, only while the GPU is held (silent when free).
    GPU_LINE="$(gpu_hook_line 2>/dev/null || true)"

    # Nothing pending and GPU free -> stay silent (preserves prior behavior).
    if [ -z "$NOTE" ] && [ -z "$GPU_LINE" ]; then
      exit 0
    fi

    FULL="$NOTE"
    if [ -n "$GPU_LINE" ]; then
      if [ -n "$FULL" ]; then FULL="$FULL"$'\n'"$GPU_LINE"; else FULL="$GPU_LINE"; fi
    fi
    ESCAPED="$(printf '%s' "$FULL" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"

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
