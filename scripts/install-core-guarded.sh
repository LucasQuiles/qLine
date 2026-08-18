#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_STATUS="$ROOT/src/statusline.py"
SOURCE_CONTEXT="$ROOT/src/context_overhead.py"
DEST=""
BACKUP_DIR=""
EXPECT_STATUS=""
EXPECT_CONTEXT=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dest) DEST=${2:?missing --dest value}; shift 2 ;;
        --backup-dir) BACKUP_DIR=${2:?missing --backup-dir value}; shift 2 ;;
        --expect-status) EXPECT_STATUS=${2:?missing --expect-status value}; shift 2 ;;
        --expect-context) EXPECT_CONTEXT=${2:?missing --expect-context value}; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$DEST" ] || [ -z "$BACKUP_DIR" ] || [ -z "$EXPECT_STATUS" ] || [ -z "$EXPECT_CONTEXT" ]; then
    echo "required: --dest --backup-dir --expect-status --expect-context" >&2
    exit 2
fi

if [[ ! "$EXPECT_STATUS" =~ ^[0-9a-f]{64}$ ]] || [[ ! "$EXPECT_CONTEXT" =~ ^[0-9a-f]{64}$ ]]; then
    echo "expected digests must be lowercase SHA-256 values" >&2
    exit 2
fi

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

DEST_STATUS="$DEST/statusline.py"
DEST_CONTEXT="$DEST/context_overhead.py"
for path in "$SOURCE_STATUS" "$SOURCE_CONTEXT" "$DEST_STATUS" "$DEST_CONTEXT"; do
    if [ ! -f "$path" ] || [ -L "$path" ]; then
        echo "refusing non-regular or symlink path: $path" >&2
        exit 3
    fi
done
if [ -e "$BACKUP_DIR" ]; then
    echo "refusing existing backup path: $BACKUP_DIR" >&2
    exit 3
fi

ACTUAL_STATUS=$(sha256 "$DEST_STATUS")
ACTUAL_CONTEXT=$(sha256 "$DEST_CONTEXT")
if [ "$ACTUAL_STATUS" != "$EXPECT_STATUS" ] || [ "$ACTUAL_CONTEXT" != "$EXPECT_CONTEXT" ]; then
    echo "refusing: deployed source digest changed" >&2
    echo "status=$ACTUAL_STATUS context=$ACTUAL_CONTEXT" >&2
    exit 4
fi

STATUS_MODE=$(stat -f '%Lp' "$DEST_STATUS")
CONTEXT_MODE=$(stat -f '%Lp' "$DEST_CONTEXT")
STATUS_STAGE=$(mktemp "$DEST/.qline-statusline.XXXXXX")
CONTEXT_STAGE=$(mktemp "$DEST/.qline-context.XXXXXX")
installed_status=0
installed_context=0

cleanup() {
    rm -f "$STATUS_STAGE" "$CONTEXT_STAGE"
}

rollback() {
    if [ "$installed_status" -eq 1 ] && [ -f "$BACKUP_DIR/statusline.py" ]; then
        cp "$BACKUP_DIR/statusline.py" "$STATUS_STAGE"
        chmod "$STATUS_MODE" "$STATUS_STAGE"
        mv -f "$STATUS_STAGE" "$DEST_STATUS"
    fi
    if [ "$installed_context" -eq 1 ] && [ -f "$BACKUP_DIR/context_overhead.py" ]; then
        cp "$BACKUP_DIR/context_overhead.py" "$CONTEXT_STAGE"
        chmod "$CONTEXT_MODE" "$CONTEXT_STAGE"
        mv -f "$CONTEXT_STAGE" "$DEST_CONTEXT"
    fi
}

trap cleanup EXIT
trap 'rollback; exit 5' ERR

cp "$SOURCE_STATUS" "$STATUS_STAGE"
cp "$SOURCE_CONTEXT" "$CONTEXT_STAGE"
chmod "$STATUS_MODE" "$STATUS_STAGE"
chmod "$CONTEXT_MODE" "$CONTEXT_STAGE"

test "$(sha256 "$STATUS_STAGE")" = "$(sha256 "$SOURCE_STATUS")"
test "$(sha256 "$CONTEXT_STAGE")" = "$(sha256 "$SOURCE_CONTEXT")"

mkdir "$BACKUP_DIR"
cp -p "$DEST_STATUS" "$BACKUP_DIR/statusline.py"
cp -p "$DEST_CONTEXT" "$BACKUP_DIR/context_overhead.py"

mv -f "$STATUS_STAGE" "$DEST_STATUS"
installed_status=1
mv -f "$CONTEXT_STAGE" "$DEST_CONTEXT"
installed_context=1

test "$(sha256 "$DEST_STATUS")" = "$(sha256 "$SOURCE_STATUS")"
test "$(sha256 "$DEST_CONTEXT")" = "$(sha256 "$SOURCE_CONTEXT")"

trap - ERR
echo "installed statusline_sha256=$(sha256 "$DEST_STATUS")"
echo "installed context_sha256=$(sha256 "$DEST_CONTEXT")"
echo "backup=$BACKUP_DIR"
