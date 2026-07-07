#!/usr/bin/env bash
# Resource idle watchdog — polls held reservations and nudges/reclaims idle ones,
# so a shared resource (the GPU, the IQ9 EVK, …) doesn't stay hoarded while idle.
# Generalizes the old GPU watchdog to every resource under bus-state/resources/.
#
#   • gpu  → idle = nvidia-smi utilization <= threshold (models loaded but not computing)
#   • else → idle = time since last /keep heartbeat (or reserve)
#
# On idle past a threshold: NUDGE the owner on the bus (re-nudging on a cadence,
# naming any requester), and AUTO-RELEASE an idle `soft` lease after a longer grace.
# `hard` leases are never force-released — only checked in on.
#
# Standalone + headless (systemd --user; see resource-watchdog.service). Shares the
# per-resource flock, so it never races reserve/release.
set -uo pipefail

RES_ROOT="${RESOURCE_STATE_DIR:-$HOME/.claude/bus-state/resources}"
BUS_FILE="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
NVIDIA_SMI="${NVIDIA_SMI:-nvidia-smi}"

POLL_SEC="${RES_POLL_SEC:-60}"
IDLE_UTIL_PCT="${RES_IDLE_UTIL_PCT:-5}"          # gpu: util <= this counts as "not computing"
IDLE_NUDGE_MIN="${RES_IDLE_NUDGE_MIN:-30}"       # first nudge after this much idle
IDLE_RENUDGE_MIN="${RES_IDLE_RENUDGE_MIN:-20}"   # re-nudge cadence while still idle
SOFT_RELEASE_MIN="${RES_SOFT_RELEASE_MIN:-60}"   # auto-release an idle SOFT lease after this

_now() { date +%s; }
_label() { case "$1" in gpu) echo "GPU" ;; *) echo "$1" ;; esac; }
_field() { grep -E "^$1=" "$LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_set() {   # key value  (lease present; caller holds the lock)
  if grep -qE "^$1=" "$LEASE" 2>/dev/null; then sed -i "s|^$1=.*|$1=$2|" "$LEASE"
  else printf '%s=%s\n' "$1" "$2" >> "$LEASE"; fi
}
_active() { [ -f "$LEASE" ] || return 1; local exp; exp="$(_field expires_epoch)"; [ -n "$exp" ] && [ "$(_now)" -lt "$exp" ]; }
_gpu_util() { "$NVIDIA_SMI" --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc '0-9'; }
_human() { local s=$1 h m; [ "$s" -lt 0 ] && s=0; h=$((s/3600)); m=$(((s%3600)/60)); if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi; }
_notify() { local ts; ts="$(date '+%Y-%m-%d %H:%M')"; { echo ""; echo "## $ts [resource-watchdog]"; echo ""; echo "$1"; } >> "$BUS_FILE"; }

# Evaluate one resource. Testable in isolation (mock NVIDIA_SMI + RESOURCE_STATE_DIR).
tick_one() {  # name
  local name="$1" lbl; lbl="$(_label "$1")"
  LEASE="$RES_ROOT/$name/lease"; LOCK="$RES_ROOT/$name/.lock"
  ( flock 9
    _active || exit 0
    local owner mode now idle_ref; owner="$(_field owner)"; mode="$(_field mode)"; now="$(_now)"

    if [ "$name" = "gpu" ]; then
      local util; util="$(_gpu_util)"
      [ -n "$util" ] || exit 0                       # no telemetry → can't judge
      if [ "$util" -gt "$IDLE_UTIL_PCT" ]; then       # active → reset
        _set last_active_epoch "$now"; _set idle_since_epoch ""; _set nudged_epoch ""; exit 0
      fi
      idle_ref="$(_field idle_since_epoch)"; [ -n "$idle_ref" ] || { idle_ref="$now"; }
      _set idle_since_epoch "$idle_ref"
    else
      idle_ref="$(_field last_active_epoch)"; [ -n "$idle_ref" ] || idle_ref="$now"
      _set idle_since_epoch "$idle_ref"               # heartbeat: idle since last /keep
    fi

    local idle=$(( now - idle_ref ))
    [ "$idle" -ge $(( IDLE_NUDGE_MIN * 60 )) ] || exit 0

    local waiter wtxt; waiter="$(_field requested_by)"; wtxt=""
    [ -n "$waiter" ] && wtxt=" [$waiter] is waiting for it."

    if [ "$mode" = "soft" ] && [ "$idle" -ge $(( SOFT_RELEASE_MIN * 60 )) ]; then
      rm -f "$LEASE"
      _notify "to:$owner to:all — [resource-watchdog] Auto-released [$owner]'s SOFT $lbl lease — idle $(_human "$idle") and a soft hold yields when not in use. $lbl is now FREE.${wtxt} @$owner re-reserve if you still need it."
      exit 0
    fi

    local nudged; nudged="$(_field nudged_epoch)"
    if [ -z "$nudged" ] || [ $(( now - nudged )) -ge $(( IDLE_RENUDGE_MIN * 60 )) ]; then
      _set nudged_epoch "$now"
      if [ "$name" = "gpu" ]; then
        local how="(util <=${IDLE_UTIL_PCT}%; models may be loaded but idle)"
      else
        local how="(no /keep heartbeat for that long)"
      fi
      if [ "$mode" = "hard" ]; then
        _notify "to:$owner — [resource-watchdog] Your HARD $lbl lease has shown no activity for $(_human "$idle") $how.${wtxt} If your job is finished or stalled, please /release $name; if it's still needed, /keep $name <dur> to reset the timer. (Hard leases are never auto-released — this is just a check-in.)"
      else
        _notify "to:$owner — [resource-watchdog] Your SOFT $lbl lease has been idle $(_human "$idle").${wtxt} It will AUTO-RELEASE once idle reaches $(_human $(( SOFT_RELEASE_MIN * 60 ))). /keep $name <dur> to hold, or /release $name now."
      fi
    fi
  ) 9>"$LOCK"
}

tick() {
  [ -d "$RES_ROOT" ] || return 0
  for d in "$RES_ROOT"/*/; do [ -d "$d" ] || continue; tick_one "$(basename "$d")"; done
}

case "${1:-run}" in
  tick) tick ;;
  run)
    echo "resource-watchdog: poll ${POLL_SEC}s · gpu idle=util<=${IDLE_UTIL_PCT}% · others idle=no-heartbeat · nudge@${IDLE_NUDGE_MIN}m · soft auto-release@${SOFT_RELEASE_MIN}m"
    mkdir -p "$RES_ROOT"
    while true; do tick; sleep "$POLL_SEC"; done
    ;;
  *) echo "usage: resource-watchdog.sh {run|tick}"; exit 2 ;;
esac
