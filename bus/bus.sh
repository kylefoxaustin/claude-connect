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

# ---- Named-resource reservation (GPU + boards; leases in bus-state) --------
# Cooperative leases so sessions self-coordinate any shared resource (the GPU,
# the IQ9 EVK, …) without asking each other. Acquire/release atomic via flock;
# expiry is lazy. `gpu` is just one resource (with nvidia-smi telemetry + a
# watchdog); others are plain leases with heartbeat-based idle detection.
RES_ROOT="${RESOURCE_STATE_DIR:-$HOME/.claude/bus-state/resources}"

# --- per-invocation resource context ----------------------------------------
_res_setup() { RES_NAME="$1"; RES_DIR="$RES_ROOT/$1"; RES_LEASE="$RES_DIR/lease"; RES_LOCK="$RES_DIR/.lock"; }
_res_label() { case "$1" in gpu) echo "GPU" ;; *) echo "$1" ;; esac; }

_res_now() { date +%s; }
_res_dur_secs() {
  case "$1" in
    *h) echo $(( ${1%h} * 3600 )) ;;
    *m) echo $(( ${1%m} * 60 )) ;;
    *s) echo $(( ${1%s} )) ;;
    ''|*[!0-9]*) echo 0 ;;
    *)  echo $(( $1 * 60 )) ;;
  esac
}
_res_human() { local s=$1 h m; [ "$s" -lt 0 ] && s=0; h=$((s/3600)); m=$(((s%3600)/60)); if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi; }
_res_field() { grep -E "^$1=" "$RES_LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_res_active() { [ -f "$RES_LEASE" ] || return 1; local exp; exp="$(_res_field expires_epoch)"; [ -n "$exp" ] && [ "$(_res_now)" -lt "$exp" ]; }
_res_remaining() { local exp; exp="$(_res_field expires_epoch)"; echo $(( ${exp:-0} - $(_res_now) )); }
_res_write() {  # mode secs job
  local now exp; now="$(_res_now)"; exp=$(( now + $2 ))
  { echo "owner=$TAG"; echo "mode=$1"; echo "acquired_epoch=$now"; echo "expires_epoch=$exp"
    echo "last_active_epoch=$now"; echo "job=$3"; echo "requested_by="; } > "$RES_LEASE"
}
_res_held_line() {  # assumes _res_active
  local owner mode job req rem lbl idle_since idletxt
  owner="$(_res_field owner)"; mode="$(_res_field mode)"; job="$(_res_field job)"
  req="$(_res_field requested_by)"; rem="$(_res_human "$(_res_remaining)")"; lbl="$(_res_label "$RES_NAME")"
  idle_since="$(_res_field idle_since_epoch)"; idletxt=""
  if [ -n "$idle_since" ]; then local idle=$(( $(_res_now) - idle_since )); [ "$idle" -ge 300 ] && idletxt=" · idle $(_res_human "$idle")"; fi
  if [ "$owner" = "$TAG" ]; then
    local msg="$lbl: YOU hold it ($mode · ~$rem left$idletxt)."
    [ -n "$req" ] && msg="$msg  ⚠ [$req] has REQUESTED it — /release $RES_NAME to yield, or keep it if you still need it."
    [ -n "$idletxt" ] && [ -z "$req" ] && msg="$msg  ⚠ idle — the watchdog may nudge/reclaim it; /release $RES_NAME if done."
    echo "$msg"
  else
    echo "$lbl: held by [$owner] ($mode · ~$rem left${job:+ · $job}$idletxt)."
  fi
}

res_reserve() {  # name dur mode [job...]
  _res_setup "$1"; local dur="${2:-}" mode="${3:-}"; shift 3 2>/dev/null || true; local job="${*:-}"
  case "$mode" in soft|hard) ;; *) echo "usage: /reserve <resource> <duration> <soft|hard> [\"job\"]"; return 2 ;; esac
  local secs; secs="$(_res_dur_secs "$dur")"
  [ "$secs" -gt 0 ] || { echo "bad duration '$dur' (use 30m, 2h, 45s, or minutes)"; return 2; }
  mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active; then
      local owner; owner="$(_res_field owner)"
      if [ "$owner" = "$TAG" ]; then _res_write "$mode" "$secs" "$job"; echo "Updated your $(_res_label "$RES_NAME") lease: $mode for $(_res_human "$secs")."
      else echo "$(_res_label "$RES_NAME") is HELD by [$owner] ($(_res_field mode), ~$(_res_human "$(_res_remaining)") left) — NOT reserved."; echo "→ /request $RES_NAME to ask them to yield, or wait."; return 1; fi
    else _res_write "$mode" "$secs" "$job"; echo "Reserved $(_res_label "$RES_NAME"): $mode for $(_res_human "$secs"). Job: ${job:-(none)}."; fi
  ) 9>"$RES_LOCK"
}
res_release() {
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active && [ "$(_res_field owner)" = "$TAG" ]; then rm -f "$RES_LEASE"; echo "Released $(_res_label "$1")."
    elif _res_active; then echo "You don't hold $(_res_label "$1") ([$(_res_field owner)] does) — not released."; return 1
    else rm -f "$RES_LEASE"; echo "$(_res_label "$1") is already free."; fi
  ) 9>"$RES_LOCK"
}
res_keep() {  # name dur  (also the heartbeat: refreshes last_active + clears idle)
  _res_setup "$1"; local secs; secs="$(_res_dur_secs "${2:-}")"
  [ "$secs" -gt 0 ] || { echo "usage: /keep <resource> <duration>"; return 2; }
  mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active && [ "$(_res_field owner)" = "$TAG" ]; then _res_write "$(_res_field mode)" "$secs" "$(_res_field job)"; echo "Extended your $(_res_label "$1") lease: $(_res_human "$secs") from now."
    else echo "You don't hold $(_res_label "$1") — nothing to extend."; return 1; fi
  ) 9>"$RES_LOCK"
}
res_request() {
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    if ! _res_active; then echo "$(_res_label "$1") is FREE — just /reserve $1 it."; return 0; fi
    local owner; owner="$(_res_field owner)"; [ "$owner" = "$TAG" ] && { echo "You already hold $(_res_label "$1")."; return 0; }
    sed -i "s/^requested_by=.*/requested_by=$TAG/" "$RES_LEASE"
    echo "Flagged [$owner] that you want $(_res_label "$1") ($(_res_field mode) hold). They'll see it on their next turn."
  ) 9>"$RES_LOCK"
}
res_status() {  # [name]  — one resource, or all
  if [ -n "${1:-}" ]; then _res_setup "$1"
    if _res_active; then _res_held_line; echo "  (expires $(date -d "@$(_res_field expires_epoch)" '+%H:%M' 2>/dev/null))"
    else echo "$(_res_label "$1"): FREE — /reserve $1 <dur> <soft|hard> to claim it."; fi
    return 0
  fi
  local any=""
  for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; _res_setup "$(basename "$d")"; if _res_active; then _res_held_line; any=1; fi; done
  [ -z "$any" ] && echo "All resources FREE."
}
res_hook_lines() {  # every held resource, one line each (for the per-prompt hook)
  [ -d "$RES_ROOT" ] || return 0
  for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; _res_setup "$(basename "$d")"; _res_active && _res_held_line; done
}
res_dispatch() {
  set +e
  case "${1:-status}" in
    reserve) shift; res_reserve "$@" ;;
    release) shift; res_release "$@" ;;
    keep)    shift; res_keep "$@" ;;
    request) shift; res_request "$@" ;;
    status)  shift; res_status "$@" ;;
    lines)   res_hook_lines ;;
    *) echo "usage: bus.sh res {reserve <name> <dur> <soft|hard>|release <name>|keep <name> <dur>|request <name>|status [name]}"; return 2 ;;
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

  res)
    res_dispatch "$@"
    exit $?
    ;;

  gpu)
    # back-compat: /gpu-* is the "gpu" resource
    action="${1:-status}"; shift 2>/dev/null || true
    res_dispatch "$action" gpu "$@"
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

    # Resource-reservation awareness: a line per held resource (silent when all free).
    RES_LINES="$(res_hook_lines 2>/dev/null || true)"

    # Nothing pending and every resource free -> stay silent (preserves prior behavior).
    if [ -z "$NOTE" ] && [ -z "$RES_LINES" ]; then
      exit 0
    fi

    FULL="$NOTE"
    if [ -n "$RES_LINES" ]; then
      if [ -n "$FULL" ]; then FULL="$FULL"$'\n'"$RES_LINES"; else FULL="$RES_LINES"; fi
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
