#!/usr/bin/env bash
# Resource idle watchdog — polls held reservations and nudges/reclaims idle ones,
# and drives the reservation QUEUE forward (offer timeouts, expiry, reclaim), so a
# shared resource (the GPU, the IQ9 EVK, an Orin, …) never stays hoarded or stuck.
#
#   • gpu  → idle = nvidia-smi utilization <= threshold (models loaded but not computing)
#   • else → idle = time since last /keep heartbeat (or reserve)
#
# Actions (all via `bus.sh res promote <name> <owner>`, which is race-safe):
#   • an OFFER that isn't claimed within its grace  → auto-pass to the next in queue
#   • a lease that hits its expiry                  → offer to the next in queue (or free)
#   • an idle SOFT lease past the grace             → reclaim → offer to the next (or free)
#   • an idle HARD lease                            → NUDGE only (never auto-released)
#
# Standalone + headless (systemd --user). Shares the per-resource flock; the promote
# handoff runs bus.sh (its own flock), so this never holds a lock across the call.
set -uo pipefail

RES_ROOT="${RESOURCE_STATE_DIR:-$HOME/.claude/bus-state/resources}"
BUS_FILE="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
BUS_SH="${BUS_SH:-$HOME/.claude/bin/bus.sh}"
NVIDIA_SMI="${NVIDIA_SMI:-nvidia-smi}"

POLL_SEC="${RES_POLL_SEC:-60}"
IDLE_UTIL_PCT="${RES_IDLE_UTIL_PCT:-5}"
IDLE_NUDGE_MIN="${RES_IDLE_NUDGE_MIN:-30}"
IDLE_RENUDGE_MIN="${RES_IDLE_RENUDGE_MIN:-20}"
SOFT_RELEASE_MIN="${RES_SOFT_RELEASE_MIN:-60}"

_now() { date +%s; }
_label() { case "$1" in gpu) echo "GPU" ;; *) echo "$1" ;; esac; }
_field() { grep -E "^$1=" "$LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_set() { if grep -qE "^$1=" "$LEASE" 2>/dev/null; then sed -i "s|^$1=.*|$1=$2|" "$LEASE"; else printf '%s=%s\n' "$1" "$2" >> "$LEASE"; fi; }
_gpu_util() { "$NVIDIA_SMI" --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc '0-9'; }
_human() { local s=$1 h m; [ "$s" -lt 0 ] && s=0; h=$((s/3600)); m=$(((s%3600)/60)); if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi; }
_notify() { local ts; ts="$(date '+%Y-%m-%d %H:%M')"; { echo ""; echo "## $ts [resource-watchdog]"; echo ""; echo "$1"; } >> "$BUS_FILE"; }
_promote() { "$BUS_SH" res promote "$1" "$2" >/dev/null 2>&1 || true; }   # race-safe handoff

tick_one() {  # name
  local name="$1" lbl; lbl="$(_label "$1")"
  LEASE="$RES_ROOT/$name/lease"; LOCK="$RES_ROOT/$name/.lock"
  [ -f "$LEASE" ] || return 0
  local owner mode exp now; owner="$(_field owner)"; mode="$(_field mode)"; exp="$(_field expires_epoch)"; now="$(_now)"
  [ -n "$exp" ] || return 0

  # An unclaimed OFFER past its grace → hand to the next in queue.
  if [ "$mode" = "offer" ]; then
    [ "$now" -ge "$exp" ] && _promote "$name" "$owner"
    return 0
  fi
  # A normal lease that hit its expiry → offer to the next in queue (or free).
  if [ "$now" -ge "$exp" ]; then _promote "$name" "$owner"; return 0; fi

  # Otherwise: idle handling under the flock; capture a RECLAIM signal on stdout.
  local signal
  signal="$( ( flock 9
    [ -f "$LEASE" ] || exit 0
    local qhead wtxt idle_ref util idle
    qhead="$(_field queue)"; qhead="${qhead%%,*}"; wtxt=""; [ -n "$qhead" ] && wtxt=" [$qhead] is next in the queue."
    if [ "$name" = "gpu" ]; then
      util="$(_gpu_util)"; [ -n "$util" ] || exit 0
      if [ "$util" -gt "$IDLE_UTIL_PCT" ]; then _set last_active_epoch "$now"; _set idle_since_epoch ""; _set nudged_epoch ""; exit 0; fi
      idle_ref="$(_field idle_since_epoch)"; [ -n "$idle_ref" ] || idle_ref="$now"
      _set idle_since_epoch "$idle_ref"
    else
      idle_ref="$(_field last_active_epoch)"; [ -n "$idle_ref" ] || idle_ref="$now"
      _set idle_since_epoch "$idle_ref"
    fi
    idle=$(( now - idle_ref ))
    [ "$idle" -ge $(( IDLE_NUDGE_MIN * 60 )) ] || exit 0
    if [ "$mode" = "soft" ] && [ "$idle" -ge $(( SOFT_RELEASE_MIN * 60 )) ]; then echo RECLAIM; exit 0; fi
    local nudged; nudged="$(_field nudged_epoch)"
    if [ -z "$nudged" ] || [ $(( now - nudged )) -ge $(( IDLE_RENUDGE_MIN * 60 )) ]; then
      _set nudged_epoch "$now"
      local how; if [ "$name" = "gpu" ]; then how="(util <=${IDLE_UTIL_PCT}%; models may be loaded but idle)"; else how="(no /keep heartbeat for that long)"; fi
      if [ "$mode" = "hard" ]; then
        _notify "to:$owner — [resource-watchdog] Your HARD $lbl lease has shown no activity for $(_human "$idle") $how.${wtxt} If done/stalled, /release $name; if still needed, /keep $name <dur>. (Hard leases are never auto-released — just a check-in.)"
      else
        _notify "to:$owner — [resource-watchdog] Your SOFT $lbl lease has been idle $(_human "$idle").${wtxt} It AUTO-RELEASES at idle $(_human $(( SOFT_RELEASE_MIN * 60 ))). /keep $name <dur> to hold, or /release $name now."
      fi
    fi
  ) 9>"$LOCK" )"

  # Reclaim an idle soft lease → hand to the next in queue (its own flock).
  [ "$signal" = RECLAIM ] && _promote "$name" "$owner"
  return 0
}

tick() { [ -d "$RES_ROOT" ] || return 0; for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; tick_one "$(basename "$d")"; done; }

case "${1:-run}" in
  tick) tick ;;
  run)
    echo "resource-watchdog: poll ${POLL_SEC}s · gpu idle=util<=${IDLE_UTIL_PCT}% · others idle=no-heartbeat · nudge@${IDLE_NUDGE_MIN}m · soft reclaim@${SOFT_RELEASE_MIN}m · drives the queue (offer-timeout/expiry/reclaim → next in line)"
    mkdir -p "$RES_ROOT"
    while true; do tick; sleep "$POLL_SEC"; done
    ;;
  *) echo "usage: resource-watchdog.sh {run|tick}"; exit 2 ;;
esac
