#!/bin/bash
# Install qLine — Claude Code status line + optional observability hooks
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="$HOME/.claude"
SETTINGS="$DEST_DIR/settings.json"

# --- Parse args ---
WITH_OBS=true
for arg in "$@"; do
    case "$arg" in
        --no-obs) WITH_OBS=false ;;
        --help|-h)
            echo "Usage: ./install.sh [--no-obs]"
            echo ""
            echo "  Default:     Install statusline + observability hooks"
            echo "  --no-obs:    Skip observability hooks"
            echo ""
            exit 0
            ;;
        *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
    esac
done

echo "=== qLine Install ==="
if [ "$WITH_OBS" = true ]; then
    echo "Mode: statusline + observability hooks"
else
    echo "Mode: statusline only"
fi

# --- Pre-flight checks ---

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$candidate" > /dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: No python3 found in PATH"
    exit 1
fi

read PY_MAJOR PY_MINOR <<< $("$PYTHON" -c 'import sys; v=sys.version_info; print(v.major, v.minor)')
PY_VERSION="$PY_MAJOR.$PY_MINOR"

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi

if [ "$PY_MINOR" -lt 11 ]; then
    echo "NOTE: Python $PY_VERSION — TOML config requires 3.11+. Defaults will be used."
fi

echo "Python: $PYTHON ($PY_VERSION)"

if [ ! -d "$DEST_DIR" ]; then
    echo "ERROR: $DEST_DIR does not exist. Is Claude Code installed?"
    exit 1
fi

JQ_AVAILABLE=false
if command -v jq > /dev/null 2>&1; then
    JQ_AVAILABLE=true
else
    echo "WARNING: jq not found — cannot patch settings.json automatically."
fi

# --- Install core files ---

cp "$SCRIPT_DIR/src/statusline.py" "$DEST_DIR/statusline.py"
chmod +x "$DEST_DIR/statusline.py"
echo "Installed: $DEST_DIR/statusline.py"

cp "$SCRIPT_DIR/src/context_overhead.py" "$DEST_DIR/context_overhead.py"
echo "Installed: $DEST_DIR/context_overhead.py"

# obs_utils + hook_utils: statusline needs these at runtime.
# When the plugin symlink exists, statusline.py imports from the plugin dir
# (canonical, repo-managed). Copy to ~/.claude/ as fallback for non-plugin installs.
if [ -L "$DEST_DIR/plugins/qline" ] || [ -d "$DEST_DIR/plugins/qline" ]; then
    # Plugin active — clean up stale copies that would shadow the plugin version
    for stale in "$DEST_DIR/obs_utils.py" "$DEST_DIR/hook_utils.py" \
                 "$DEST_DIR/scripts/obs_utils.py" "$DEST_DIR/scripts/hook_utils.py"; do
        if [ -f "$stale" ] && [ ! -L "$stale" ]; then
            rm -f "$stale"
            echo "Removed stale: $stale"
        fi
    done
    echo "Plugin active — obs_utils imported from plugin dir"
else
    # No plugin — copy modules as fallback
    cp "$SCRIPT_DIR/hooks/obs_utils.py" "$DEST_DIR/obs_utils.py"
    cp "$SCRIPT_DIR/hooks/hook_utils.py" "$DEST_DIR/hook_utils.py"
    echo "Installed: $DEST_DIR/obs_utils.py, hook_utils.py"
fi

# Fix shebang if needed
if ! command -v python3 > /dev/null 2>&1; then
    REAL_PYTHON=$(command -v "$PYTHON")
    sed -i'' -e "1s|.*|#!$REAL_PYTHON|" "$DEST_DIR/statusline.py"
    echo "Shebang updated to: #!$REAL_PYTHON"
elif [ "$PYTHON" != "python3" ]; then
    PY3_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
    if [ "$PY3_MINOR" -lt 10 ]; then
        REAL_PYTHON=$(command -v "$PYTHON")
        sed -i'' -e "1s|.*|#!$REAL_PYTHON|" "$DEST_DIR/statusline.py"
        echo "Shebang updated to: #!$REAL_PYTHON"
    fi
fi

# --- Patch statusLine binding ---

if [ "$JQ_AVAILABLE" = true ] && [ -f "$SETTINGS" ]; then
    if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
        echo "statusLine binding already present"
    else
        BACKUP="$DEST_DIR/backups/qline-install-$(date +%Y%m%d-%H%M%S)"
        mkdir -p "$BACKUP"
        cp "$SETTINGS" "$BACKUP/settings.json.bak"
        echo "Backup: $BACKUP/settings.json.bak"

        TMP=$(mktemp)
        jq --arg cmd "$DEST_DIR/statusline.py" '. + {"statusLine": {"type": "command", "command": $cmd}}' "$SETTINGS" > "$TMP"
        if jq -e '.' "$TMP" > /dev/null 2>&1; then
            mv "$TMP" "$SETTINGS"
            echo "statusLine binding added to settings.json"
        else
            rm -f "$TMP"
            echo "ERROR: failed to create valid JSON — settings.json unchanged"
        fi
    fi
elif [ ! -f "$SETTINGS" ]; then
    jq -n --arg cmd "$DEST_DIR/statusline.py" '{"statusLine": {"type": "command", "command": $cmd}}' > "$SETTINGS" 2>/dev/null || \
    echo "{\"statusLine\":{\"type\":\"command\",\"command\":\"$DEST_DIR/statusline.py\"}}" > "$SETTINGS"
fi

# --- Install observability (optional) ---

if [ "$WITH_OBS" = true ]; then
    echo ""
    echo "--- Observability hooks ---"

    # Check if qLine plugin is already active (manages hooks via hooks.json)
    if [ -L "$DEST_DIR/plugins/qline" ] || [ -d "$DEST_DIR/plugins/qline" ]; then
        echo "qLine plugin detected — hooks are managed by the plugin."
        echo "Skipping hook copy and registration."
        echo "To update hooks, modify hooks/hooks.json and re-sync settings.json."
    else
        HOOKS_DIR="$DEST_DIR/hooks"
        mkdir -p "$HOOKS_DIR"

        # Copy hooks + their support modules into the hooks dir
        for f in "$SCRIPT_DIR/hooks/obs-"*.py \
                 "$SCRIPT_DIR/hooks/precompact-preserve.py" \
                 "$SCRIPT_DIR/hooks/session-end-summary.py" \
                 "$SCRIPT_DIR/hooks/subagent-stop-gate.py" \
                 "$SCRIPT_DIR/hooks/task-completed-gate.py" \
                 "$SCRIPT_DIR/hooks/hook_utils.py" \
                 "$SCRIPT_DIR/hooks/obs_utils.py"; do
            [ -f "$f" ] || continue
            cp "$f" "$HOOKS_DIR/"
            chmod +x "$HOOKS_DIR/$(basename "$f")"
        done
        echo "Installed: hooks to $HOOKS_DIR/"

        # Register hooks in settings.json (inline)
        if [ "$JQ_AVAILABLE" = true ] && [ -f "$SETTINGS" ]; then
            echo "Registering obs hooks in settings.json..."
            "$PYTHON" -c "
import json, sys

settings_path = '$SETTINGS'
hooks_dir = '$HOOKS_DIR'

with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.setdefault('hooks', {})

OBS_HOOKS = [
    ('SessionStart', '.*', 'obs-session-start.py', 5000),
    ('PreToolUse', 'Read', 'obs-pretool-read.py', 5000),
    ('PostToolUse', 'Write', 'obs-posttool-write.py', 5000),
    ('PostToolUse', 'Bash', 'obs-posttool-bash.py', 5000),
    ('PostToolUse', 'Edit|MultiEdit', 'obs-posttool-edit.py', 5000),
    ('PostToolUseFailure', '.*', 'obs-posttool-failure.py', 5000),
    ('UserPromptSubmit', '.*', 'obs-prompt-submit.py', 5000),
    ('Stop', '.*', 'obs-stop-cache.py', 2000),
    ('PreCompact', '.*', 'obs-precompact.py', 5000),
    ('PreCompact', '.*', 'precompact-preserve.py', 5000),
    ('SubagentStop', '.*', 'obs-subagent-stop.py', 5000),
    ('SubagentStop', '.*', 'subagent-stop-gate.py', 5000),
    ('SessionEnd', '.*', 'obs-session-end.py', 5000),
    ('SessionEnd', '.*', 'session-end-summary.py', 5000),
    ('TaskCompleted', '.*', 'obs-task-completed.py', 5000),
    ('TaskCompleted', '.*', 'task-completed-gate.py', 5000),
]

registered = 0
for event, matcher, filename, timeout in OBS_HOOKS:
    command = f'{hooks_dir}/{filename}'
    event_hooks = hooks.setdefault(event, [])
    already = any(
        any(h.get('command') == command for h in entry.get('hooks', []))
        for entry in event_hooks
    )
    if not already:
        entry = {'hooks': [{'type': 'command', 'command': command, 'timeout': timeout}]}
        if matcher != '.*':
            entry['matcher'] = matcher
        event_hooks.append(entry)
        registered += 1

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print(f'  Registered {registered} hooks ({len(OBS_HOOKS) - registered} already present)')
"
        else
            echo "WARNING: Could not register hooks (jq or settings.json missing)"
        fi
    fi
fi

# --- Summary ---

echo ""
echo "=== Setup Complete ==="
echo "  Restart Claude Code to activate."
if [ "$WITH_OBS" = true ]; then
    echo "  Statusline + observability hooks installed."
else
    echo "  Statusline only (observability skipped)."
fi
echo ""
echo "  Optional: customize theme:"
echo "    cp $SCRIPT_DIR/qline.example.toml ~/.config/qline.toml"
echo ""
echo "  Nerd Font required for glyphs — install on your LOCAL terminal:"
echo "    https://github.com/ryanoasis/nerd-fonts"
