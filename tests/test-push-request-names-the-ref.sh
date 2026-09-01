#!/usr/bin/env bash
# A tag push and a branch push must not look identical in the approval inbox.
#
# Kyle, 2026-08-31, after approving a push and then being asked again by what looked like the
# same request: "didn't see any new ones to tap." The first was `master`, the second was the TAG
# for the same release. The gate was behaving correctly — one grant is one push — and the inbox
# could not say so, because every request rendered as the repo name and nothing else.
#
# That is the approval loop v2.41 exists to end, arriving through the DISPLAY rather than the
# policy: an approval the human has already given, asked for a second time in a form they cannot
# distinguish from the first. git hands the hook the refs on stdin; the hook was reading them for
# their shas and discarding the names.
set -uo pipefail

HOOK="$(cd "$(dirname "$0")/.." && pwd)/bus/git-hooks/pre-push"
pass=0; fail=0
ok()  { pass=$((pass+1)); echo "  ok   $1"; }
bad() { fail=$((fail+1)); echo "  FAIL $1"; }
command -v git >/dev/null 2>&1 || { echo "git unavailable — skipping"; exit 0; }

SB="$(mktemp -d)"; trap 'rm -rf "$SB"' EXIT
export COORD_STATE_DIR="$SB/coord"
mkdir -p "$COORD_STATE_DIR/push-tokens" "$COORD_STATE_DIR/push-requests" "$COORD_STATE_DIR/push-claims"

wt="$SB/wt"; up="$SB/up"
git init -q --bare "$up"
git init -q -b main "$wt"
git -C "$wt" config user.email t@t; git -C "$wt" config user.name t
git -C "$wt" remote add origin "$up"
echo one > "$wt/a.txt"; git -C "$wt" add -A; git -C "$wt" commit -qm one
SHA="$(git -C "$wt" rev-parse HEAD)"
git -C "$wt" tag -a v9.9.9 -m nine
KEY="$(printf '%s' "$wt" | tr -cs 'A-Za-z0-9._-' '_' | sed 's/^_*//;s/_*$//')"
ZERO=0000000000000000000000000000000000000000

# Drive the hook with EXACTLY what git writes on stdin: <lref> <lsha> <rref> <rsha>
attempt() {
  rm -f "$COORD_STATE_DIR/push-requests/$KEY"
  printf '%s\n' "$1" | (cd "$wt" && bash "$HOOK" origin "$up" >/dev/null 2>"$SB/err")
  grep -E '^refs=' "$COORD_STATE_DIR/push-requests/$KEY" 2>/dev/null | sed 's/^refs=//'
}

# 1. A branch push names the branch.
got="$(attempt "refs/heads/main $SHA refs/heads/main $ZERO")"
[ "$got" = "main" ] && ok "branch push files refs=main" || bad "branch: got '$got'"

# 2. ⭐ A TAG push says TAG. This is the one Kyle could not tell apart.
got="$(attempt "refs/tags/v9.9.9 $SHA refs/tags/v9.9.9 $ZERO")"
[ "$got" = "tag v9.9.9" ] && ok "⭐ tag push files refs='tag v9.9.9'" || bad "tag: got '$got'"

# 3. They must DIFFER, which is the whole property — asserting each in isolation would pass
#    against a hook that wrote the same constant twice.
a="$(attempt "refs/heads/main $SHA refs/heads/main $ZERO")"
b="$(attempt "refs/tags/v9.9.9 $SHA refs/tags/v9.9.9 $ZERO")"
[ "$a" != "$b" ] && ok "the two are distinguishable in the inbox" || bad "both render as '$a'"

# 4. A delete is a real, gated push and must say so rather than look like an update.
got="$(attempt "(delete) $ZERO refs/heads/old $SHA")"
case "$got" in *"delete old"*) ok "a branch delete says delete" ;; *) bad "delete: got '$got'" ;; esac

# 5. Several refs at once are all named — `git push --tags` is one attempt, many refs.
got="$(attempt "$(printf 'refs/heads/main %s refs/heads/main %s\nrefs/tags/v9.9.9 %s refs/tags/v9.9.9 %s' "$SHA" "$ZERO" "$SHA" "$ZERO")")"
case "$got" in *main*"tag v9.9.9"*) ok "a multi-ref push names them all" ;; *) bad "multi: got '$got'" ;; esac

# 6. The DENIAL TEXT says it too — that is where the pushing session reads it, and a session
#    that knows it is asking for a tag can say so instead of re-asking for "the push".
printf '%s\n' "refs/tags/v9.9.9 $SHA refs/tags/v9.9.9 $ZERO" \
  | (cd "$wt" && bash "$HOOK" origin "$up" >/dev/null 2>"$SB/err2")
grep -q 'tag v9.9.9' "$SB/err2" && ok "the denial message names the tag" \
  || bad "denial text still says only the repo: $(head -c 90 "$SB/err2")"

# 7. CONTROL: a no-op push must still be allowed and file NOTHING. Naming refs must not turn an
#    up-to-date push into a request.
rm -f "$COORD_STATE_DIR/push-requests/$KEY"
printf '%s\n' "refs/heads/main $SHA refs/heads/main $SHA" \
  | (cd "$wt" && bash "$HOOK" origin "$up" >/dev/null 2>&1)
rc=$?
[ "$rc" = 0 ] && [ ! -f "$COORD_STATE_DIR/push-requests/$KEY" ] \
  && ok "a no-op push is still allowed and files no request" \
  || bad "no-op push now files a request (rc=$rc)"

echo "── push-request-names-the-ref: $pass passed, $fail failed"
[ "$fail" = 0 ]
