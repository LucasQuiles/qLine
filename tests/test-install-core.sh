#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
INSTALLER="$ROOT/scripts/install-core-guarded.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

DEST="$TMP/dest"
BACKUP="$TMP/backup"
mkdir -p "$DEST"
printf '%s\n' '#!/old/python' 'old statusline' > "$DEST/statusline.py"
printf '%s\n' 'old context' > "$DEST/context_overhead.py"
chmod 755 "$DEST/statusline.py"
chmod 644 "$DEST/context_overhead.py"
STATUS_BEFORE=$(sha256 "$DEST/statusline.py")
CONTEXT_BEFORE=$(sha256 "$DEST/context_overhead.py")

"$INSTALLER" \
  --dest "$DEST" \
  --backup-dir "$BACKUP" \
  --expect-status "$STATUS_BEFORE" \
  --expect-context "$CONTEXT_BEFORE"

test "$(sha256 "$DEST/statusline.py")" = "$(sha256 "$ROOT/src/statusline.py")"
test "$(sha256 "$DEST/context_overhead.py")" = "$(sha256 "$ROOT/src/context_overhead.py")"
test "$(sha256 "$BACKUP/statusline.py")" = "$STATUS_BEFORE"
test "$(sha256 "$BACKUP/context_overhead.py")" = "$CONTEXT_BEFORE"
test "$(stat -f '%Lp' "$DEST/statusline.py")" = 755
test "$(stat -f '%Lp' "$DEST/context_overhead.py")" = 644

REFUSE_DEST="$TMP/refuse"
REFUSE_BACKUP="$TMP/refuse-backup"
mkdir -p "$REFUSE_DEST"
printf '%s\n' 'changed statusline' > "$REFUSE_DEST/statusline.py"
printf '%s\n' 'changed context' > "$REFUSE_DEST/context_overhead.py"
REFUSE_STATUS=$(sha256 "$REFUSE_DEST/statusline.py")
REFUSE_CONTEXT=$(sha256 "$REFUSE_DEST/context_overhead.py")

if "$INSTALLER" \
  --dest "$REFUSE_DEST" \
  --backup-dir "$REFUSE_BACKUP" \
  --expect-status 0000000000000000000000000000000000000000000000000000000000000000 \
  --expect-context "$REFUSE_CONTEXT" 2>"$TMP/refusal.stderr"; then
  echo "expected digest mismatch refusal" >&2
  exit 1
fi

grep -q "deployed source digest changed" "$TMP/refusal.stderr"

test "$(sha256 "$REFUSE_DEST/statusline.py")" = "$REFUSE_STATUS"
test "$(sha256 "$REFUSE_DEST/context_overhead.py")" = "$REFUSE_CONTEXT"
test ! -e "$REFUSE_BACKUP"

echo "guarded core installer: PASS"
