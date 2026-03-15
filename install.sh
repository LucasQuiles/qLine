#!/bin/bash
# Install qLine statusline.py to ~/.claude/statusline.py
# and add statusLine binding to ~/.claude/settings.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$SCRIPT_DIR/src/statusline.py"
DEST="$HOME/.claude/statusline.py"
SETTINGS="$HOME/.claude/settings.json"

echo "=== qLine Install ==="

# 1. Copy source
cp "$SRC" "$DEST"
chmod +x "$DEST"
echo "Installed: $DEST"

# 2. Add binding if not present
if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
    echo "statusLine binding already present in $SETTINGS"
else
    BACKUP="$HOME/.claude/backups/statusline-install-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$BACKUP"
    cp "$SETTINGS" "$BACKUP/settings.json.bak"
    echo "Backup: $BACKUP/settings.json.bak"

    TMP=$(mktemp)
    jq '. + {"statusLine": {"type": "command", "command": "'"$DEST"'"}}' "$SETTINGS" > "$TMP"
    if jq -e '.' "$TMP" > /dev/null 2>&1; then
        mv "$TMP" "$SETTINGS"
        echo "statusLine binding added to $SETTINGS"
    else
        rm -f "$TMP"
        echo "ERROR: failed to create valid JSON"
        exit 1
    fi
fi

echo "Done. Restart Claude to activate."
