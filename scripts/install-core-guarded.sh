#!/bin/bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
SOURCE_FULL="$ROOT/src/statusline.py"
SOURCE_CONTEXT="$ROOT/src/context_overhead.py"
SOURCE_STATUS=""
DEST=""
BACKUP_DIR=""
EXPECT_STATUS=""
EXPECT_FULL=""
EXPECT_CONTEXT=""
STATUS_SOURCE=auto

while [ "$#" -gt 0 ]; do
    case "$1" in
        --dest) DEST=${2:?missing --dest value}; shift 2 ;;
        --backup-dir) BACKUP_DIR=${2:?missing --backup-dir value}; shift 2 ;;
        --expect-status) EXPECT_STATUS=${2:?missing --expect-status value}; shift 2 ;;
        --expect-full) EXPECT_FULL=${2:?missing --expect-full value}; shift 2 ;;
        --expect-context) EXPECT_CONTEXT=${2:?missing --expect-context value}; shift 2 ;;
        --status-source) STATUS_SOURCE=${2:?missing --status-source value}; shift 2 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$DEST" ] || [ -z "$BACKUP_DIR" ] || [ -z "$EXPECT_STATUS" ] || [ -z "$EXPECT_FULL" ] || [ -z "$EXPECT_CONTEXT" ]; then
    echo "required: --dest --backup-dir --expect-status --expect-full --expect-context" >&2
    exit 2
fi

case "$STATUS_SOURCE" in
    auto)
        if [ -x /bin/zsh ]; then
            STATUS_SOURCE=throttle
        else
            STATUS_SOURCE=full
        fi
        ;;
    throttle)
        if [ ! -x /bin/zsh ]; then
            echo "qLine throttle requires an executable /bin/zsh; use --status-source full" >&2
            exit 3
        fi
        ;;
    full) ;;
    *)
        echo "status source must be auto, throttle, or full" >&2
        exit 2
        ;;
esac
case "$STATUS_SOURCE" in
    throttle) SOURCE_STATUS="$ROOT/src/statusline-throttle.zsh" ;;
    full) SOURCE_STATUS="$SOURCE_FULL" ;;
esac

case "$(uname -s)" in
    Darwin) MODE_STAT_STYLE=darwin ;;
    Linux) MODE_STAT_STYLE=gnu ;;
    *)
        echo "unsupported platform: qLine installation supports macOS and Linux" >&2
        exit 3
        ;;
esac

sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
valid_expected() { [ "$1" = absent ] || [[ "$1" =~ ^[0-9a-f]{64}$ ]]; }
check_expected() {
    local path=$1 expected=$2
    if [ "$expected" = absent ]; then
        [ ! -e "$path" ] && [ ! -L "$path" ]
    else
        [ -f "$path" ] && [ ! -L "$path" ] && [ "$(sha256 "$path")" = "$expected" ]
    fi
}
mode_of() {
    case "$MODE_STAT_STYLE" in
        darwin) stat -f '%Lp' "$1" ;;
        gnu) stat -c '%a' "$1" ;;
    esac
}
mode_for() {
    if [ "$1" = absent ]; then
        mode_of "$2"
    else
        mode_of "$3"
    fi
}

for expected in "$EXPECT_STATUS" "$EXPECT_FULL" "$EXPECT_CONTEXT"; do
    valid_expected "$expected" || { echo "expected digests must be lowercase SHA-256 values or absent" >&2; exit 2; }
done

DEST_STATUS="$DEST/statusline.py"
DEST_FULL="$DEST/statusline_full.py"
DEST_CONTEXT="$DEST/context_overhead.py"
for path in "$SOURCE_STATUS" "$SOURCE_FULL" "$SOURCE_CONTEXT"; do
    if [ ! -f "$path" ] || [ -L "$path" ]; then
        echo "refusing non-regular or symlink source: $path" >&2
        exit 3
    fi
done
if [ ! -d "$DEST" ] || [ -L "$DEST" ] || [ -e "$BACKUP_DIR" ]; then
    echo "refusing destination or existing backup path" >&2
    exit 3
fi
for pair in "$DEST_STATUS:$EXPECT_STATUS" "$DEST_FULL:$EXPECT_FULL" "$DEST_CONTEXT:$EXPECT_CONTEXT"; do
    path=${pair%%:*}; expected=${pair#*:}
    if ! check_expected "$path" "$expected"; then
        echo "refusing: deployed source digest changed" >&2
        exit 4
    fi
done

STATUS_MODE=$(mode_for "$EXPECT_STATUS" "$SOURCE_STATUS" "$DEST_STATUS")
FULL_MODE=$(mode_for "$EXPECT_FULL" "$SOURCE_FULL" "$DEST_FULL")
CONTEXT_MODE=$(mode_for "$EXPECT_CONTEXT" "$SOURCE_CONTEXT" "$DEST_CONTEXT")
STATUS_STAGE=""; FULL_STAGE=""; CONTEXT_STAGE=""
installed_status=0; installed_full=0; installed_context=0

cleanup() { rm -f "$STATUS_STAGE" "$FULL_STAGE" "$CONTEXT_STAGE"; }
restore() {
    local rollback_failed=0 stage
    set +e
    for item in "status:$installed_status:$EXPECT_STATUS:$DEST_STATUS:$STATUS_MODE" "full:$installed_full:$EXPECT_FULL:$DEST_FULL:$FULL_MODE" "context:$installed_context:$EXPECT_CONTEXT:$DEST_CONTEXT:$CONTEXT_MODE"; do
        IFS=: read -r name installed expected path mode <<< "$item"
        [ "$installed" -eq 1 ] || continue
        if [ "$expected" = absent ]; then
            if ! rm -f -- "$path"; then
                printf 'rollback failed to remove %s\n' "$path" >&2
                rollback_failed=1
            fi
        else
            stage=$(mktemp "$DEST/.qline-rollback-${name}.XXXXXX") || {
                printf 'rollback failed to stage %s\n' "$path" >&2
                rollback_failed=1
                continue
            }
            if ! cp "$BACKUP_DIR/$(basename "$path")" "$stage" \
                || ! chmod "$mode" "$stage" \
                || ! mv -f "$stage" "$path"; then
                printf 'rollback failed for %s\n' "$path" >&2
                rollback_failed=1
                rm -f -- "$stage" || {
                    printf 'rollback failed to remove staged %s\n' "$path" >&2
                    rollback_failed=1
                }
            fi
        fi
    done
    return "$rollback_failed"
}
trap cleanup EXIT
on_error() {
    if ! restore; then
        printf 'rollback incomplete; backup retained at %s\n' "$BACKUP_DIR" >&2
    fi
    exit 5
}
trap on_error ERR

STATUS_STAGE=$(mktemp "$DEST/.qline-statusline.XXXXXX")
FULL_STAGE=$(mktemp "$DEST/.qline-full.XXXXXX")
CONTEXT_STAGE=$(mktemp "$DEST/.qline-context.XXXXXX")
cp "$SOURCE_STATUS" "$STATUS_STAGE"; chmod "$STATUS_MODE" "$STATUS_STAGE"
cp "$SOURCE_FULL" "$FULL_STAGE"; chmod "$FULL_MODE" "$FULL_STAGE"
cp "$SOURCE_CONTEXT" "$CONTEXT_STAGE"; chmod "$CONTEXT_MODE" "$CONTEXT_STAGE"
chmod u+rx "$STATUS_STAGE"
chmod u+rx "$FULL_STAGE"
test "$(sha256 "$STATUS_STAGE")" = "$(sha256 "$SOURCE_STATUS")"
test "$(sha256 "$FULL_STAGE")" = "$(sha256 "$SOURCE_FULL")"
test "$(sha256 "$CONTEXT_STAGE")" = "$(sha256 "$SOURCE_CONTEXT")"

mkdir "$BACKUP_DIR"
for pair in "$DEST_STATUS:$EXPECT_STATUS" "$DEST_FULL:$EXPECT_FULL" "$DEST_CONTEXT:$EXPECT_CONTEXT"; do
    path=${pair%%:*}; expected=${pair#*:}
    [ "$expected" = absent ] || cp -p "$path" "$BACKUP_DIR/$(basename "$path")"
done

mv -f "$STATUS_STAGE" "$DEST_STATUS"; STATUS_STAGE=""; installed_status=1
mv -f "$FULL_STAGE" "$DEST_FULL"; FULL_STAGE=""; installed_full=1
mv -f "$CONTEXT_STAGE" "$DEST_CONTEXT"; CONTEXT_STAGE=""; installed_context=1
test "$(sha256 "$DEST_STATUS")" = "$(sha256 "$SOURCE_STATUS")"
test "$(sha256 "$DEST_FULL")" = "$(sha256 "$SOURCE_FULL")"
test "$(sha256 "$DEST_CONTEXT")" = "$(sha256 "$SOURCE_CONTEXT")"
trap - ERR
echo "installed statusline_sha256=$(sha256 "$DEST_STATUS")"
echo "installed statusline_full_sha256=$(sha256 "$DEST_FULL")"
echo "installed context_sha256=$(sha256 "$DEST_CONTEXT")"
echo "installed status_source=$STATUS_SOURCE"
echo "backup=$BACKUP_DIR"
