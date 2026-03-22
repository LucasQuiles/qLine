#!/bin/bash
# Remove qLine files and statusLine binding from ~/.claude/settings.json
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

# Remove installed files
for f in "$DEST_DIR/statusline.py" "$DEST_DIR/obs_utils.py"; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "Removed: $f"
    fi
done

echo ""
echo "Done. Restart Claude Code to deactivate."
echo "NOTE: ~/.config/qline.toml was not removed (delete manually if desired)"
