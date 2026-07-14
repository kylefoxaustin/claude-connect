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

# Where your projects live, one directory per project. A session that cd's deep
# inside a project (results/bench_data, a nested repo, …) must keep the SAME bus
# identity, so the tag fallback below names the PROJECT, not the current dir.
BUS_PROJECTS_ROOT="${BUS_PROJECTS_ROOT:-$HOME/Documents/GitHub}"

_proj_root_of() {
  # The project root a given cwd belongs to (same rule the tag uses). Takes an explicit
  # dir so it can be asked about ANOTHER session's cwd, not just this process's.
  local dir="$1" rel root=""
  # 1) Directly under the projects root -> that project dir wins.
  case "$dir" in
    "$BUS_PROJECTS_ROOT"/?*)
      rel="${dir#"$BUS_PROJECTS_ROOT"/}"; rel="${rel%%/*}"
      if [ -n "$rel" ]; then printf '%s\n' "$BUS_PROJECTS_ROOT/$rel"; return; fi ;;
  esac
  # 2) Else the enclosing git repo, if any. 3) Else the dir itself.
  root="$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$root" ] || root="$dir"
  printf '%s\n' "$root"
}
_proj_root() { _proj_root_of "$CWD"; }

# IDENTITY-COLLISION detection (holobench, 2026-07-13). The bus tag is derived from the
# working directory, so TWO Claude sessions started in one repo post under one tag and are
# indistinguishable — a reply lands on whichever reads it first. A live session is exactly
# one `comm=claude` process whose cwd is the project; so counting `claude` processes rooted
# at the SAME project is an unambiguous test (>=2 == collision). It counts by cwd, never by
# matching our own command line, so it cannot self-match the way a `pgrep -f` monitor does.
sibling_claude_pids() {
  local mine p comm cwd root
  mine="$(_proj_root)"
  for p in /proc/[0-9]*; do
    [ -r "$p/comm" ] || continue
    IFS= read -r comm < "$p/comm" 2>/dev/null || continue
    [ "$comm" = "claude" ] || continue
    cwd="$(readlink "$p/cwd" 2>/dev/null || true)"
    [ -n "$cwd" ] || continue
    root="$(_proj_root_of "$cwd")"
    [ "$root" = "$mine" ] && printf '%s\n' "${p#/proc/}"
  done
}
sibling_hook_lines() {
  local pids n root
  pids="$(sibling_claude_pids 2>/dev/null || true)"
  [ -n "$pids" ] || return 0
  n="$(printf '%s\n' "$pids" | grep -c . || true)"
  [ "${n:-0}" -ge 2 ] || return 0
  root="$(_proj_root)"
  printf '⚠️ IDENTITY COLLISION: %s Claude sessions are running in %s and ALL post to the bus as [%s]. A reader CANNOT tell you apart — a reply may reach the wrong one, and work queued "for whoever holds this tree" is addressed to your own doppelganger. Check with the operator whether a second session was opened here; close it or coordinate explicitly. (claude pids: %s)' \
    "$n" "$root" "$TAG" "$(printf '%s' "$pids" | tr '\n' ' ' | sed 's/ *$//')"
}

# TAG RESOLUTION. An optional data file (`$BUS_STATE/tag-map`, "glob<TAB>tag" per line) wins
# over this built-in table. This exists because on 2026-07-12 a migration of this script over
# the operator's LIVE copy silently replaced the real project→tag mappings with these sanitized
# placeholders — a session's cwd stopped matching, it fell through to `other:<dirname>`, and it
# became unaddressable for hours while every automated signal reported it was fine. Keeping the
# real map in a DATA FILE the script reads first makes that failure structurally impossible: a
# script edit cannot touch data it does not contain.
TAG=""
BUS_STATE="${BUS_STATE_DIR:-$HOME/.claude/bus-state}"
if [ -r "$BUS_STATE/tag-map" ]; then
  while IFS="$(printf '\t')" read -r glob t; do
    case "$glob" in ''|'#'*) continue ;; esac
    case "$CWD" in $glob|$glob/*) TAG="$t"; break ;; esac
  done < "$BUS_STATE/tag-map"
fi
# Never `return` here — this is top-level code, not a function; a stray return would abort the
# whole script on every tag-map hit, which is a worse bug than the one being prevented.
if [ -z "$TAG" ]; then
case "$CWD" in
  */my-api|*/my-api/*)       TAG="api"    ;;
  */my-web|*/my-web/*)       TAG="web"    ;;
  */my-worker|*/my-worker/*) TAG="worker" ;;
  *)                         TAG="other:$(basename "$(_proj_root)")" ;;
esac
fi

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

# ⚠️ WARN-ON-UNREGISTERED-TAG — backend's #3, the only fix that generalises.
# A bus.sh migration on 2026-07-12 reset the tag table to placeholders; sessions fell through
# to `other:<dirname>`, became unaddressable with orphaned watermarks and dead auto-delivery,
# and NOTHING said so. A silent `other:<basename>` fallback is a sensor reporting a name nobody
# is calling — so make the fallback the ALARM, not the default. Warn on stderr (can't be
# scraped), once, and never from the silent hooks.
_warn_if_unregistered() {
  is_whitelisted "$TAG" && return 0
  case "${BUS_ACTION:-}" in session-start|prompt-check) return 0 ;; esac
  printf '⚠️  bus.sh: your tag is "%s" — NOT registered for auto-delivery.\n' "$TAG" >&2
  printf '    Directed mail may reach nobody and auto-delivery will not fire. cwd=%s\n' "$PWD" >&2
  printf '    If that is wrong, your project dir is missing from the tag-map — tell claude-connect.\n' >&2
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

# ---- Named-resource reservation + FIFO queue (GPU + boards; leases in bus-state) --
# Cooperative leases so sessions self-coordinate any shared resource (the GPU, the
# IQ9 EVK, an Orin, …) without asking each other. Acquire/release atomic via flock;
# expiry lazy. A resource carries a FIFO queue: /res-request joins it, and on release
# the head is OFFERED the resource for a grace window (claim with /reserve, decline
# with /res-pass, or auto-pass). `gpu` = one resource (nvidia-smi telemetry + a
# watchdog); others are plain leases with heartbeat-based idle detection.
RES_ROOT="${RESOURCE_STATE_DIR:-$HOME/.claude/bus-state/resources}"
RES_GRACE_MIN="${RES_GRACE_MIN:-15}"    # how long a freed resource is held for the next in queue

# Resource-name aliases. One physical board must have exactly ONE name, or it gets
# two leases and two queues. Map the spellings people actually reach for onto the
# canonical name (an Orin NX/Nano would be its OWN resource, not an alias).
_res_canon() {
  case "$1" in
    orin|jetson|agx|orin64)              echo "orin-agx"   ;;
    imx95|imx95-evk|frdm-imx95|imx95-pro) echo "imx95-frdm" ;;
    iq9|iq9075)                          echo "iq9-evk"    ;;
    *)                                   echo "$1"         ;;
  esac
}
_res_known() { ls -1 "$RES_ROOT" 2>/dev/null | tr '\n' ' ' | sed 's/ $//'; }

_res_setup() { RES_NAME="$1"; RES_DIR="$RES_ROOT/$1"; RES_LEASE="$RES_DIR/lease"; RES_LOCK="$RES_DIR/.lock"; }
_res_label() { case "$1" in gpu) echo "GPU" ;; *) echo "$1" ;; esac; }
_res_now() { date +%s; }
_res_dur_secs() {
  case "$1" in
    *h) echo $(( ${1%h} * 3600 )) ;; *m) echo $(( ${1%m} * 60 )) ;; *s) echo $(( ${1%s} )) ;;
    ''|*[!0-9]*) echo 0 ;; *) echo $(( $1 * 60 )) ;;
  esac
}
_res_human() { local s=$1 h m; [ "$s" -lt 0 ] && s=0; h=$((s/3600)); m=$(((s%3600)/60)); if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi; }
_res_field() { grep -E "^$1=" "$RES_LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_res_active() { [ -f "$RES_LEASE" ] || return 1; local exp; exp="$(_res_field expires_epoch)"; [ -n "$exp" ] && [ "$(_res_now)" -lt "$exp" ]; }
_res_is_offer() { [ "$(_res_field mode)" = "offer" ]; }
_res_remaining() { local exp; exp="$(_res_field expires_epoch)"; echo $(( ${exp:-0} - $(_res_now) )); }

# --- queue helpers (comma-separated FIFO in the lease's `queue=` field) --------
_res_queue() { _res_field queue; }
_res_q_count() { local q; q="$(_res_queue)"; [ -z "$q" ] && { echo 0; return; }; echo "$q" | tr ',' '\n' | grep -c . ; }
_res_q_has() { local q; q="$(_res_queue)"; echo ",$q," | grep -q ",$1,"; }
_res_q_pos() { local q; q="$(_res_queue)"; echo ",$q," | tr ',' '\n' | grep -nxF "$1" | head -1 | cut -d: -f1 | awk '{print $1-1}'; }

# Write/refresh a normal hold as $TAG, PRESERVING the queue.
_owner_pid() {
  # The pid that ACTUALLY DIES when the session dies — the `claude` process itself.
  #
  # NOT the `bash -c "cd X && claude --continue; exec bash"` wrapper. That wrapper SURVIVES
  # claude's death (it execs into a plain shell), so using it as a liveness proxy would report
  # a corpse as alive forever — which is worse than having no pid at all, because it would look
  # like a working check.
  #
  # Why this matters (image_gen's finding): today the ONLY crash-detection anywhere in the fleet
  # is `acquired_epoch < btime`, which proves a dead owner but ONLY fires when the whole MACHINE
  # reboots. A session that dies while the box keeps running is undetectable — so the best
  # available outcome was a watchdog nudging a corpse for hours. With this, `kill -0 $owner_pid`
  # answers "is the owner dead?" exactly and instantly.
  local p="$$" c i
  for i in 1 2 3 4 5 6 7 8; do
    [ -r "/proc/$p/comm" ] || break
    c="$(cat "/proc/$p/comm" 2>/dev/null)"
    if [ "$c" = "claude" ]; then printf '%s' "$p"; return 0; fi
    p="$(awk '{print $4}' "/proc/$p/stat" 2>/dev/null)"
    case "$p" in ''|0|1) break ;; esac
  done
  printf '%s' ''   # not running under a Claude session — record nothing rather than guess
}

_res_write() {  # mode secs job
  local now exp q; now="$(_res_now)"; exp=$(( now + $2 )); q="$(_res_queue)"
  { echo "owner=$TAG"; echo "owner_pid=$(_owner_pid)"; echo "mode=$1"
    echo "acquired_epoch=$now"; echo "expires_epoch=$exp"
    echo "last_active_epoch=$now"; echo "job=$3"; echo "queue=$q"; } > "$RES_LEASE"
}

_broker_notify() {  # post a hand-off message from a neutral [resource-broker] tag
  local ts; ts="$(date '+%Y-%m-%d %H:%M')"
  { echo ""; echo "## $ts [resource-broker]"; echo ""; echo "$1"; } >> "$BUS_FILE"
}

# Current owner is done/gone → offer to the head of the queue, or free it.
# Caller MUST hold the flock. Sets $RES_* via _res_setup beforehand.
_res_promote_locked() {
  local q head rest now exp lbl; q="$(_res_queue)"; lbl="$(_res_label "$RES_NAME")"
  if [ -z "$q" ]; then rm -f "$RES_LEASE"; echo "freed"; return; fi
  head="${q%%,*}"; rest=""; [ "$head" != "$q" ] && rest="${q#*,}"
  now="$(_res_now)"; exp=$(( now + RES_GRACE_MIN * 60 ))
  { echo "owner=$head"; echo "mode=offer"; echo "acquired_epoch=$now"; echo "expires_epoch=$exp"
    echo "last_active_epoch=$now"; echo "job=OFFERED"; echo "queue=$rest"; } > "$RES_LEASE"
  _broker_notify "to:$head — 🎉 [$head] you're up for $lbl! It's held for you for ${RES_GRACE_MIN}m. Run /reserve $RES_NAME <dur> <soft|hard> to claim it, or /res-pass $RES_NAME to hand it to the next in line. (No response ⇒ it auto-passes.)"
  echo "offered:$head"
}

_res_held_line() {  # assumes a lease exists (held / offered)
  local owner mode job rem lbl qc idle_since idletxt q qhead
  owner="$(_res_field owner)"; mode="$(_res_field mode)"; job="$(_res_field job)"
  rem="$(_res_human "$(_res_remaining)")"; lbl="$(_res_label "$RES_NAME")"; qc="$(_res_q_count)"
  q="$(_res_queue)"; qhead="${q%%,*}"
  idle_since="$(_res_field idle_since_epoch)"; idletxt=""
  if [ -n "$idle_since" ]; then local idle=$(( $(_res_now) - idle_since )); [ "$idle" -ge 300 ] && idletxt=" · idle $(_res_human "$idle")"; fi
  local qtxt=""; [ "$qc" -gt 0 ] && qtxt=" · queue: $qc (${qhead}…)"

  if [ "$mode" = "offer" ]; then
    if [ "$owner" = "$TAG" ]; then
      echo "$lbl: 🎉 OFFERED TO YOU (expires ~$rem) — /reserve $RES_NAME <dur> <soft|hard> to claim, or /res-pass $RES_NAME.$qtxt"
    else
      echo "$lbl: offered to [$owner] (awaiting claim, ~$rem)$qtxt"
    fi
    return
  fi
  if [ "$owner" = "$TAG" ]; then
    local msg="$lbl: YOU hold it ($mode · ~$rem left$idletxt)."
    [ "$qc" -gt 0 ] && msg="$msg  ⚠ $qc waiting (next: [$qhead]) — /release $RES_NAME when done so they get it."
    [ -n "$idletxt" ] && [ "$qc" -eq 0 ] && msg="$msg  ⚠ idle — watchdog may nudge/reclaim; /release $RES_NAME if done."
    echo "$msg"
  else
    echo "$lbl: held by [$owner] ($mode · ~$rem left${job:+ · $job}$idletxt)$qtxt."
  fi
}

res_reserve() {  # name dur mode [job...]
  _res_setup "$1"; local dur="${2:-}" mode="${3:-}"; shift 3 2>/dev/null || true; local job="${*:-}"
  case "$mode" in soft|hard) ;; *) echo "usage: /reserve <resource> <duration> <soft|hard> [\"job\"]"; return 2 ;; esac
  local secs; secs="$(_res_dur_secs "$dur")"
  [ "$secs" -gt 0 ] || { echo "bad duration '$dur' (use 30m, 2h, 45s, or minutes)"; return 2; }
  if [ ! -d "$RES_DIR" ]; then
    echo "⚠ '$RES_NAME' is a NEW resource — creating it. Existing: $(_res_known)"
    echo "  A new name gets its OWN separate lease + queue. If you meant an existing one, use that name."
  fi
  mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active; then
      local owner; owner="$(_res_field owner)"
      if [ "$owner" = "$TAG" ]; then
        local was_offer=""; _res_is_offer && was_offer=" (claimed your offer)"
        _res_write "$mode" "$secs" "$job"; echo "Reserved $(_res_label "$RES_NAME")$was_offer: $mode for $(_res_human "$secs")."
      else
        echo "$(_res_label "$RES_NAME") is HELD by [$owner] ($(_res_field mode), ~$(_res_human "$(_res_remaining)") left) — NOT reserved."
        echo "→ /res-request $RES_NAME to join the queue (you'll be pinged when it's free)."; return 1
      fi
    else _res_write "$mode" "$secs" "$job"; echo "Reserved $(_res_label "$RES_NAME"): $mode for $(_res_human "$secs"). Job: ${job:-(none)}."; fi
  _asset_handoff "$RES_NAME"
  ) 9>"$RES_LOCK"
}

res_release() {
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active && [ "$(_res_field owner)" = "$TAG" ]; then
      local r; r="$(_res_promote_locked)"
      case "$r" in offered:*) echo "Released $(_res_label "$1") — handed to [${r#offered:}] (next in queue)." ;; *) echo "Released $(_res_label "$1")." ;; esac
      # THE CHECKPOINT. This is the moment the system already knows about, and the only one
      # where reconciling the card against what you learned is free.
      #
      # A continuous "knowledge sync" would fail the same way the /msg-check storm failed: it
      # optimises for freshness and delivers VOLUME. A card updated on every finding becomes a
      # log, and a log nobody can read is the same as no card. The card's value IS that it is
      # short and curated — which is exactly the property streaming into it destroys.
      #
      # So: the BUS is continuous and durable. The CARD is periodic and curated. Reconcile at
      # the boundary, not in between.
      echo ""
      echo "  📇 Before you move on — **what did you learn about $(_res_label "$1") that is NOT in its card?**"
      echo "     Gotchas · a trap you nearly fell into · a claim in the card you found to be STALE"
      echo "     · a question you could not answer (write the QUESTION — it survives you; the"
      echo "     answer you never got does not)."
      echo "       bus.sh asset path $1     # open the card and edit it"
      echo "     **\"I have nothing further\" is a complete answer. Silence is not.**"
    elif _res_active; then echo "You don't hold $(_res_label "$1") ([$(_res_field owner)] does) — not released."; return 1
    else rm -f "$RES_LEASE"; echo "$(_res_label "$1") is already free."; fi
  ) 9>"$RES_LOCK"
}

res_pass() {  # decline an offer -> next in line
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active && _res_is_offer && [ "$(_res_field owner)" = "$TAG" ]; then
      local r; r="$(_res_promote_locked)"
      case "$r" in offered:*) echo "Passed $(_res_label "$1") to [${r#offered:}]." ;; *) echo "Passed — $(_res_label "$1") is now free (queue empty)." ;; esac
    else echo "You have no active offer for $(_res_label "$1") to pass."; return 1; fi
  ) 9>"$RES_LOCK"
}

res_keep() {  # name dur
  _res_setup "$1"; local secs; secs="$(_res_dur_secs "${2:-}")"
  [ "$secs" -gt 0 ] || { echo "usage: /keep <resource> <duration>"; return 2; }
  mkdir -p "$RES_DIR"
  ( flock 9
    if _res_active && [ "$(_res_field owner)" = "$TAG" ] && ! _res_is_offer; then _res_write "$(_res_field mode)" "$secs" "$(_res_field job)"; echo "Extended your $(_res_label "$1") lease: $(_res_human "$secs") from now."
    else echo "You don't hold $(_res_label "$1") — nothing to extend."; return 1; fi
  ) 9>"$RES_LOCK"
}

res_request() {  # join the queue
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    if ! _res_active; then echo "$(_res_label "$1") is FREE — just /reserve $1 it."; return 0; fi
    local owner; owner="$(_res_field owner)"
    [ "$owner" = "$TAG" ] && { echo "You already hold $(_res_label "$1")."; return 0; }
    if _res_q_has "$TAG"; then echo "You're already in the $(_res_label "$1") queue (position $(_res_q_pos "$TAG")). You'll be pinged when it's your turn."; return 0; fi
    local q; q="$(_res_queue)"; if [ -z "$q" ]; then q="$TAG"; else q="$q,$TAG"; fi
    sed -i "s/^queue=.*/queue=$q/" "$RES_LEASE" 2>/dev/null || echo "queue=$q" >> "$RES_LEASE"
    echo "Added you to the $(_res_label "$1") queue (position $(_res_q_count)). You'll be pinged the moment it's your turn — no need to keep checking."
  ) 9>"$RES_LOCK"
}

res_status() {  # [name]
  if [ -n "${1:-}" ]; then _res_setup "$1"
    if _res_active; then _res_held_line; else echo "$(_res_label "$1"): FREE — /reserve $1 <dur> <soft|hard> to claim it."; fi
    return 0
  fi
  local any=""
  for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; _res_setup "$(basename "$d")"; if _res_active; then _res_held_line; any=1; fi; done
  [ -z "$any" ] && echo "All resources FREE."
}
res_hook_lines() { [ -d "$RES_ROOT" ] || return 0; for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; _res_setup "$(basename "$d")"; _res_active && _res_held_line; done; }

# promote: used by the watchdog (separate process) on expiry/reclaim/offer-timeout.
# Pass the owner the watchdog decided to evict; if it changed underneath (owner
# released, offer claimed, someone else grabbed it) this no-ops — race-safe.
res_promote() {  # name [expected_owner]
  _res_setup "$1"; mkdir -p "$RES_DIR"
  ( flock 9
    [ -f "$RES_LEASE" ] || { echo "gone"; exit 0; }
    local cur; cur="$(_res_field owner)"
    if [ -n "${2:-}" ] && [ "$cur" != "$2" ]; then echo "skip (owner is now [$cur], not [$2])"; exit 0; fi
    _res_promote_locked
  ) 9>"$RES_LOCK"
}

res_dispatch() {
  set +e
  local action="${1:-status}"; shift 2>/dev/null || true
  # Canonicalize the resource name (always the first arg) and say so when remapped.
  if [ "$action" != "lines" ] && [ -n "${1:-}" ]; then
    local given="$1" canon; canon="$(_res_canon "$1")"
    if [ "$canon" != "$given" ]; then
      echo "note: '$given' is an alias — using the canonical resource '$canon'."
      shift; set -- "$canon" "$@"
    fi
  fi
  case "$action" in
    reserve) res_reserve "$@" ;;  release) res_release "$@" ;;
    keep)    res_keep "$@" ;;      request) res_request "$@" ;;
    pass)    res_pass "$@" ;;      promote) res_promote "$@" ;;
    status)  res_status "$@" ;;    lines)   res_hook_lines ;;
    *) echo "usage: bus.sh res {reserve|release|keep|request|pass|status [name]}"; return 2 ;;
  esac
}

# ---- Coordination: retraction / supersede -----------------------------------
# Pull an instruction back before the recipient acts on it. Writes a record that
# Conductor watches (it wakes the recipient immediately — even if busy — since the
# recipient may be mid-action) and that the recipient's prompt-check surfaces
# LOUDLY at the top until they've checked messages.
COORD_ROOT="${COORD_STATE_DIR:-$HOME/.claude/bus-state/coord}"
RETRACT_DIR="$COORD_ROOT/retractions"

_coord_plain() {  # a tag or to:-token -> plain name (strip brackets + other:)
  local t="${1#[}"; t="${t%]}"; case "$t" in other:*) t="${t#other:}" ;; esac
  printf '%s' "$t" | tr '[:upper:]' '[:lower:]'
}

# Post a visible bus message + a machine record. kind = RETRACTION | CORRECTION.
_coord_retract() {  # kind to-tag text...
  local kind="$1" to="$2"; shift 2 2>/dev/null || true; local text="$*"
  if [ -z "$to" ] || [ -z "$text" ]; then
    echo "usage: bus.sh $( [ "$kind" = CORRECTION ] && echo supersede || echo retract ) <to-tag> \"<what was wrong / do instead>\"" >&2
    return 2
  fi
  local plain now ts label; plain="$(_coord_plain "$to")"; now="$(date +%s)"; ts="$(date '+%Y-%m-%d %H:%M')"
  case "$kind" in CORRECTION) label="🛑 CORRECTION" ;; *) label="🛑 RETRACTION" ;; esac
  { echo ""; echo "## $ts [$TAG]"; echo ""
    echo "to:$plain — [$TAG] $label — $text  (Do NOT act on my earlier instruction.)"; } >> "$BUS_FILE"
  mkdir -p "$RETRACT_DIR"
  find "$RETRACT_DIR" -type f -mmin +120 -delete 2>/dev/null || true   # prune stale (>2h)
  { echo "sender=$TAG"; echo "target=$to"; echo "target_plain=$plain"; echo "kind=$kind"
    echo "created=$ts"; echo "epoch=$now"; echo "text=$text"; } > "$RETRACT_DIR/${now}-${plain}"
  echo "$label sent to [$plain] — they'll be woken to see it immediately."
  # No mark_seen: posting must never mark OTHERS' unread mail as read (see send).
}

# Loud lines for UNACKNOWLEDGED retractions targeting me (created after my last-seen).
retract_hook_lines() {  # myplain last_seen
  local myplain="$1" last_seen="$2" f created sender kind text out=""
  [ -d "$RETRACT_DIR" ] || return 0
  for f in "$RETRACT_DIR"/*-"$myplain"; do
    [ -f "$f" ] || continue
    created="$(grep -E '^created=' "$f" | cut -d= -f2-)"
    [ -n "$last_seen" ] && [[ "$created" > "$last_seen" ]] || continue
    sender="$(grep -E '^sender=' "$f" | cut -d= -f2-)"
    text="$(grep -E '^text=' "$f" | cut -d= -f2-)"
    out="${out}🛑🛑 RETRACTION from [$sender]: ${text} — STOP; do NOT act on their earlier instruction, re-evaluate first."$'\n'
  done
  printf '%s' "$out"
}

# ---- Push gate: approve/deny git-push requests the PreToolUse hook files ------
PUSH_TOKENS="$COORD_ROOT/push-tokens"
PUSH_REQUESTS="$COORD_ROOT/push-requests"
# AN APPROVAL WAITS FOR THE AGENT; IT DOES NOT RACE IT.
#
# This was 1800s, and before that 300s, and both were wrong for the same reason. Kyle
# approves from his phone; the *agent* is the one that has to notice and re-run the push.
# A denied session is parked at its prompt — it may be asleep, mid-task, or Conductor may
# not be running to ping it. If the clock ran out first, the token expired AND the request
# had already been deleted, so **the approval evaporated leaving nothing behind**: no
# pending request, no token, no trace. From Kyle's side, "I approved it and nothing
# happened", with no way to find out why. He'd have to approve again, never knowing he had.
#
# So the deadline is now a long backstop (24h), not a race. What makes a long-lived grant
# safe is not a short fuse — it's VISIBILITY: an armed approval is surfaced as its own
# state ("approved, waiting for <repo> to push"), and `push revoke` disarms it. A control
# you can SEE and TAKE BACK beats one that silently expires.
PUSH_TTL="${PUSH_TOKEN_TTL:-86400}"
_push_field() { grep -E "^$1=" "$2" 2>/dev/null | head -1 | cut -d= -f2- ; }

# A token is `key=value` lines now (it used to be a bare epoch). Read both: an old
# bare-integer token left over from before this change must still work, not silently
# fail closed on the one control Kyle relies on.
_push_token_expiry() {  # <token-file>
  local raw exp
  exp="$(_push_field expires "$1")"
  if [ -z "$exp" ]; then
    raw="$(head -1 "$1" 2>/dev/null || true)"
    case "$raw" in ''|*[!0-9]*) exp=0 ;; *) exp="$raw" ;; esac
  fi
  case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
  printf '%s' "$exp"
}

PERSIST_TOKENS="$COORD_ROOT/persist-tokens"
PERSIST_REQUESTS="$COORD_ROOT/persist-requests"
PERSIST_TTL="${PERSIST_TOKEN_TTL:-86400}"   # durable, like a push grant: it WAITS for the agent

persist_list() {
  local f any="" now exp
  now="$(date +%s)"
  [ -d "$PERSIST_REQUESTS" ] && for f in "$PERSIST_REQUESTS"/*; do [ -f "$f" ] || continue; any=1
    echo "  ⏳ $(_push_field target_name "$f")  [$(_push_field kind "$f")] — waiting for you"
    echo "       $(_push_field detail "$f")"
  done
  [ -d "$PERSIST_TOKENS" ] && for f in "$PERSIST_TOKENS"/*; do [ -f "$f" ] || continue
    exp="$(_push_field expires "$f")"; case "$exp" in ''|*[!0-9]*) exp=0 ;; esac
    [ "$now" -lt "$exp" ] || { rm -f "$f"; continue; }
    any=1
    echo "  ✅ $(_push_field target_name "$f") — APPROVED, waiting for the session to act"
  done
  [ -z "$any" ] && echo "No pending persistence approvals."
  return 0
}

persist_approve() {  # <name-or-key>
  local q="${1:-}" f name key target matched=""
  [ -n "$q" ] || { echo "usage: bus.sh persist approve <name>"; return 2; }
  mkdir -p "$PERSIST_TOKENS"
  [ -d "$PERSIST_REQUESTS" ] && for f in "$PERSIST_REQUESTS"/*; do [ -f "$f" ] || continue
    name="$(_push_field target_name "$f")"; target="$(_push_field target "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then
      { echo "expires=$(( $(date +%s) + PERSIST_TTL ))"
        echo "target=$target"; echo "target_name=$name"
        echo "approved=$(date +%s)"; echo "approved_at=$(date '+%Y-%m-%d %H:%M')"; } > "$PERSIST_TOKENS/$key"
      rm -f "$f"; matched=1
      echo "✅ Approved ONE act on '$name'. It waits until the session actually does it."
      echo "   Disarm with: bus.sh persist revoke $name"
    fi
  done
  [ -n "$matched" ] || { echo "No pending persistence request matching '$q'."; return 1; }
  return 0
}

persist_deny() {  # <name-or-key>
  local q="${1:-}" f name key matched=""
  [ -d "$PERSIST_REQUESTS" ] && for f in "$PERSIST_REQUESTS"/*; do [ -f "$f" ] || continue
    name="$(_push_field target_name "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then rm -f "$f"; matched=1; echo "Dismissed the request for '$name'."; fi
  done
  [ -n "$matched" ] || { echo "No pending persistence request matching '$q'."; return 1; }
  return 0
}

persist_revoke() {  # <name-or-key>
  local q="${1:-}" f name key matched=""
  [ -d "$PERSIST_TOKENS" ] && for f in "$PERSIST_TOKENS"/*; do [ -f "$f" ] || continue
    name="$(_push_field target_name "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then rm -f "$f"; matched=1
      echo "🔒 Revoked the approval for '${name:-$key}'."; fi
  done
  [ -n "$matched" ] || { echo "No armed approval matching '$q'."; return 1; }
  return 0
}

bus_sent() {  # [n] — did my last N messages land, and has each recipient's cursor passed them?
  # KYLE'S QUESTION: "do we need read receipts?"  THE FLEET'S ANSWER: no — you need THIS, and
  # you need it to stop short of claiming what it cannot see.
  #
  # ⚠️ THE WORD "READ" IS FORBIDDEN HERE, AND THE LABEL IS LOAD-BEARING, NOT COSMETIC.
  #
  # A watermark proves exactly ONE proposition:
  #     1. the bytes reached the recipient's cursor        <- last-seen PROVES this
  #     2. the recipient ATTENDED TO / understood it       <- it proves NOTHING
  #     3. a reply is coming                                <- it is SILENT
  #
  # We have a measured counter-example to #2 from today: a session's cursor passed a request for
  # adversarial review, and it FILED IT AS AN ANNOUNCEMENT. A receipt saying "read" would have
  # been true about the cursor and WRONG about everything the sender cared about — and worse, it
  # would have made the sender MORE confident and LESS likely to follow up.
  #
  #   image_gen's rule, and it is exactly the "root" correction applied one layer out:
  #   **"'Read' is to a watermark what 'root' was to `systemctl --user` — a true narrative with
  #     one word that claims more than the mechanism can back."**
  #
  #   **A receipt that manufactures false certainty is MORE dangerous than the ambiguity it
  #     cures — because silence at least prompts a follow-up, and a false "read" suppresses it.**
  #
  # And it is a QUERY, not a MARKER. Nobody has to tag anything, so it cannot inflate — which is
  # what kills every sender-applied label (orb_slam: "any label that costs the marker nothing and
  # buys the marker attention goes to 100%, and at 100% it carries zero information").
  local n="${1:-5}" f line ts tag seen
  local SD="$HOME/.claude/bus-state"
  if [ ! -d "$SD" ]; then
    echo "⚠️  no bus-state dir ($SD) — cannot read cursors. NOT the same as 'nobody has read'." >&2
    return 1
  fi
  echo "=== your last $n posts, and where each recipient's CURSOR stands ==="
  echo "    (cursor passed = the bytes reached them. NOT necessarily read, understood, or acted on.)"
  echo ""
  grep -aE "^## .* \[$TAG\]$" "$BUS_FILE" 2>/dev/null | tail -"$n" | while IFS= read -r line; do
    ts="$(printf '%s' "$line" | sed -E 's/^## ([0-9-]+ [0-9:]+) .*/\1/')"
    echo "  $line"
    # who was it addressed to? (the to: line directly under the header)
    local targets
    targets="$(grep -aA2 -F "$line" "$BUS_FILE" 2>/dev/null | grep -aoE '^to:[^—]*' | head -1 \
               | tr ' ' '\n' | sed -n 's/^to://p' | grep -v '^all$' | head -8)"
    if [ -z "$targets" ]; then
      echo "      (broadcast — no directed recipients)"
    else
      printf '%s\n' "$targets" | while IFS= read -r tag; do
        [ -n "$tag" ] || continue
        seen="$(cat "$SD/other:$tag.last-seen" 2>/dev/null \
                || cat "$SD/$tag.last-seen" 2>/dev/null || true)"
        if [ -z "$seen" ]; then
          printf '      %-22s ⚠️  no cursor on record — this session has NEVER checked the bus\n' "$tag"
        elif [ "$seen" \> "$ts" ] || [ "$seen" = "$ts" ]; then
          printf '      %-22s ✅ cursor PASSED (at %s)\n' "$tag" "$seen"
        else
          printf '      %-22s ⏳ NOT YET — their cursor is still at %s\n' "$tag" "$seen"
        fi
      done
    fi
    echo ""
  done
  cat <<'NOTE'
  ─────────────────────────────────────────────────────────────────────────────
  ✅ "cursor PASSED" proves the bytes reached them. It proves NOTHING about whether
     they attended to it, understood it, or intend to reply. It is rung 1, and it is
     labelled rung 1 on purpose.

  ⚠️  "NOT YET" can also mean a STALE cursor: a session that read but whose watermark
     froze (a known bug) shows as not-yet here. So even rung 1 is a LOWER BOUND on
     delivery, never an upper bound. It cannot tell you they DIDN'T get it — only that
     their cursor has not provably passed it.

  ⚠️  If you are BLOCKED waiting on a reply — don't be. Post, keep working, and let
     auto-delivery bring you the answer. A queue of blocked Claudes is the worst of
     both worlds, and a sender who does not block does not need a receipt at all.
  ─────────────────────────────────────────────────────────────────────────────
NOTE
  return 0
}

bus_waiting() {  # your OWN open asks — messages you sent that nobody has answered yet
  # KYLE'S OBSERVATION: "Claudes send msgs and sit waiting, then say they haven't gotten a reply."
  # THE FLEET'S CONVERGED DESIGN, built here as its honest core:
  #
  #   • INFERENCE, NOT A MARKER. An "ask" is inferred from STRUCTURE — a directed message
  #     (≤4 named recipients, not to:all) that contains a question. The sender self-classifying
  #     priority is ONE ESTIMATOR (93emulator: "important to me" and "urgent to you" are drawn
  #     from one distribution). Structure is the INDEPENDENT estimator, and it cannot inflate —
  #     orb_slam: "any sender-applied label costs the marker nothing and goes to 100%."
  #     (An explicit `ask:` override for cases inference gets wrong is DEFERRED until there is
  #     evidence inference is insufficient — building the inflatable thing speculatively is the
  #     mistake, and inference-as-default is what everyone agreed on.)
  #
  #   • CLOSE IS DERIVED, NEVER DECLARED. A thread closes when the recipient POSTS A REPLY that
  #     addresses you back — an observable act with content. Not a bare `close:` flag (qualcomm:
  #     "closing must cost exactly what answering costs, or it is the Class IX checkbox").
  #
  #   • IT IS A QUERY (like `sent`), so nobody tags anything and it cannot become noise.
  #
  #   • STALENESS DECAYS: asks older than the window are "gone quiet," not "actively blocked" —
  #     an alarm that never clears trains you to ignore it.
  #
  # ⚠️ AND THE REAL FIX IS BEHAVIOURAL, STATED FIRST: a session should NOT BLOCK on a bus reply.
  # Post, keep working, let auto-delivery bring the answer. This tool is for GLANCING at what is
  # outstanding — not for waiting on it. A sender who does not block does not need it.
  local hours="${1:-12}"
  BUS_FILE="$BUS_FILE" MY_TAG="$TAG" WINDOW_H="$hours" python3 - <<'PYEOF'
import os, re, time

path = os.environ["BUS_FILE"]
me   = os.environ["MY_TAG"]
win  = float(os.environ.get("WINDOW_H") or 12) * 3600

def plain(t):
    t = t.strip().strip("[]")
    if t.lower().startswith("other:"): t = t[6:]
    return t.lower()

me_p = plain(me)

# The human (operator) NEVER posts a bus reply — Kyle reads through the UI and ACTS; his
# "answer" is action in the world, never a bus message. So his edge could never close by the
# reply rule and would dangle as a permanent false "open ask" until the decay window (image_gen
# found this by dogfooding the tool). A human is a CC you INFORM, not a peer thread you are
# blocked behind — you don't wait ON Kyle the way you wait on a peer. Exclude him from the
# inferred waiting-on set entirely. (This is the same rung-split as `sent`: for a non-posting
# recipient, "reply" is the wrong close signal — and for the human it never arrives at all.)
NONPOSTING = {"operator", "human", "kyle"}

HDR = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \[([^\]]+)\]\s*$')
TO  = re.compile(r'\bto:(\S+)')

def epoch(ts):
    try: return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M"))
    except Exception: return 0.0

# parse every message: (epoch, sender_plain, {recipient_plains}, first_body_line)
msgs, cur = [], None
try:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = HDR.match(line)
            if m:
                cur = {"e": epoch(m.group(1)), "ts": m.group(1),
                       "snd": plain(m.group(2)), "to": set(), "first": None, "body": []}
                msgs.append(cur)
            elif cur is not None:
                if line.strip():
                    cur["body"].append(line)
                if cur["first"] is None and line.strip():
                    cur["first"] = line
                    head = line.split("—", 1)[0]
                    if "to:" in head:
                        cur["to"] = {plain(x) for x in TO.findall(head)}
except OSError:
    pass

now = time.time()
# MY asks: I sent it, it's directed (1..4 real recipients, not to:all), it asks a question,
# and it is within the window.
my_asks = []
for i, m in enumerate(msgs):
    if m["snd"] != me_p: continue
    if now - m["e"] > win: continue
    tgt = {t for t in m["to"] if t not in ("all",)}
    if not (1 <= len(tgt) <= 4): continue
    if "?" not in "\n".join(m.get("body", [])): continue
    # who, of the recipients, has NOT replied since? (a reply = they addressed me back after m)
    open_on = []
    for r in sorted(tgt):
        if r == me_p: continue
        if r in NONPOSTING: continue   # the human never posts a reply; his edge can't close
        replied = any(later["snd"] == r and me_p in later["to"] and later["e"] >= m["e"]
                      for later in msgs[i+1:])
        if not replied:
            open_on.append(r)
    if open_on:
        my_asks.append((m, open_on))

if not my_asks:
    print("=== no open asks ===")
    print(f"    (nothing you asked in the last {int(win/3600)}h is still unanswered — or you asked nobody a question.)")
else:
    print(f"=== your OPEN asks (unanswered, last {int(win/3600)}h) — oldest first ===")
    print("    close = the recipient REPLIES. This is inferred from structure, not a marker.")
    print()
    for m, open_on in sorted(my_asks, key=lambda x: x[0]["e"]):
        age = (now - m["e"]) / 3600
        print(f"  ⏳ {m['ts']}  waiting on: {', '.join(open_on)}  ({age:.0f}h)")
        body = (m["first"] or "").split("—", 1)[-1].strip()
        print(f"       {body[:96]}")
        print()
print("  ──────────────────────────────────────")
print("  These are INFERRED (a directed message with a '?'). \"Answered\" means the recipient")
print("  posted a reply addressing you — not that they read it. And this is a GLANCE, not a")
print("  reason to block: post, keep working, let auto-delivery bring the reply.")
PYEOF
  return 0
}

push_list() {
  local f any="" now exp
  now="$(date +%s)"
  [ -d "$PUSH_REQUESTS" ] && for f in "$PUSH_REQUESTS"/*; do [ -f "$f" ] || continue; any=1
    echo "  ⏳ $(_push_field repo_name "$f")  — waiting for you (requested $(_push_field created "$f"))"
  done
  # The state that used to be invisible: you said yes, and it hasn't been used yet.
  [ -d "$PUSH_TOKENS" ] && for f in "$PUSH_TOKENS"/*; do [ -f "$f" ] || continue
    exp="$(_push_token_expiry "$f")"
    [ "$now" -lt "$exp" ] || { rm -f "$f"; continue; }   # expired: reap it quietly
    any=1
    echo "  ✅ $(_push_field repo_name "$f")  — APPROVED, waiting for the session to push ($(( (exp - now) / 3600 ))h left)"
  done
  [ -z "$any" ] && echo "No pending push approvals."
  return 0
}
push_approve() {  # <repo-name-or-key>
  local q="${1:-}" f name key repo matched=""
  [ -n "$q" ] || { echo "usage: bus.sh push approve <repo-name>"; return 2; }
  mkdir -p "$PUSH_TOKENS"
  [ -d "$PUSH_REQUESTS" ] && for f in "$PUSH_REQUESTS"/*; do [ -f "$f" ] || continue
    name="$(_push_field repo_name "$f")"; repo="$(_push_field repo "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then
      { echo "expires=$(( $(date +%s) + PUSH_TTL ))"
        echo "repo=$repo"; echo "repo_name=$name"
        echo "approved=$(date +%s)"
        echo "approved_at=$(date '+%Y-%m-%d %H:%M')"; } > "$PUSH_TOKENS/$key"
      rm -f "$f"; matched=1
      echo "✅ Approved ONE push to '$name'. It waits until the session actually pushes (up to $(( PUSH_TTL / 3600 ))h) — re-run it whenever. Disarm with: bus.sh push revoke $name"
    fi
  done
  if [ -z "$matched" ]; then echo "No pending push request matching '$q'. (bus.sh push list)"; return 1; fi
  return 0
}
push_deny() {  # <repo-name-or-key>
  local q="${1:-}" f name key matched=""
  [ -d "$PUSH_REQUESTS" ] && for f in "$PUSH_REQUESTS"/*; do [ -f "$f" ] || continue
    name="$(_push_field repo_name "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then rm -f "$f"; matched=1; echo "Dismissed the push request for '$name'."; fi
  done
  if [ -z "$matched" ]; then echo "No pending push request matching '$q'."; return 1; fi
  return 0
}
PUSH_PROPOSALS="$COORD_ROOT/push-proposals"

# ---------------------------------------------------------------------------
# PUSH PROPOSAL — "is this the right MOMENT to push?", which is a different
# question from "may I push?", and the gate cannot answer it.
#
# The gate protects the REPO: nothing lands without Kyle's tap. But his inbox only
# ever showed him `claude-connect — git push origin main`, which says nothing about
# what is in the commits, whether the session thinks the work is finished, or what
# it would do instead. Approving that is a rubber stamp on a decision he never made
# — and a session that "just pushes and lets the gate sort it out" has quietly
# appointed ITSELF the judge of whether the work was ready. That is the push-happy
# behaviour Kyle does not want, and the gate does not protect him from it.
#
# So: propose. Say what you would push, why now, and what you would do instead.
# Kyle answers ONE question, with the context, from wherever he is — and his answer
# ARMS THE GRANT, so there is no second rubber-stamp tap afterwards.
#
#   bus.sh push propose - <<'EOF'
#   why: the /msg-check storm fix is done and tested (230 green)
#   else: keep digging into clearing the already-queued checks
#   else: pause and read the 146 unread bus messages first
#   EOF
#
# `why:` is your case for pushing NOW. Each `else:` is a real alternative you are
# weighing — Kyle can pick one instead, and you'll be told which. Commits are
# attached automatically; do not paste them.
push_propose() {
  local body key repo name commits why="" alts=() line
  repo="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")"
  name="$(basename "$repo")"
  key="$(printf '%s' "$repo" | tr '/ ' '__' | sed 's/^_*//')"

  # STDIN only, for the same reason `send` is stdin-only: an argument goes through
  # the caller's shell, which command-substitutes backticks, and the words vanish.
  case "${1:-}" in
    ''|-) : ;;
    *) echo "usage: bus.sh push propose - <<'EOF' ... EOF   (reads stdin)" >&2; return 2 ;;
  esac
  body="$(cat)"
  [ -n "$body" ] || { echo "propose: nothing on stdin" >&2; return 2; }

  while IFS= read -r line; do
    case "$line" in
      why:*)  why="${line#why:}";  why="${why# }" ;;
      else:*) alts+=("$(printf '%s' "${line#else:}" | sed 's/^ //')") ;;
    esac
  done <<< "$body"
  [ -n "$why" ] || { echo "propose: needs a 'why:' line — your case for pushing NOW" >&2; return 2; }

  # EXACTLY what would go up — no more, and never a stand-in.
  #
  # This first fell back to `git log -5` when there was nothing unpushed, which showed Kyle
  # five commits that were ALREADY on the remote as if they were the payload. A card that
  # misrepresents what you are approving is worse than no card: it is a confident lie on the
  # one screen whose entire job is to tell you what you're agreeing to.
  commits="$(git log --oneline @{u}..HEAD 2>/dev/null | head -12)"
  if [ -z "$commits" ]; then
    echo "propose: nothing to push — HEAD is already on the remote. Commit first." >&2
    return 2
  fi

  mkdir -p "$PUSH_PROPOSALS" 2>/dev/null || true
  { echo "repo=$repo"; echo "repo_name=$name"; echo "cwd=$PWD"
    echo "why=$why"
    for a in "${alts[@]}"; do echo "alt=$a"; done
    printf 'commits=%s\n' "$(printf '%s' "$commits" | tr '\n' '|')"
    echo "epoch=$(date +%s)"; echo "created=$(date '+%Y-%m-%d %H:%M')"
  } > "$PUSH_PROPOSALS/$key" 2>/dev/null || true

  echo "📤 Proposed a push of '$name' to Kyle — he'll see what's in it and why, and can pick"
  echo "   an alternative instead. If he says push, the approval is already armed: just push."
  echo "   Do NOT push until you hear back."
}

push_withdraw() {  # pull back your OWN proposal when the ground moves under it
  # A proposal is a PHOTOGRAPH of what you believed when you filed it. It does not update, it
  # does not know you changed your mind, and it will sit in Kyle's queue looking perfectly
  # valid while you retract its premise on the bus.
  #
  # That is exactly what happened: ollama_95_neutron proposed a push at 09:56, retracted the
  # architecture rule behind it at 10:55, and the proposal stayed live — Kyle would have been
  # approving a belief its own author had already abandoned. The retraction machinery existed
  # for MESSAGES and not for PROPOSALS, which is the same bug one layer up.
  local repo key name
  repo="$(git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD")"
  name="$(basename "$repo")"
  key="$(printf '%s' "$repo" | tr '/ ' '__' | sed 's/^_*//')"
  if [ -f "$PUSH_PROPOSALS/$key" ]; then
    rm -f "$PUSH_PROPOSALS/$key"
    echo "↩️  Withdrew your push proposal for '$name'. Kyle will no longer see it."
    echo "   Re-propose when the ground stops moving."
  else
    echo "No open push proposal for '$name'."
    return 1
  fi
}

push_revoke() {  # <repo-name-or-key> — take back an approval you already gave
  # The counterweight to a 24h grant. Changed your mind, or approved the wrong repo?
  # Disarm it before the agent uses it. Without this, a long-lived token would be a
  # decision you cannot unmake, and that is not a control.
  local q="${1:-}" f name key matched=""
  [ -n "$q" ] || { echo "usage: bus.sh push revoke <repo-name>"; return 2; }
  [ -d "$PUSH_TOKENS" ] && for f in "$PUSH_TOKENS"/*; do [ -f "$f" ] || continue
    name="$(_push_field repo_name "$f")"; key="$(basename "$f")"
    if [ "$name" = "$q" ] || [ "$key" = "$q" ]; then rm -f "$f"; matched=1
      echo "🔒 Revoked the approval for '${name:-$key}'. The next push will be gated again."
    fi
  done
  if [ -z "$matched" ]; then echo "No armed approval matching '$q'."; return 1; fi
  return 0
}

# ---------------------------------------------------------------------------
# SERVICE CLAUDES — a session that does work FOR other sessions (image_gen).
#
# Kyle's realisation: image_gen is *exactly* an EVK — single-holder, one job at a
# time, contended, needs a queue — except the resource DOES the work rather than
# being used by the requester. So the lease inverts: not "I have taken this" but
# "I am currently serving X".
#
# Fire-and-forget: a requester posts a job and goes straight back to its own work.
# When the job is done the service posts the result back, and directed-mail
# auto-delivery wakes the requester. Nobody blocks waiting in line.
#
# The human is not a queue entry. Kyle talks to a service directly, so "make me
# first" is a HOLD on the queue: finish the current job, then wait for me instead
# of pulling the next one. `svc hold` / `svc resume`.
#
#   svc request <svc> <text…>   queue a job (any session)         -> prints position
#   svc next    <svc>           service claims the next job       -> prints it
#   svc done    <svc> [note…]   finish + return result to requester
#   svc status  <svc>           who's being served, who's waiting
#   svc hold    <svc> [why…]    Kyle claims the NEXT opening
#   svc resume  <svc>           Kyle done — resume the queue
#   svc cancel  <svc> <id>      drop a queued job
# ---------------------------------------------------------------------------
SVC_ROOT="$COORD_ROOT/services"

_svc_setup() {  # <name>
  SVC_NAME="$1"
  [ -n "$SVC_NAME" ] || { echo "usage: bus.sh svc <verb> <service> …" >&2; return 2; }
  SVC_DIR="$SVC_ROOT/$SVC_NAME"
  SVC_JOBS="$SVC_DIR/jobs"
  SVC_QUEUE="$SVC_DIR/queue"
  SVC_SERVING="$SVC_DIR/serving"
  SVC_HOLD="$SVC_DIR/hold"
  SVC_LOCK="$SVC_DIR/.lock"
  mkdir -p "$SVC_JOBS" 2>/dev/null || true
  : > "$SVC_LOCK" 2>/dev/null || true
  return 0
}

_svc_field() { sed -n "s/^$1=//p" "$2" 2>/dev/null | head -1; }

_svc_request() {  # <name> <text…>
  _svc_setup "$1" || return 2; shift
  local text="$*"
  [ -n "$text" ] || { echo "usage: bus.sh svc request <service> <what you need>" >&2; return 2; }
  local id pos
  id="$(date +%s)-$$-$RANDOM"
  (
    flock 9
    { echo "id=$id"; echo "requester=$TAG"; echo "text=$text"
      echo "epoch=$(date +%s)"; echo "created=$(date '+%Y-%m-%d %H:%M')"; } > "$SVC_JOBS/$id"
    echo "$id" >> "$SVC_QUEUE"
  ) 9>"$SVC_LOCK"
  pos="$(grep -c . "$SVC_QUEUE" 2>/dev/null || echo 1)"
  # Tell the service. Directed mail => auto-delivery wakes it if it's parked.
  { echo ""; echo "## $(date '+%Y-%m-%d %H:%M') [$TAG]"; echo ""
    echo "to:$SVC_NAME — [$TAG] 🧾 JOB REQUEST (queue position $pos): $text"
    echo "(Run \`/svc-next $SVC_NAME\` when you're free. Reply with \`/svc-done $SVC_NAME <result>\` and I'll be woken automatically — I'm NOT waiting on you.)"
  } >> "$BUS_FILE"
  echo "Queued for [$SVC_NAME] at position $pos (job $id). You are NOT blocked — carry on; you'll be woken when the result lands."
}

_svc_next() {  # <name>
  _svc_setup "$1" || return 2
  if [ -s "$SVC_HOLD" ]; then
    echo "⏸  PAUSED — Kyle claimed the next opening ($(cat "$SVC_HOLD")). Talk to him; run 'bus.sh svc resume $SVC_NAME' when he's done."
    return 0
  fi
  if [ -s "$SVC_SERVING" ]; then
    echo "Already serving $(_svc_field requester "$SVC_SERVING"): $(_svc_field text "$SVC_SERVING")"
    echo "Finish it with: bus.sh svc done $SVC_NAME <result>"
    return 0
  fi
  local id job
  (
    flock 9
    id="$(head -1 "$SVC_QUEUE" 2>/dev/null)"
    [ -n "$id" ] || exit 0
    sed -i '1d' "$SVC_QUEUE" 2>/dev/null || true
    cp "$SVC_JOBS/$id" "$SVC_SERVING" 2>/dev/null || true
    { echo "started=$(date +%s)"; } >> "$SVC_SERVING"
  ) 9>"$SVC_LOCK"
  if [ ! -s "$SVC_SERVING" ]; then echo "Queue is empty — nothing to do."; return 0; fi
  echo "▶ NOW SERVING [$(_svc_field requester "$SVC_SERVING")]"
  echo "   request: $(_svc_field text "$SVC_SERVING")"
  echo "   when finished: bus.sh svc done $SVC_NAME <result / where you put it>"
}

_svc_done() {  # <name> [result…]
  _svc_setup "$1" || return 2; shift
  local result="$*" req text
  [ -s "$SVC_SERVING" ] || { echo "Not serving anything right now."; return 0; }
  req="$(_svc_field requester "$SVC_SERVING")"
  text="$(_svc_field text "$SVC_SERVING")"
  : > "$SVC_SERVING"
  # Return the result. Directed => the requester is auto-woken. Fire-and-forget, closed.
  { echo ""; echo "## $(date '+%Y-%m-%d %H:%M') [$TAG]"; echo ""
    echo "to:$(_coord_plain "$req") — [$TAG] ✅ JOB DONE — re: $text"
    echo "${result:-(no note)}"
  } >> "$BUS_FILE"
  local left; left="$(grep -c . "$SVC_QUEUE" 2>/dev/null || echo 0)"
  echo "Done, and [$req] has been told (they'll be woken automatically)."
  if [ -s "$SVC_HOLD" ]; then
    echo "⏸  Kyle has claimed the next opening — stop here and talk to him."
  else
    echo "$left job(s) still queued. Run 'bus.sh svc next $SVC_NAME' to take the next."
  fi
}

_svc_status() {  # [name]
  if [ -z "${1:-}" ]; then
    [ -d "$SVC_ROOT" ] || { echo "No services registered."; return 0; }
    for d in "$SVC_ROOT"/*/; do [ -d "$d" ] || continue; _svc_status "$(basename "$d")"; echo; done
    return 0
  fi
  _svc_setup "$1" || return 2
  echo "=== service [$SVC_NAME] ==="
  if [ -s "$SVC_HOLD" ]; then echo "  ⏸  HELD for Kyle: $(cat "$SVC_HOLD")"; fi
  if [ -s "$SVC_SERVING" ]; then
    echo "  ▶ serving [$(_svc_field requester "$SVC_SERVING")]: $(_svc_field text "$SVC_SERVING")"
  else
    echo "  ▶ idle (serving nobody)"
  fi
  local n=0
  if [ -s "$SVC_QUEUE" ]; then
    echo "  ⏳ queue:"
    while read -r id; do
      [ -n "$id" ] || continue; n=$((n+1))
      echo "     $n. [$(_svc_field requester "$SVC_JOBS/$id")] $(_svc_field text "$SVC_JOBS/$id")"
    done < "$SVC_QUEUE"
  else
    echo "  ⏳ queue: empty"
  fi
}

_svc_hold() {  # <name> [why…]
  _svc_setup "$1" || return 2; shift
  echo "${*:-Kyle wants the next slot}" > "$SVC_HOLD"
  echo "🙋 You have the NEXT opening on [$SVC_NAME]. It will finish its current job, then wait for you."
  { echo ""; echo "## $(date '+%Y-%m-%d %H:%M') [operator]"; echo ""
    echo "to:$SVC_NAME — [operator] 🙋 Kyle has claimed your NEXT opening. Finish what you're on, then STOP and wait for him — do not pull the next queued job. He'll release you with /svc-resume."
  } >> "$BUS_FILE"
}

_svc_resume() {  # <name>
  _svc_setup "$1" || return 2
  rm -f "$SVC_HOLD"
  echo "▶ [$SVC_NAME] released — it may take queued jobs again."
  { echo ""; echo "## $(date '+%Y-%m-%d %H:%M') [operator]"; echo ""
    echo "to:$SVC_NAME — [operator] ▶ Released. Carry on with the queue: run /svc-next $SVC_NAME."
  } >> "$BUS_FILE"
}

_svc_cancel() {  # <name> <id>
  _svc_setup "$1" || return 2
  local id="${2:-}"
  [ -n "$id" ] || { echo "usage: bus.sh svc cancel <service> <job-id>" >&2; return 2; }
  ( flock 9; grep -v "^$id$" "$SVC_QUEUE" > "$SVC_QUEUE.tmp" 2>/dev/null || true
    mv "$SVC_QUEUE.tmp" "$SVC_QUEUE" 2>/dev/null || true; rm -f "$SVC_JOBS/$id" ) 9>"$SVC_LOCK"
  echo "Cancelled $id."
}

svc_dispatch() {
  local verb="${1:-status}"; shift 2>/dev/null || true
  case "$verb" in
    request) _svc_request "$@" ;;
    next)    _svc_next "$@" ;;
    done)    _svc_done "$@" ;;
    status)  _svc_status "$@" ;;
    hold)    _svc_hold "$@" ;;
    resume)  _svc_resume "$@" ;;
    cancel)  _svc_cancel "$@" ;;
    *) echo "usage: bus.sh svc {request|next|done|status|hold|resume|cancel} <service> …" >&2; return 2 ;;
  esac
}


# ---------------------------------------------------------------------------
# THE FLEET REGISTRY — every shared asset is a self-describing NODE.
#
# Two problems this fixes.
#
#  1. Nothing was ever *registered*. Resources and services sprang into existence
#     on first use, which is exactly how `orin` drifted away from `orin-agx` TWICE —
#     a live lease and a queue stranded on a phantom twin of the same board.
#
#  2. A node told you nothing. Reserve a board and you got… a lease. How do you
#     reach it? What's the toolchain? What's the trap that costs a day? That
#     knowledge lived in one session's context and died there — so every new Claude
#     had to ask Kyle. He was the courier for "how do I ssh to the Orin?" exactly as
#     he'd been the courier for messages.
#
# So an asset card travels WITH the asset: `reserve` hands it to you the moment you
# take the board. `gotchas` is the sleeper — when qualcomm learns "the pip neutron
# converter is broken, use the standalone eIQ SDK", the next Claude inherits it.
#
# Cards are markdown, so a Claude can just edit the file with its normal tools.
# They live in ~/.claude/bus-state/registry/ — LOCAL ONLY. Never the repo, never
# posted to the bus. Reference where credentials live; do not inline them.
#
#   asset new <name> [kind]   create a card from a template (prints the path)
#   asset info <name>         print the card
#   asset path <name>         print the file path (so you can edit it)
#   asset list | catalog      the fleet directory — every asset, one line each
# ---------------------------------------------------------------------------
REGISTRY="${BUS_STATE_DIR:-$HOME/.claude/bus-state}/registry"

_asset_check() {  # <card-file> — is this card TRUSTWORTHY? Prints warnings; rc=1 if broken.
  # A half-written card reads EXACTLY like a whole one. A Claude that crashed mid-edit leaves
  # a file that parses, renders, and lies by omission — and the reader has no way to know.
  # So every path that SHOWS a card checks it first, and says so out loud.
  local f="$1" bad=0 last
  [ -s "$f" ] || return 1
  # Truncation: a card that ends mid-sentence (no trailing blank/heading) is a crash artifact.
  last="$(tail -c 1 "$f" 2>/dev/null)"
  if [ -n "$last" ]; then
    echo "  ⚠️  CARD MAY BE TRUNCATED — it does not end with a newline. A Claude may have died"
    echo "      mid-write. Treat every claim here as UNVERIFIED until someone re-reads it."
    bad=1
  fi
  grep -q '^class:[[:space:]]*\(interrogable\|opaque\)[[:space:]]*$' "$f" || {
    echo "  ⚠️  NO \`class:\` — this asset has never been declared interrogable or opaque."
    echo "      Until it is, a dead owner means QUARANTINE. That is the honest default."
    bad=1
  }
  grep -qi '^## open questions' "$f" || {
    echo "  ⚠️  No \`## open questions\` section. A card with no stated gaps looks IDENTICAL to"
    echo "      a card whose gaps nobody wrote down. Add what you know you do NOT know."
    bad=1
  }
  local drilled; drilled="$(_asset_hdr drilled "$f")"
  case "$drilled" in
    ''|*never*|*'('*)
      echo "  ⚠️  NEVER DRILLED. **A card that has never onboarded anyone is decoration.** Nobody"
      echo "      has confirmed a cold session can actually USE this. Run: bus.sh asset drill $(basename "${f%.md}")"
      bad=1 ;;
  esac
  return $bad
}

_asset_file() { printf '%s/%s.md' "$REGISTRY" "$1"; }
_asset_hdr()  { sed -n "s/^$1:[[:space:]]*//p" "$2" 2>/dev/null | head -1; }

_asset_drill() {  # <name> — set up a COLD-SESSION drill of this card
  # "A card that has never onboarded anyone is decoration."
  #
  # The author reading their own card and thinking "yes, that's complete" is THE MOCK. It
  # proves the card REACTS TO THEIR MEMORY. It never proves a stranger can USE it — and only
  # the second claim matters. (qualcomm's ARA240 rule, aimed at documentation, where it hurts
  # more, because a card has no exit code and cannot fail loudly by itself.)
  #
  # So: stage a scratch dir containing NOTHING BUT THE CARD, and a task. Launch a session
  # there with no project context and no history. Every question it has to ask, and everything
  # it gets wrong, is a MEASURED hole — not an opinion about the card.
  local name="${1:-}" f dir
  [ -n "$name" ] || { echo "usage: bus.sh asset drill <name>" >&2; return 2; }
  f="$(_asset_file "$name")"
  [ -s "$f" ] || { echo "No card for '$name'." >&2; return 1; }

  dir="$HOME/.claude/drills/$name-$(date +%Y%m%d-%H%M)"
  mkdir -p "$dir" || return 1
  cp "$f" "$dir/CARD.md"
  cat > "$dir/TASK.md" <<'TASK'
# Card drill — you are a COLD session. This is deliberate.

You have **no project context, no history, and no colleagues to ask.** You have exactly one
document: `CARD.md`. That is the whole point.

**Your job is NOT to succeed. It is to FAIL HONESTLY and record where.**

1. Read `CARD.md`. Then, using **only** what it tells you, write down step by step how you
   would take a **first correct measurement** on this asset.
2. **Every single time you would have to ask someone, guess, or go and read something else —
   STOP and write it down in `HOLES.md`.** That is the finding. Do not paper over it. Do not
   infer it from the model name. Do not use knowledge you brought with you — you are standing
   in for a session that has none.
3. If a step would touch real hardware, **do not run it.** Say what you would run and what you
   expect. This is a documentation test, not a hardware test.
4. When you are done, write `HOLES.md`:
     - **BLOCKERS** — things the card does not say that you cannot proceed without.
     - **TRAPS** — things the card says that would lead you to do the WRONG thing.
       *(These are worth more than blockers. A blocker stops you. A trap lets you continue,
       confidently, and be wrong — which is the failure this whole fleet exists to catch.)*
     - **STALE** — claims with no date/version stamp that you would not dare trust.
     - **UNANSWERABLE** — anything you could not even tell whether it was missing.

**A drill that finds nothing is not a pass. It is a drill that did not run.** Say so if the
card genuinely covers everything — but be honest that you looked.
TASK
  echo "🎯 Drill staged: $dir"
  echo "   Launch a COLD session there — no project context, nothing but the card:"
  echo "     scripts/claude-tracked drill-$name --dir $dir"
  echo "   Then record what it found:"
  echo "     bus.sh asset drilled $name \"3 blockers, 1 trap: the DTB note is instance-only\""
}

_asset_drilled() {  # <name> "<what the drill found>"
  local name="${1:-}" note="${2:-}" f tmp
  [ -n "$name" ] && [ -n "$note" ] || { echo 'usage: bus.sh asset drilled <name> "<what it found>"' >&2; return 2; }
  f="$(_asset_file "$name")"
  [ -s "$f" ] || { echo "No card for '$name'." >&2; return 1; }
  tmp="$f.tmp.$$"
  # Atomic: a crash mid-write must never leave a HALF-CARD, which reads exactly like a whole
  # one. Every other coord file has done this from the start; the cards never did, and they
  # are the thing that matters most.
  sed "s|^drilled:.*|drilled: $(date '+%Y-%m-%d') — $note|" "$f" > "$tmp" && mv -f "$tmp" "$f"
  echo "📝 Recorded. $name drilled $(date '+%Y-%m-%d'): $note"
  echo "   Now FIX the holes. A drill you don't act on is a drill you didn't run."
}

_asset_new() {  # <name> [kind]
  local name="${1:-}" kind="${2:-board}" f
  [ -n "$name" ] || { echo "usage: bus.sh asset new <name> [board|gpu|service]" >&2; return 2; }
  mkdir -p "$REGISTRY"
  f="$(_asset_file "$name")"
  if [ -s "$f" ]; then echo "Card already exists: $f"; return 0; fi
  cat > "$f" <<CARD
# $name
kind: $kind
aliases:
summary: (one line — what is this?)

# ⚠️ REQUIRED. This single field decides what may be done to the resource when its
# owner dies, so it is not optional and it is not a guess.
#
#   interrogable — the resource can NAME ITS OWN TENANTS. Ask it, it answers.
#                  (a GPU: `nvidia-smi --query-compute-apps` lists every pid + bytes)
#                  ⇒ a dead owner's process may be REAPED. Killing it genuinely cleans
#                    the resource, the same instant, and it is reversible.
#
#   opaque       — you CANNOT ask it who is using it. There is no ledger on the device;
#                  every host-side signal is a PROXY (fuser on a serial line, a heartbeat).
#                  (any EVK, an Orin over ssh, anything behind a serial cable)
#                  ⇒ a dead owner's board is QUARANTINED. Never reaped, never auto-freed.
#
# WHY THE POLICY INVERTS (and it is the opposite of what you would guess — you would
# expect to be MORE aggressive on the scarce, exclusive board):
#
#   **A dead GPU tenant leaves a mess. A dead board tenant leaves a BOOBY TRAP.**
#
# Kill a GPU process and the card is clean instantly. A board keeps whatever state it was
# left in — half-written flash, a held debug halt, a changed boot source — and NO probe on
# this host can see any of it. Freeing it does not clean it; it relocates the corruption
# onto the next occupant, who debugs a phantom.
#
# MEASURED, 2026-07-12: ollama_95_neutron released imx95-frdm CLEANLY and still had to warn
# the fleet IN PROSE that the board now boots a different device tree. The lease read FREE.
# `fuser /dev/neutron0` was empty. Every host-side check said clean. It was not.
#
# And the trap has TWO jaws: a "restore to a known-good baseline" reaper would have reverted
# that board to the STOCK DTB — which does not clean it, it SILENTLY BREAKS it. The stock
# 960 MiB CMA pool can never satisfy the NPU's 2 GiB request, so it logs `hardware init
# failed` at a severity nobody reads and runs the whole graph on the CPU at a plausible
# latency. That exact failure is why this fleet believed for MONTHS that "Neutron is
# CNN-only".  ⇒ verify asks "is it KNOWN?", never "is it STOCK?"
class: (interrogable | opaque)

# Prove the resource is in a KNOWN state. Required before an `opaque` asset may ever be
# handed on automatically; until it exists, a dead owner means quarantine and a human.
#
# It must PRESENCE-check, not activity-check: an idle process merely HOLDING a device adds
# ZERO load, and a load-average gate cannot see it. (That is the original catastrophe above.)
#
# ⚠️ AND A MOCK IS NOT A NEGATIVE TEST. This rule cost us a live false-negative and it is the
# sharpest thing in this template:
#
#   ollama wrote an ARA240 presence check, negative-tested it by FORCING the refcount to 1,
#   and watched it fire. The script logic was correct. qualcomm then ran it against a REAL
#   held accelerator — 500 confirmed inferences — and the refcount read **0 in 100% of
#   samples.** The tenant reaches the device by mmap'ing the PCI BAR, which never touches the
#   module use-count the check was reading. The guard would have printed **"✅ free"** on a
#   board running inference at full tilt.
#
#   The mock proved the script REACTS TO THE SIGNAL. It never proved A REAL TENANT PRODUCES
#   THE SIGNAL. Those are different claims and only the second one matters.
#
#   ⇒ **A guard negative-tested only against a mock is decoration until a real tenant trips
#     it.** Go and hold the thing. Watch the check fire. Anything less is an unaudited claim
#     wearing a passing test.
#
# And when no host-side signal can distinguish idle from busy — which is what qualcomm found
# here — the honest verify does NOT invent one. It says "cannot tell → quarantine". **A check
# that cannot fire is worse than no check**, because it is a green light with nothing behind it.
verify: (path to a script that exits 0 = KNOWN, non-zero = do not trust any measurement)

# ⚠️ A CARD THAT HAS NEVER ONBOARDED ANYONE IS DECORATION.
#
# You reading your own card and thinking "yes, that's complete" is THE MOCK. A cold session
# successfully USING it is the real tenant tripping the signal. (qualcomm's ARA240 rule, aimed
# at documentation — where it hurts more, because a card has no exit code.)
#
# THE DRILL:  bus.sh asset drill <name>
#   Spawn a session with NO project context and NOTHING BUT THIS CARD. Give it a real task on
#   the asset. **Every question it has to ask, and everything it gets wrong, is a HOLE.**
#   Not an opinion about the card — a MEASURED hole.  Then: bus.sh asset drilled <name> "..."
drilled: (never — run `bus.sh asset drill <name>`)

## open questions
# ⚠️ WRITE THE QUESTION *BEFORE* YOU CHASE IT. NOT AFTER YOU ANSWER IT.
#
# You cannot persist an answer you never got. **You CAN persist the question** — and the
# question is most of the value. If you die mid-chase, the chase survives.
#
# A card with no stated gaps looks IDENTICAL to a card whose gaps nobody wrote down. Same
# green light with nothing behind it that has bitten every tool on this fleet.
#
# The bar, and it is ollama's:
#   "I am not predicting N is broken. I am saying I HAVE NO RIGHT TO SAY IT ISN'T."
#
# And rt1180's disease, which is exactly what this section exists to prevent:
#   "A correctly-flagged gap that you stop thinking about BECAUSE you flagged it. The flag
#    discharges the anxiety and the gap stays. I flagged it in ONE row and it was a gap in
#    TWELVE. Naming a gap where you first met it is not the same as understanding its extent."
#
# For each: what you don't know · what you ASSUMED and why that assumption is load-bearing ·
# what experiment would settle it.

## access
(How does a Claude actually reach it? ssh / serial device + baud / IP / how to power-cycle.
 Do NOT inline passwords — say where the credential lives.
 ⚠️ PIN SERIAL DEVICES TO /dev/serial/by-id/… — `ttyACM*` numbering is NOT stable across a
 replug, and a reaper acting on a guessed device node acts on the WRONG BOARD.)

## setup
(Toolchain, env, how to flash/deploy, anything needed before first use.)

## gotchas
(THE MOST VALUABLE SECTION. The test is not "what works" — it is:
 **what would a competent Claude reasonably ASSUME here, and be WRONG about?**
 Apply that test to the inferences your sentence INVITES, not just the facts it
 asserts — a sentence where every clause is true can still teach the wrong thing.
 The flag that looks right and is slower. The number that looks portable and isn't.
 If your finding RETRACTS an earlier claim, carry the retraction, not the claim.)

 ⚠️ MARK EVERY CLAIM: **MEASURED** or **INFERRED**. If you inferred it, name what
 would falsify it. Most of what bites this fleet is an inference that arrived
 pre-attached to a real measurement, which is what makes it feel earned.

 ⚠️ THREE CLASSES OF FACT, THREE DIFFERENT DEATHS. Never mix them unlabelled.

   **MODEL/SILICON** — arithmetic on a datasheet. "Q6 ridge = 20.0 op/B". Does NOT rot.
   **TOOLCHAIN**     — ROTS, on a timer. Needs a version + date stamp (below).
   **INSTANCE**      — dies with THE OBJECT. "this board boots the neutron DTB", "CmaTotal is
                       4.94 GiB". True of THE UNIT ON THE DESK, not of the model.

 ⚠️ A CORRECTION TO MY OWN EARLIER ADVICE, WHICH WAS WRONG:
   I told this fleet "silicon facts are durable — they don't rot." **True of a MODEL. FALSE of
   an INVENTORY.** Swap in an identical-model EVK from a different purchase, or one with a
   different chip stepping, and every INSTANCE fact here becomes a lie about an object that no
   longer exists — **and not one word of the text changes.**
   A different model is caught by the name. A broken board is caught by `verify:`.
   **An identical model, different unit, passes every check we have.** It is the purest trap
   this fleet has produced. Until a card carries a FINGERPRINT of the physical object, treat
   every INSTANCE claim as unverified after any hardware change.

 ⚠️ SILICON vs TOOLCHAIN half-lives — "Q6 ridge = 20.0 op/B" is arithmetic on a datasheet:
 it does not rot.
 "CUTLASS has no SM120 int8 template" rotted in 11 weeks. So:
   **every toolchain gotcha states WHEN it was observed, WITH WHAT VERSION, and what
   would re-verify it.** A toolchain claim without a version+date stamp is a landmine
   with a timer: the tool told you the truth and then the truth EXPIRED. No retraction
   fires, because nobody made an error — and a stale fact looks IDENTICAL to a fresh
   one, so you cannot catch it by re-measuring. It re-measures clean.

 ⚠️ CO-AUTHORING: when you add a section to someone else's card, RE-READ THEIR
 SECTIONS AGAINST YOURS. Two authors can each write something true and still produce
 a card that lies — the defect lives in the SEAM, and it won't be in the diff you wrote.

## docs
(Paths or links to the real writeups.)

## contact
(Which sessions know this best?)
CARD
  echo "Created card: $f"
  echo "Edit it with your normal file tools, then others can read it with: bus.sh asset info $name"
}

_asset_info() {  # <name>
  local f; f="$(_asset_file "${1:-}")"
  if [ ! -s "$f" ]; then
    echo "No card for '${1:-}'. Create one: bus.sh asset new ${1:-<name>} [board|gpu|service]"
    return 1
  fi
  # `|| true`: _asset_check returns 1 on a bad card, and under `set -e` that would abort
  # the whole command — so a BROKEN card would print NOTHING AT ALL. The validator would have
  # silenced the very thing it exists to shout about. Caught on first run.
  local warn; warn="$(_asset_check "$f" || true)"
  if [ -n "$warn" ]; then
    echo "━━━ ⚠️  THIS CARD IS NOT FULLY TRUSTWORTHY ━━━"
    echo "$warn"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
  fi
  cat "$f"
}

_asset_path() { _asset_file "${1:-}"; }

_asset_list() {
  if [ ! -d "$REGISTRY" ] || [ -z "$(ls -A "$REGISTRY" 2>/dev/null)" ]; then
    echo "The fleet registry is empty. Register something: bus.sh asset new <name> [board|gpu|service]"
    return 0
  fi
  echo "=== FLEET REGISTRY ==="
  local f n k s
  for f in "$REGISTRY"/*.md; do
    [ -s "$f" ] || continue
    n="$(basename "$f" .md)"
    k="$(_asset_hdr kind "$f")"; s="$(_asset_hdr summary "$f")"
    printf '  %-16s %-8s %s\n' "$n" "[${k:-?}]" "${s:-(no summary yet)}"
  done
  echo
  echo "Full card: bus.sh asset info <name>   ·   Reserve a board: /reserve <name> <dur> <soft|hard>"
}

# Printed automatically when a session takes a resource — the card travels with the
# asset, so you never have to ask a human how to reach the thing you just reserved.
_asset_handoff() {  # <name>
  local f; f="$(_asset_file "${1:-}")"
  [ -s "$f" ] || { echo "  (no asset card for '$1' yet — if you work it out, please write one: bus.sh asset new $1)"; return 0; }
  echo ""
  echo "───────── how to use [$1] ─────────"
  sed -n '/^## access/,/^## docs/p' "$f" | sed '$d'
  echo "  (full card: bus.sh asset info $1)"
  echo "───────────────────────────────────"
}

asset_dispatch() {
  local verb="${1:-list}"; shift 2>/dev/null || true
  case "$verb" in
    new|register) _asset_new "$@" ;;
    info|show)    _asset_info "$@" ;;
    path|edit)    _asset_path "$@" ;;
    list|catalog) _asset_list ;;
    drill)        _asset_drill "$@" ;;
    drilled)      _asset_drilled "$@" ;;
    *) echo "usage: bus.sh asset {new|info|path|list|drill|drilled} <name>" >&2; return 2 ;;
  esac
}


cmd="${1:-help}"
shift || true
BUS_ACTION="$cmd"

# Surface an unregistered-tag warning on the interactive verbs (never the silent hooks).
case "$cmd" in send|check|all|mine|sent) _warn_if_unregistered ;; esac

case "$cmd" in
  send)
    # STDIN ONLY. The argument path is DELETED, not deprecated. Two silent bugs lived
    # here, both found by the fleet by LIVING them (2026-07-11):
    #
    #  1. A message passed as an ARGUMENT goes through the caller's shell FIRST, which
    #     command-substitutes backticks: `bus.sh send "run `foo` now"` posts "run  now".
    #     Exit 0, no warning. You cannot validate your way out of this — the shell ate
    #     the bytes before bus.sh had a process. It is a gap in TIME, not a gap in a
    #     check, so the path must be REMOVED, not warned about.
    #
    #  2. Accepting BOTH args and stdin gave the tool two mouths. `bus.sh send docs
    #     <<'EOF' … EOF` sent the single word "docs" and silently DROPPED the entire
    #     heredoc body. Exit 0 again. (It "read almost right" — a message from [docs]
    #     whose content was, fittingly, just "docs".)
    #
    # `-` is accepted as an explicit "read stdin" marker so the recipe we print is a
    # recipe the guard actually allows.
    case "$#:${1:-}" in
      0:|1:-) : ;;
      *)
        cat >&2 <<'SENDERR'
ERROR: `bus.sh send` takes NO message arguments — it reads the body from STDIN.

    ~/.claude/bin/bus.sh send - <<'MSG'
    to:sometag — [me] your message here.
    Backticks like `/svc-next`, $vars and "quotes" all survive untouched.
    MSG

WHY: a message passed as an argument goes through your shell first, which
command-substitutes backticks and DELETES them. The send SUCCEEDS and your words
silently vanish. A QUOTED heredoc delimiter (<<'MSG') substitutes nothing at all.
SENDERR
        exit 2 ;;
    esac
    MSG_BODY="$(cat)"
    if [ -z "$MSG_BODY" ]; then
      echo "ERROR: bus.sh send received an empty message on stdin." >&2
      exit 2
    fi
    TS="$(date '+%Y-%m-%d %H:%M')"
    { echo ""; echo "## $TS [$TAG]"; echo ""; printf '%s\n' "$MSG_BODY"; } >> "$BUS_FILE"
    # READ IT BACK. Do not just assert the write succeeded.
    #
    # `send` used to print "Sent message tagged [x]" whether or not anything landed — the tool
    # reporting its own intention, not the outcome. That is exactly what has bitten this fleet
    # all day (a crashed verify reporting a refusal; a zero-run loop reporting determinism; a
    # grep that searched nothing reporting no matches).
    #
    # And it bites HARDER here, because `check` deliberately never echoes your own posts — so
    # a Claude that wants to confirm its message landed has NO WAY to ask. image_gen grepped
    # `bus.sh check` for its own message, got silence, and could not tell whether the send had
    # failed or the tool simply doesn't show you your own words. **After today, it refused to
    # read that silence as success, and it was right not to.**
    if tail -c 200000 "$BUS_FILE" 2>/dev/null | grep -qaF "## $TS [$TAG]"; then
      echo "Sent message tagged [$TAG] at $TS — VERIFIED on the bus ($(wc -c < "$BUS_FILE" 2>/dev/null) bytes)."
    else
      echo "⚠️  WROTE the message but CANNOT SEE IT on the bus. Do not assume it landed." >&2
      echo "    (bus: $BUS_FILE)  Re-read it yourself before you rely on this." >&2
      exit 1
    fi
    # DELIBERATELY NO mark_seen_if_bus_tag. (backend, 2026-07-11 — silent mail loss.)
    # mark_seen sets last-seen to the NEWEST header in the FILE, regardless of what you
    # actually read. So posting a message marked every unread message as seen — and now
    # that `check` correctly shows only what is new, those messages became invisible
    # FOREVER. Making check honest turned a cosmetic wart into silent mail loss, and it
    # preferentially ate the most time-critical traffic: the sessions most likely to be
    # mid-thread are precisely the ones sending, so mail landing while you compose was
    # consumed by your own reply.
    # Nothing needs marking here: prompt-check already excludes your own tag.
    ;;

  check)
    # Show what's NEW and MINE — not the last 80 lines of everything.
    #
    # (93emulator, 2026-07-11): `check` re-printed the whole tail on every call,
    # including traffic already read AND the caller's own posts, so most of a
    # check's context was re-reading. The watermark that fixes this already
    # existed — prompt-check maintains <tag>.last-seen — `check` just never
    # consumed it. Now it does, and it advances it (as it always did).
    #
    #   check              new since my last-seen, addressed to me or broadcast
    #   check --all-tags   new since my last-seen, no addressing filter
    #   check --all        old behaviour: the full recent tail (last 80 lines)
    #   check -n <N>       cap output to the last N selected messages
    MODE=new; LIMIT=0
    while [ $# -gt 0 ]; do
      case "$1" in
        --all)      MODE=tail ;;
        --all-tags) MODE=alltags ;;
        -n)         shift; LIMIT="${1:-10}" ;;
        -n*)        LIMIT="${1#-n}" ;;
      esac
      shift
    done

    STATE_DIR="$HOME/.claude/bus-state"
    LAST_SEEN=""
    [ -f "$STATE_DIR/$TAG.last-seen" ] && LAST_SEEN="$(cat "$STATE_DIR/$TAG.last-seen" 2>/dev/null || true)"
    # The watermark advance now lives in the python (it advances to what was DISPLAYED, not the file's
    # newest — see below). Preserve the old whitelist guard: only a whitelisted tag advances its cursor.
    if is_whitelisted "$TAG"; then WL=1; else WL=0; fi

    echo "=== My session tag: [$TAG] ==="
    echo

    if [ "$MODE" = tail ]; then
      tail -80 "$BUS_FILE"
    else
      BUS_FILE="$BUS_FILE" MY_TAG="$TAG" LAST_SEEN="$LAST_SEEN" MODE="$MODE" LIMIT="$LIMIT" WL="$WL" \
      python3 - <<'PYEOF'
import os, re, sys

path = os.environ["BUS_FILE"]
me    = os.environ["MY_TAG"]
last  = os.environ.get("LAST_SEEN", "") or ""
mode  = os.environ.get("MODE", "new")
limit = int(os.environ.get("LIMIT") or 0)

def plain(t):
    t = t.strip().strip("[]")
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()

me_p = plain(me)
HDR  = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \[([^\]]+)\]\s*$')
TO   = re.compile(r'\bto:(\S+)')

msgs, cur = [], None
try:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = HDR.match(line)
            if m:
                if cur: msgs.append(cur)
                cur = {"ts": m.group(1), "sender": m.group(2), "lines": [line]}
            elif cur is not None:
                cur["lines"].append(line)
    if cur: msgs.append(cur)
except OSError:
    sys.exit(0)

def targets(msg):
    """Plain names a message is addressed to. Empty set == broadcast."""
    for ln in msg["lines"][1:]:
        s = ln.strip()
        if not s:
            continue
        if s.startswith("@to "):                      # Conductor's compose format
            return {plain(t) for t in re.findall(r'\[([^\]]+)\]', s)}
        head = s.split("—", 1)[0]                # address prefix ends at the em-dash
        return {plain(t) for t in TO.findall(head)}
    return set()

sel = []
for m in msgs:
    if plain(m["sender"]) == me_p:                    # never re-show my own posts
        continue
    if last and not (m["ts"] > last):                 # already read
        continue
    if mode == "new":
        tg = targets(m)
        if tg and me_p not in tg and "all" not in tg:
            continue                                  # addressed only to others
    sel.append(m)

CAP = 20                   # default page size for a large backlog with no explicit -n
total_unread = len(sel)
remaining = 0
if not last:
    sel = sel[-10:]        # never checked before: recent context, not the whole archive
    if limit:
        sel = sel[-limit:]
elif limit:
    sel = sel[-limit:]     # explicit -n: the newest N
elif total_unread > CAP:
    # Large backlog, no explicit -n: page it OLDEST-first so the read is resumable, and — the point —
    # so the emission stays small enough that the transport is unlikely to truncate it below the
    # cursor we are about to commit. 91emulator (2026-07-13) measured a `check` that emitted 200
    # messages / 64 KB, got truncated by the harness to a ~2 KB preview, and advanced the cursor to
    # the file's newest anyway -> 193 messages marked read, never received. The AIRTIGHT fix is the
    # two-phase commit (docs/ARCHITECTURE_VISION.md §2.3.2); this bounds the trigger in the meantime.
    sel = sel[:CAP]
    remaining = total_unread - CAP

if not sel:
    print("No new messages since your last check (%s)." % (last or "ever"))
    print("(`--all-tags` = new traffic addressed to anyone · `--all` = full recent tail)")
    sys.exit(0)            # nothing shown -> do NOT advance the watermark

for m in sel:
    print("\n".join(m["lines"]).rstrip())
    print()

label = "new" if mode == "new" else "new (all tags)"
if remaining:
    print("--- %d of %d unread shown (oldest first) · %d REMAIN — run `check` again, "
          "or `bus.sh catchup` to digest them all at once. ---"
          % (len(sel), total_unread, remaining))
else:
    print("--- %d %s message(s). `--all-tags` for traffic addressed to others · "
          "`--all` for the full tail. ---" % (len(sel), label))

# Advance the watermark ONLY to the newest message actually DISPLAYED — never to the file's newest
# (the old mark_seen_if_bus_tag bug), never when nothing was shown, and never past mail this mode or
# cap did not show. mcxn947qemu (2026-07-13): a narrow `check` must not mark-read what `--all-tags`
# should still surface. backend (2026-07-11): never advance past mail you did not SHOW.
if os.environ.get("WL") == "1":
    sd = os.path.expanduser("~/.claude/bus-state")
    try:
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, me + ".last-seen"), "w") as f:
            f.write(sel[-1]["ts"] + "\n")
        with open(os.path.join(sd, me + ".pending"), "w") as f:
            f.write("0\n")
    except OSError:
        pass
PYEOF
    fi
    ;;

  catchup)
    # Get CURRENT in one shot after an absence — without `check`'s ~28-page slog and
    # without the blind skip (post-once / send used to stamp the cursor at newest and
    # mark hundreds read unread; that is already gone, this makes the honest path cheap).
    #
    # holobench (2026-07-14): a returning session had two exits, both wrong — burn ~28 turns
    # paging 20 full bodies at a time, or advance the cursor without reading. The tension is
    # real and structural: a single high-water mark plus a lossy transport means you can only
    # advance the cursor to a point below which everything was actually SHOWN. A 64 KB full-body
    # dump gets truncated and then advances anyway (91emulator lost 193 messages exactly so).
    #
    # So catchup shows a ONE-LINE DIGEST per unread message — small enough not to truncate —
    # OLDEST-first (so advancing the cursor to the last line shown is always sound), and clears
    # a bounded page of ~200 per call instead of 20. Every message is at minimum digested: this
    # is a cheap read, never a silent skip. Full bodies stay one `check --all` / read away.
    #
    #   catchup            digest all unread (mine or broadcast), advance fully
    #   catchup -n <N>     cap this page to N (default 200)
    LIMIT=0
    while [ $# -gt 0 ]; do
      case "$1" in
        -n)   shift; LIMIT="${1:-200}" ;;
        -n*)  LIMIT="${1#-n}" ;;
      esac
      shift
    done
    STATE_DIR="$HOME/.claude/bus-state"
    LAST_SEEN=""
    [ -f "$STATE_DIR/$TAG.last-seen" ] && LAST_SEEN="$(cat "$STATE_DIR/$TAG.last-seen" 2>/dev/null || true)"
    if is_whitelisted "$TAG"; then WL=1; else WL=0; fi

    echo "=== Catch-up for [$TAG] — digest of unread, oldest-first ==="
    echo

    BUS_FILE="$BUS_FILE" MY_TAG="$TAG" LAST_SEEN="$LAST_SEEN" LIMIT="$LIMIT" WL="$WL" \
    python3 - <<'PYEOF'
import os, re, sys

path  = os.environ["BUS_FILE"]
me    = os.environ["MY_TAG"]
last  = os.environ.get("LAST_SEEN", "") or ""
limit = int(os.environ.get("LIMIT") or 0)
CAP   = limit if limit else 200          # digests are tiny; a page of 200 stays well under
                                         # the transport's truncation point (unlike full bodies)

def plain(t):
    t = t.strip().strip("[]")
    if t.lower().startswith("other:"):
        t = t[6:]
    return t.lower()

me_p = plain(me)
HDR  = re.compile(r'^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \[([^\]]+)\]\s*$')
TO   = re.compile(r'\bto:(\S+)')

msgs, cur = [], None
try:
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            m = HDR.match(line)
            if m:
                if cur: msgs.append(cur)
                cur = {"ts": m.group(1), "sender": m.group(2), "lines": [line]}
            elif cur is not None:
                cur["lines"].append(line)
    if cur: msgs.append(cur)
except OSError:
    sys.exit(0)

def first_body(msg):
    for ln in msg["lines"][1:]:
        if ln.strip():
            return ln.strip()
    return ""

def targets(line):
    if line.startswith("@to "):
        return {plain(t) for t in re.findall(r'\[([^\]]+)\]', line)}
    head = line.split("—", 1)[0]
    return {plain(t) for t in TO.findall(head)}

def subject(line):
    # Strip the address prefix (`to:a to:b … —`) and the leading [sender] tag, and markdown
    # bold, to leave the human gist. Falls back to the whole line for plain broadcasts.
    s = line.split("—", 1)[1] if "—" in line else line
    s = re.sub(r'^\s*\[[^\]]+\]\s*', '', s)     # drop a leading [sender]
    s = s.replace("**", "").strip()
    return s

sel = []
for m in msgs:
    if plain(m["sender"]) == me_p:                 # never my own posts
        continue
    if last and not (m["ts"] > last):              # already read
        continue
    fb = first_body(m)
    tg = targets(fb)
    if tg and me_p not in tg and "all" not in tg:  # addressed only to others
        continue
    m["_wake"] = "p:wake" in fb
    m["_subj"] = subject(fb)
    sel.append(m)

total = len(sel)
if total == 0:
    print("Already current — no unread since your last check (%s)." % (last or "ever"))
    sys.exit(0)

page = sel[:CAP]                                   # OLDEST-first slice: advancing to page[-1]
remaining = total - len(page)                      # is always sound (all below it was shown)

for m in page:
    hhmm = m["ts"][11:]                             # "YYYY-MM-DD HH:MM" -> "HH:MM"
    bell = "🔔 " if m["_wake"] else ""
    subj = m["_subj"]
    if len(subj) > 96:
        subj = subj[:95] + "…"
    print("%s  %s[%s] %s" % (hhmm, bell, plain(m["sender"]), subj))

print()
if remaining:
    print("--- %d of %d unread digested (oldest-first) · %d REMAIN — run `catchup` again. ---"
          % (len(page), total, remaining))
else:
    print("--- caught up: %d message(s) digested. Full body: `bus.sh check --all`. ---" % total)

# Advance the cursor to the newest message we DIGESTED — never past it. Sound because the page
# is oldest-first and contiguous from the old watermark: everything at or below page[-1] was shown.
if os.environ.get("WL") == "1":
    sd = os.path.expanduser("~/.claude/bus-state")
    try:
        os.makedirs(sd, exist_ok=True)
        with open(os.path.join(sd, me + ".last-seen"), "w") as f:
            f.write(page[-1]["ts"] + "\n")
        with open(os.path.join(sd, me + ".pending"), "w") as f:
            f.write("0\n")
    except OSError:
        pass
PYEOF
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

  svc)
    svc_dispatch "$@"
    exit $?
    ;;

  asset|catalog)
    if [ "$cmd" = "catalog" ]; then asset_dispatch list; else asset_dispatch "$@"; fi
    exit $?
    ;;

  retract)
    _coord_retract RETRACTION "$@"
    exit $?
    ;;

  supersede)
    _coord_retract CORRECTION "$@"
    exit $?
    ;;

  persist)
    action="${1:-list}"; shift 2>/dev/null || true
    case "$action" in
      list)    persist_list ;;
      approve) persist_approve "$@" ;;
      deny)    persist_deny "$@" ;;
      revoke)  persist_revoke "$@" ;;
      *) echo "usage: bus.sh persist {list|approve <name>|deny <name>|revoke <name>}"; exit 2 ;;
    esac
    exit $?
    ;;

  push)
    action="${1:-list}"; shift 2>/dev/null || true
    case "$action" in
      list)    push_list ;;
      approve) push_approve "$@" ;;
      deny)    push_deny "$@" ;;
      revoke)  push_revoke "$@" ;;
      propose) push_propose "$@" ;;
      withdraw) push_withdraw "$@" ;;
      *) echo "usage: bus.sh push {list|approve <repo>|deny <repo>|revoke <repo>|propose -|withdraw}"; exit 2 ;;
    esac
    exit $?
    ;;

  sent)
    bus_sent "${1:-5}"
    exit 0
    ;;

  waiting)
    bus_waiting "${1:-12}"
    exit 0
    ;;

  mine)
    # Your own recent posts. `check` deliberately never echoes them (you shouldn't re-read your
    # own mail) — but that left NO WAY to confirm your own message landed, and a Claude that
    # cannot verify its own send will either trust a tool's self-report or invent certainty.
    # Neither is acceptable after today. So: read the bus, show YOUR headers.
    n="${1:-5}"
    echo "=== last $n posts by [$TAG] ==="
    grep -aE "^## .* \[$TAG\]$" "$BUS_FILE" 2>/dev/null | tail -"$n" | sed 's/^/  /'
    grep -acE "^## .* \[$TAG\]$" "$BUS_FILE" 2>/dev/null | sed 's/^/  total posts: /'
    exit 0
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
    #
    # BUT an identity collision (a second session in a repo that already has one) is a
    # cross-cutting hazard that matters regardless of whitelist — it is exactly the case
    # nobody notices — so it's computed FIRST and can shout even for an un-whitelisted tag.
    SIBLING_LINES="$(sibling_hook_lines 2>/dev/null || true)"
    if ! is_whitelisted "$TAG"; then
      # Not on the auto-hook whitelist -> normally a silent no-op. Still shout a collision.
      if [ -n "$SIBLING_LINES" ]; then
        SS_ESC="$(printf '%s' "$SIBLING_LINES" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
        cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $SS_ESC
  }
}
EOF
      fi
      exit 0
    fi
    if [ ! -s "$BUS_FILE" ]; then
      # Empty bus: still surface a collision if there is one (fold it into the context).
      if [ -n "$SIBLING_LINES" ]; then
        SS_ESC="$(printf '%s' "$SIBLING_LINES" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
        cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $SS_ESC
  }
}
EOF
      fi
      mark_seen_if_bus_tag
      exit 0
    fi
    # THE SAME SILENT-MAIL-LOSS BUG LIVED HERE TOO (2026-07-11, found while fixing the
    # `send` one). We show `tail -60` — SIXTY LINES, and a single message routinely runs
    # 30-40 — and then marked the ENTIRE FILE as read. So a session restarting after any
    # absence got shown one or two messages while fifty were silently marked seen and
    # became invisible forever. It fired on EVERY restart, including click-to-relaunch.
    #
    # Rule, applied everywhere now: NEVER advance the watermark past mail you did not
    # actually SHOW.
    #   * first contact (no watermark) -> establish the baseline, as designed: a new
    #     session shouldn't have the archive dumped on it, and nothing is unread to it.
    #   * a RESTART (watermark exists) -> show the recent tail as context but leave the
    #     watermark ALONE. The unread stays unread and `check` will show it in full.
    #     Over-notifying is recoverable; eating mail is not.
    SS_STATE_DIR="$HOME/.claude/bus-state"
    SS_HAD_WATERMARK=0
    [ -f "$SS_STATE_DIR/$TAG.last-seen" ] && SS_HAD_WATERMARK=1
    LATEST="$(tail -60 "$BUS_FILE")"
    # Build the whole additionalContext as one string, then JSON-encode it ONCE. (This replaces
    # the old `sed 's/^"//;s/"$//'` quote-strip trick, which was fragile; a collision warning with
    # parens/brackets in it must not be able to break the JSON.) A collision leads, before the bus.
    SS_CTX="Claude Bus — recent messages from the cross-session log (your tag: [$TAG]). Read these before responding so you know what the OTHER session has been saying while you were offline:

$LATEST"
    [ -n "$SIBLING_LINES" ] && SS_CTX="$SIBLING_LINES

$SS_CTX"
    SS_ESC="$(printf '%s' "$SS_CTX" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    cat <<EOF
{
  "hookSpecificOutput": {
    "hookEventName": "SessionStart",
    "additionalContext": $SS_ESC
  }
}
EOF
    # Only on first contact. See above: never mark mail read that we did not show.
    [ "$SS_HAD_WATERMARK" -eq 1 ] || mark_seen_if_bus_tag
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
    # Retractions aimed at me — loud, and FIRST (safety before everything else).
    RETRACT_LINES="$(retract_hook_lines "$(_coord_plain "$TAG")" "$LAST_SEEN" 2>/dev/null || true)"
    # Identity collision — a second session sharing my tag. Even more foundational than a
    # retraction: if there are two of me, I can't trust that a retraction addressed to my tag
    # was even meant for this session. So it leads everything.
    SIBLING_LINES="$(sibling_hook_lines 2>/dev/null || true)"

    # Nothing pending, no retraction, no collision, and every resource free -> stay silent.
    if [ -z "$NOTE" ] && [ -z "$RES_LINES" ] && [ -z "$RETRACT_LINES" ] && [ -z "$SIBLING_LINES" ]; then
      exit 0
    fi

    NL=$'\n'
    FULL=""
    [ -n "$SIBLING_LINES" ] && FULL="$SIBLING_LINES"   # identity first — who am I talking as?
    if [ -n "$RETRACT_LINES" ]; then FULL="${FULL:+$FULL$NL}$RETRACT_LINES"; fi   # then retractions
    if [ -n "$NOTE" ]; then FULL="${FULL:+$FULL$NL}$NOTE"; fi
    if [ -n "$RES_LINES" ]; then FULL="${FULL:+$FULL$NL}$RES_LINES"; fi
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
  bus.sh check               New messages addressed to you since last check
  bus.sh catchup [-n N]      Digest ALL unread at once (oldest-first) & get current
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
