#!/bin/bash
# Remove qLine statusLine binding from ~/.claude/settings.json
set -euo pipefail

SETTINGS="$HOME/.claude/settings.json"

echo "=== qLine Uninstall ==="

if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
    TMP=$(mktemp)
    jq 'del(.statusLine)' "$SETTINGS" > "$TMP"
    if jq -e '.' "$TMP" > /dev/null 2>&1; then
        mv "$TMP" "$SETTINGS"
        echo "statusLine binding removed from $SETTINGS"
    else
        rm -f "$TMP"
        echo "ERROR: failed to create valid JSON"
        exit 1
    fi
else
    echo "No statusLine binding found in $SETTINGS"
fi

echo "Done. Restart Claude to deactivate."
