#!/bin/bash
# Remove qLine files and all registrations from ~/.claude/settings.json
set -euo pipefail

DEST_DIR="$HOME/.claude"
SETTINGS="$DEST_DIR/settings.json"
HOOKS_DIR="$DEST_DIR/hooks"

echo "=== qLine Uninstall ==="

# --- Remove statusLine binding ---

if command -v jq > /dev/null 2>&1 && [ -f "$SETTINGS" ]; then
    if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
        TMP=$(mktemp)
        jq 'del(.statusLine)' "$SETTINGS" > "$TMP"
        if jq -e '.' "$TMP" > /dev/null 2>&1; then
            mv "$TMP" "$SETTINGS"
            echo "statusLine binding removed from settings.json"
        else
            rm -f "$TMP"
            echo "ERROR: failed to update settings.json"
        fi
    else
        echo "No statusLine binding found"
    fi
else
    echo "NOTE: jq not found or settings.json missing — manual cleanup needed"
fi

# --- Remove obs hook registrations from settings.json ---

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" > /dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -n "$PYTHON" ] && [ -f "$SETTINGS" ]; then
    "$PYTHON" -c "
import json

with open('$SETTINGS') as f:
    settings = json.load(f)

hooks = settings.get('hooks', {})
removed = 0

# Remove any entry whose command points to our hooks dir
for event in list(hooks.keys()):
    new_entries = []
    for entry in hooks[event]:
        inner = entry.get('hooks', [])
        keep = True
        for h in inner:
            cmd = h.get('command', '')
            if '/hooks/obs-' in cmd and '$HOOKS_DIR' in cmd:
                keep = False
                removed += 1
        if keep:
            new_entries.append(entry)
    hooks[event] = new_entries

# Clean empty events
hooks = {k: v for k, v in hooks.items() if v}
settings['hooks'] = hooks

with open('$SETTINGS', 'w') as f:
    json.dump(settings, f, indent=2)

if removed:
    print(f'Removed {removed} obs hook registrations from settings.json')
else:
    print('No obs hook registrations found in settings.json')
" 2>/dev/null
fi

# --- Remove installed files ---

for f in "$DEST_DIR/statusline.py" "$DEST_DIR/obs_utils.py" "$DEST_DIR/context_overhead.py"; do
    if [ -f "$f" ]; then
        rm "$f"
        echo "Removed: $f"
    fi
done

# --- Remove observability hooks ---

HOOKS_REMOVED=0
for hook in "$HOOKS_DIR/obs-"*.py; do
    [ -f "$hook" ] || continue
    rm -f "$hook"
    HOOKS_REMOVED=$((HOOKS_REMOVED + 1))
done
[ "$HOOKS_REMOVED" -gt 0 ] && echo "Removed: $HOOKS_REMOVED observability hooks"

# --- Remove shared scripts (only qLine-owned) ---

rm -f "$DEST_DIR/scripts/obs_utils.py" "$DEST_DIR/scripts/hook_utils.py"
echo "Removed: shared scripts (obs_utils.py, hook_utils.py)"

# --- Summary ---

echo ""
echo "Done. Restart Claude Code to deactivate."
echo "NOTE: ~/.config/qline.toml was not removed (delete manually if desired)"
