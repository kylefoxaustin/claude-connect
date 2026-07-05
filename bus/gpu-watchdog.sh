#!/usr/bin/env bash
# GPU idle watchdog (Phase 2 of the bus GPU-reservation system).
#
# Polls nvidia-smi and, when the held GPU lease has been sitting idle (models
# loaded but ~0% utilization) past a threshold, NUDGES the owner on the bus to
# release it — and, for a preemptible `soft` lease, auto-releases it after a
# longer grace. All without the human coordinating.
#
# Standalone + headless: run under `systemd --user` (see bus/gpu-watchdog.service)
# or `nohup bus/gpu-watchdog.sh run &`. Reads/writes the same lease file bus.sh
# uses, under the same flock, so it never races the reserve/release commands.
#
# Tunables (env): GPU_POLL_SEC, GPU_IDLE_UTIL_PCT, GPU_IDLE_NUDGE_MIN,
#   GPU_IDLE_RENUDGE_MIN, GPU_SOFT_RELEASE_MIN. NVIDIA_SMI / BUS_FILE / GPU_STATE_DIR
#   are overridable for testing.
set -uo pipefail

GPU_DIR="${GPU_STATE_DIR:-$HOME/.claude/bus-state/gpu}"
GPU_LEASE="$GPU_DIR/lease"
GPU_LOCK="$GPU_DIR/.lock"
BUS_FILE="${BUS_FILE:-$HOME/Documents/claude-bus/messages.md}"
NVIDIA_SMI="${NVIDIA_SMI:-nvidia-smi}"

POLL_SEC="${GPU_POLL_SEC:-60}"
IDLE_UTIL_PCT="${GPU_IDLE_UTIL_PCT:-5}"          # util <= this counts as "not computing"
IDLE_NUDGE_MIN="${GPU_IDLE_NUDGE_MIN:-30}"       # first nudge after this much idle
IDLE_RENUDGE_MIN="${GPU_IDLE_RENUDGE_MIN:-20}"   # re-nudge cadence while still idle
SOFT_RELEASE_MIN="${GPU_SOFT_RELEASE_MIN:-60}"   # auto-release an idle SOFT lease after this

_now() { date +%s; }
_field() { grep -E "^$1=" "$GPU_LEASE" 2>/dev/null | head -1 | cut -d= -f2- ; }
_set_field() {  # key value  (lease assumed present; caller holds the lock)
  if grep -qE "^$1=" "$GPU_LEASE" 2>/dev/null; then
    sed -i "s|^$1=.*|$1=$2|" "$GPU_LEASE"
  else
    printf '%s=%s\n' "$1" "$2" >> "$GPU_LEASE"
  fi
}
_lease_active() {
  [ -f "$GPU_LEASE" ] || return 1
  local exp; exp="$(_field expires_epoch)"; [ -n "$exp" ] && [ "$(_now)" -lt "$exp" ]
}
_gpu_util() {  # integer utilization % of GPU 0, or empty if nvidia-smi is unavailable
  "$NVIDIA_SMI" --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc '0-9'
}
_human() { local s=$1 h m; [ "$s" -lt 0 ] && s=0; h=$((s/3600)); m=$(((s%3600)/60)); if [ "$h" -gt 0 ]; then echo "${h}h ${m}m"; elif [ "$m" -gt 0 ]; then echo "${m}m"; else echo "${s}s"; fi; }
_notify() {  # post a message on the bus tagged [gpu-watchdog]
  local ts; ts="$(date '+%Y-%m-%d %H:%M')"
  { echo ""; echo "## $ts [gpu-watchdog]"; echo ""; echo "$1"; } >> "$BUS_FILE"
}

# Evaluate one poll. Testable in isolation (mock NVIDIA_SMI + GPU_STATE_DIR).
tick() {
  ( flock 9
    _lease_active || exit 0
    local owner mode now util
    owner="$(_field owner)"; mode="$(_field mode)"; now="$(_now)"
    util="$(_gpu_util)"
    [ -n "$util" ] || exit 0   # can't judge idle without telemetry → do nothing

    if [ "$util" -gt "$IDLE_UTIL_PCT" ]; then
      # Real activity — freshen last-active and clear any idle/nudge tracking.
      _set_field last_active_epoch "$now"
      _set_field idle_since_epoch ""
      _set_field nudged_epoch ""
      exit 0
    fi

    # Idle this sample. Start (or continue) the idle clock.
    local idle_since; idle_since="$(_field idle_since_epoch)"
    if [ -z "$idle_since" ]; then _set_field idle_since_epoch "$now"; idle_since="$now"; fi
    local idle=$(( now - idle_since ))
    [ "$idle" -ge $(( IDLE_NUDGE_MIN * 60 )) ] || exit 0   # not idle long enough yet

    local waiter wtxt; waiter="$(_field requested_by)"; wtxt=""
    [ -n "$waiter" ] && wtxt=" [$waiter] is waiting for it."

    # SOFT + idle past the grace → auto-release (it's preemptible by definition).
    if [ "$mode" = "soft" ] && [ "$idle" -ge $(( SOFT_RELEASE_MIN * 60 )) ]; then
      rm -f "$GPU_LEASE"
      _notify "to:$owner to:all — [gpu-watchdog] Auto-released [$owner]'s SOFT GPU lease — idle $(_human "$idle") (util <=${IDLE_UTIL_PCT}%), and a soft hold yields when not in use. GPU is now FREE.${wtxt} @$owner re-reserve if you still need it."
      exit 0
    fi

    # Otherwise nudge the owner (once, then on a re-nudge cadence).
    local nudged; nudged="$(_field nudged_epoch)"
    if [ -z "$nudged" ] || [ $(( now - nudged )) -ge $(( IDLE_RENUDGE_MIN * 60 )) ]; then
      _set_field nudged_epoch "$now"
      if [ "$mode" = "hard" ]; then
        _notify "to:$owner — [gpu-watchdog] Your HARD GPU lease has shown no activity for $(_human "$idle") (util <=${IDLE_UTIL_PCT}%; models may be loaded but idle).${wtxt} If your job is finished or stalled, please /gpu-release; if it's still needed, /gpu-keep to reset the timer. (Hard leases are never auto-released — this is just a check-in.)"
      else
        _notify "to:$owner — [gpu-watchdog] Your SOFT GPU lease has been idle $(_human "$idle").${wtxt} It will AUTO-RELEASE once idle reaches $(_human $(( SOFT_RELEASE_MIN * 60 ))). /gpu-keep to hold it, or /gpu-release now."
      fi
    fi
  ) 9>"$GPU_LOCK"
}

case "${1:-run}" in
  tick) tick ;;
  run)
    echo "gpu-watchdog: poll ${POLL_SEC}s · idle=util<=${IDLE_UTIL_PCT}% · nudge@${IDLE_NUDGE_MIN}m (re-nudge ${IDLE_RENUDGE_MIN}m) · soft auto-release@${SOFT_RELEASE_MIN}m"
    mkdir -p "$GPU_DIR"
    while true; do tick; sleep "$POLL_SEC"; done
    ;;
  *) echo "usage: gpu-watchdog.sh {run|tick}"; exit 2 ;;
esac
