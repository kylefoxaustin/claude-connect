#!/usr/bin/env bash
# backup-transcripts.sh — the DR transcript slice.
#
# Transcripts (~/.claude/projects/*/*.jsonl) are the `claude --continue` FUEL — without a
# session's transcript, a rebuilt fleet gets a blank Claude in that repo instead of the
# resumed conversation. They're ~1 GB and individual files can exceed GitHub's 100 MB
# file cap, so they are NOT git-tracked in fleet-backup. Instead this tars them (zstd) and
# uploads the archive as a RELEASE ASSET on fleet-backup (release assets allow up to 2 GB
# and don't bloat the git history). Fixed release/asset names, --clobber, so each run
# replaces the last — the newest transcripts are always one download away.
#
# Runs LESS often than the hourly state snapshot (transcripts are big); wire it to a daily
# timer, or run by hand. RESTORE.md step 5b consumes the asset it produces.
#
#   scripts/backup-transcripts.sh            # tar + upload
#   scripts/backup-transcripts.sh --dry-run  # tar to /tmp, report size, upload NOTHING
set -uo pipefail

REPO="${FLEET_BACKUP_SLUG:-kylefoxaustin/fleet-backup}"
REL_TAG="fleet-transcripts"
ASSET="fleet-transcripts.tar.zst"
SRC="${CLAUDE_HOME:-$HOME/.claude}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

command -v gh   >/dev/null || { echo "gh CLI not found" >&2; exit 2; }
command -v zstd >/dev/null || { echo "zstd not found" >&2; exit 2; }

WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
ARCHIVE="$WORK/$ASSET"
LIST="$WORK/list"

# Paths relative to $HOME so a restore is `tar -C ~ -xf ...` → ~/.claude/projects/*/*.jsonl.
( cd "$HOME" && find ".claude/projects" -name '*.jsonl' -print0 ) > "$LIST" 2>/dev/null
COUNT="$(tr -cd '\0' < "$LIST" | wc -c | tr -d ' ')"
if [ "$COUNT" -eq 0 ]; then
  echo "No transcripts found under $SRC/projects — nothing to back up." >&2
  exit 0
fi

echo "Archiving $COUNT transcript(s) with zstd…"
( cd "$HOME" && tar --null -T "$LIST" --zstd -cf "$ARCHIVE" ) || { echo "tar failed" >&2; exit 1; }
BYTES="$(stat -c '%s' "$ARCHIVE" 2>/dev/null || wc -c < "$ARCHIVE")"
HUMAN="$(numfmt --to=iec "$BYTES" 2>/dev/null || echo "${BYTES}B")"
echo "Archive: $ARCHIVE  ($HUMAN, $COUNT files)"

if [ "$DRY" = 1 ]; then
  echo "DRY-RUN — not uploading. (would upload $ASSET to release '$REL_TAG' on $REPO)"
  exit 0
fi

NOTES="Fleet transcripts ($COUNT files, $HUMAN) — the \`claude --continue\` fuel for DR.
Restore: \`gh release download $REL_TAG --repo $REPO -D /tmp/tx && tar -C ~ -xf /tmp/tx/$ASSET\`.
Updated: $(date '+%Y-%m-%d %H:%M')."

# Create the release once (idempotent), then clobber the asset every run.
if ! gh release view "$REL_TAG" --repo "$REPO" >/dev/null 2>&1; then
  gh release create "$REL_TAG" --repo "$REPO" --title "Fleet transcripts (DR)" --notes "$NOTES" \
    || { echo "gh release create failed" >&2; exit 1; }
else
  gh release edit "$REL_TAG" --repo "$REPO" --notes "$NOTES" >/dev/null 2>&1 || true
fi
echo "Uploading $HUMAN to $REPO release '$REL_TAG'…"
gh release upload "$REL_TAG" "$ARCHIVE" --repo "$REPO" --clobber \
  || { echo "gh release upload failed" >&2; exit 1; }
echo "✅ Uploaded $ASSET ($HUMAN, $COUNT transcripts) to $REPO."
