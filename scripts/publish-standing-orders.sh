#!/usr/bin/env bash
# publish-standing-orders.sh — mirror the fleet standing orders into the public
# rules-of-engagement repo, byte-for-byte, and commit there.
#
# bus/standing-orders.md (this repo) is the SOURCE: install-standing-orders.sh deploys it to the
# live fleet from here. rules-of-engagement/FLEET-STANDING-ORDERS.md is a published MIRROR, and Kyle
# wants it to be an exact match (2026-10-13) — the rules the agents are held to and the rules
# published as the rules must not quietly diverge. claude-connect owns both and runs this after
# every amendment. tests/test-standing-orders.sh fails while they differ.
#
# Commits only; pushing is gated like any other push.
#   ROE=<path to the rules-of-engagement clone>   (default: a sibling of this repo)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROE="${ROE:-$(dirname "$REPO")/rules-of-engagement}"
SRC="$REPO/bus/standing-orders.md"
DST="$ROE/FLEET-STANDING-ORDERS.md"
[ -d "$ROE/.git" ] || { echo "no rules-of-engagement clone at $ROE (set ROE=)"; exit 1; }
if cmp -s "$SRC" "$DST"; then echo "= already identical: $DST"; exit 0; fi
if [ -n "$(git -C "$ROE" status --porcelain -- FLEET-STANDING-ORDERS.md)" ] && [ -f "$DST" ] \
   && git -C "$ROE" ls-files --error-unmatch FLEET-STANDING-ORDERS.md >/dev/null 2>&1; then
  echo "refusing: $DST has uncommitted edits — the mirror is never edited in place"; exit 1
fi
cp "$SRC" "$DST"
cmp "$SRC" "$DST"
SHA="$(git -C "$REPO" log -1 --format=%h -- bus/standing-orders.md)"
git -C "$ROE" add FLEET-STANDING-ORDERS.md
git -C "$ROE" commit -q -m "Fleet standing orders: sync from claude-connect ${SHA}" \
  -m "Byte-for-byte mirror of claude-connect bus/standing-orders.md — edit it there, not here."
echo "synced -> $DST ($(git -C "$ROE" log -1 --format=%h)); push rules-of-engagement to publish"
