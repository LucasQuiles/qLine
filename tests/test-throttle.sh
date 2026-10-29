#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE="$ROOT/src/statusline-throttle.zsh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

test -x "$SOURCE"
mkdir -p "$TMP/bin" "$TMP/cache"
cp "$SOURCE" "$TMP/bin/statusline.py"
chmod 755 "$TMP/bin/statusline.py"
# shellcheck disable=SC2016 # The fixture must expand these values when it runs.
printf '%s\n' \
  '#!/bin/sh' \
  'payload=$(cat)' \
  'count=0' \
  '[ -f "$QLINE_THROTTLE_COUNT" ] && count=$(cat "$QLINE_THROTTLE_COUNT")' \
  'count=$((count + 1))' \
  'printf "%s" "$count" > "$QLINE_THROTTLE_COUNT"' \
  'printf "render-%s" "$count"' > "$TMP/bin/statusline_full.py"
chmod 755 "$TMP/bin/statusline_full.py"

COUNT="$TMP/count"
TRANSCRIPT="$TMP/transcript with spaces.jsonl"
touch "$TRANSCRIPT"
PAYLOAD=$(printf '{"session_id":"alpha_1","transcript_path":"%s"}' "$TRANSCRIPT")
run() {
  printf '%s' "$1" | env TMPDIR="$TMP/cache" QLINE_THROTTLE_COUNT="$COUNT" QLINE_THROTTLE_TTL="$2" "$TMP/bin/statusline.py"
}

test "$(run "$PAYLOAD" 10)" = "render-1"
CACHE="$TMP/cache/qline-throttle/alpha_1"
test -f "$CACHE"
touch -t 200001010101 "$CACHE"
MTIME=$(stat -f '%m' "$CACHE")
test "$(run "$PAYLOAD" 10)" = "render-1"
test "$(stat -f '%m' "$CACHE")" = "$MTIME"

touch -t 203001010101 "$TRANSCRIPT"
test "$(run "$PAYLOAD" 10)" = "render-2"
test "$(run "$PAYLOAD" 0)" = "render-3"

# A clock rollback must not make a future cache timestamp valid indefinitely.
CACHE_REWRITE="$TMP/cache-rewrite"
FUTURE_CACHED_AT=$(( $(date +%s) + 3600 ))
{
  IFS=' ' read -r _ CACHED_MTIME CACHED_SIZE
  printf '%s %s %s\n' "$FUTURE_CACHED_AT" "$CACHED_MTIME" "$CACHED_SIZE"
  cat
} < "$CACHE" > "$CACHE_REWRITE"
mv "$CACHE_REWRITE" "$CACHE"
test "$(run "$PAYLOAD" 10)" = "render-4"

# Transcript size changes invalidate a cache entry even when the mtime matches.
printf x >> "$TRANSCRIPT"
touch -t 203001010101 "$TRANSCRIPT"
test "$(run "$PAYLOAD" 10)" = "render-5"

MISSING=$(printf '{"session_id":"missing","transcript_path":"%s"}' "$TMP/no-such-transcript")
test "$(run "$MISSING" 10)" = "render-6"
test ! -e "$TMP/cache/qline-throttle/missing"

NO_SESSION=$(printf '{"transcript_path":"%s"}' "$TRANSCRIPT")
test "$(run "$NO_SESSION" 10)" = "render-7"

TRAVERSAL=$(printf '{"session_id":"../escape","transcript_path":"%s"}' "$TRANSCRIPT")
test "$(run "$TRAVERSAL" 10)" = "render-8"
test ! -e "$TMP/cache/escape"

MALFORMED=$(printf '{"session_id":"bad/path","transcript_path":"%s"}' "$TRANSCRIPT")
test "$(run "$MALFORMED" 10)" = "render-9"
test ! -e "$TMP/cache/qline-throttle/bad"

rm -f "$TMP/cache/qline-throttle/alpha_1"
rmdir "$TMP/cache/qline-throttle"
ln -s "$TMP/unsafe-target" "$TMP/cache/qline-throttle"
mkdir "$TMP/unsafe-target"
SAFE_CACHE=$(printf '{"session_id":"safe","transcript_path":"%s"}' "$TRANSCRIPT")
test "$(run "$SAFE_CACHE" 10)" = "render-10"
test ! -e "$TMP/unsafe-target/safe"

echo "throttle: PASS"
