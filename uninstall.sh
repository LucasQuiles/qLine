#!/bin/bash
# Remove qLine files, hooks, and statusLine binding from ~/.claude/settings.json
set -euo pipefail

DEST_DIR="$HOME/.claude"
SETTINGS="$DEST_DIR/settings.json"

echo "=== qLine Uninstall ==="

# Remove statusLine binding from settings.json
if command -v jq > /dev/null 2>&1 && [ -f "$SETTINGS" ]; then
    if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
        TMP=$(mktemp)
        jq 'del(.statusLine)' "$SETTINGS" > "$TMP"
        if jq -e '.' "$TMP" > /dev/null 2>&1; then
            mv "$TMP" "$SETTINGS"
            echo "statusLine binding removed from $SETTINGS"
        else
            rm -f "$TMP"
            echo "ERROR: failed to create valid JSON — settings.json unchanged"
        fi
    else
        echo "No statusLine binding found in $SETTINGS"
    fi
else
    echo "NOTE: jq not found or settings.json missing — remove statusLine from settings.json manually"
fi

# Remove hook registrations from settings.json
# Only removes if ALL hooks in the hooks key are qline obs-* hooks.
# If the user has added their own hooks, we leave the key alone.
if command -v jq > /dev/null 2>&1 && [ -f "$SETTINGS" ]; then
    if jq -e 'has("hooks")' "$SETTINGS" > /dev/null 2>&1; then
        # Check if any non-obs hook commands exist
        NON_OBS=$(jq -r '[.hooks[][] | .hooks[]? | .command // empty] | map(select(test("/obs-") | not)) | length' "$SETTINGS" 2>/dev/null || echo "error")
        if [ "$NON_OBS" = "0" ]; then
            TMP=$(mktemp)
            jq 'del(.hooks)' "$SETTINGS" > "$TMP"
            if jq -e '.' "$TMP" > /dev/null 2>&1; then
                mv "$TMP" "$SETTINGS"
                echo "Hook registrations removed from $SETTINGS"
            else
                rm -f "$TMP"
                echo "WARNING: failed to remove hooks from settings.json"
            fi
        else
            echo "NOTE: hooks key in $SETTINGS contains non-qLine hooks — left intact"
            echo "      Remove the obs-* hook entries manually if desired."
        fi
    fi
fi

# Remove installed files
for f in "$DEST_DIR/statusline.py" "$DEST_DIR/obs_utils.py"; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "Removed: $f"
    fi
done

# Remove hook scripts
HOOK_COUNT=0
for f in "$DEST_DIR/hooks"/obs-*.py; do
    [ -f "$f" ] || continue
    rm "$f"
    HOOK_COUNT=$((HOOK_COUNT + 1))
done
if [ "$HOOK_COUNT" -gt 0 ]; then
    echo "Removed: $HOOK_COUNT hook scripts from $DEST_DIR/hooks/"
fi

# Remove shared libraries (only if no other scripts depend on them)
# hook_utils.py and obs_utils.py in ~/.claude/scripts/
for f in "$DEST_DIR/scripts/hook_utils.py" "$DEST_DIR/scripts/obs_utils.py"; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "Removed: $f"
    fi
done

echo ""
echo "Done. Restart Claude Code to deactivate."
echo "NOTE: ~/.config/qline.toml was not removed (delete manually if desired)"
