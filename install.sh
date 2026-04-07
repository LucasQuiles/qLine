#!/bin/bash
# Install qLine — Claude Code status line + optional observability hooks
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="$HOME/.claude"
SETTINGS="$DEST_DIR/settings.json"

# --- Parse args ---
WITH_OBS=false
for arg in "$@"; do
    case "$arg" in
        --with-obs) WITH_OBS=true ;;
        --help|-h)
            echo "Usage: ./install.sh [--with-obs]"
            echo ""
            echo "  Default:     Install statusline only (one styled bar in Claude Code)"
            echo "  --with-obs:  Also install observability hooks (session tracking,"
            echo "               tool recording, compaction monitoring)"
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

PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')

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

cp "$SCRIPT_DIR/scripts/obs_utils.py" "$DEST_DIR/obs_utils.py"
echo "Installed: $DEST_DIR/obs_utils.py"

# Fix shebang if needed
if ! command -v python3 > /dev/null 2>&1; then
    REAL_PYTHON=$(command -v "$PYTHON")
    sed -i "1s|.*|#!$REAL_PYTHON|" "$DEST_DIR/statusline.py"
    echo "Shebang updated to: #!$REAL_PYTHON"
elif [ "$PYTHON" != "python3" ]; then
    PY3_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
    if [ "$PY3_MINOR" -lt 10 ]; then
        REAL_PYTHON=$(command -v "$PYTHON")
        sed -i "1s|.*|#!$REAL_PYTHON|" "$DEST_DIR/statusline.py"
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

    SCRIPTS_DIR="$DEST_DIR/scripts"
    HOOKS_DIR="$DEST_DIR/hooks"
    mkdir -p "$SCRIPTS_DIR" "$HOOKS_DIR"

    # Shared utilities
    cp "$SCRIPT_DIR/scripts/hook_utils.py" "$SCRIPTS_DIR/hook_utils.py"
    echo "Installed: $SCRIPTS_DIR/hook_utils.py"

    cp "$SCRIPT_DIR/scripts/obs_utils.py" "$SCRIPTS_DIR/obs_utils.py"
    echo "Installed: $SCRIPTS_DIR/obs_utils.py"

    # Obs hooks
    HOOKS_INSTALLED=0
    for hook in "$SCRIPT_DIR/hooks/obs-"*.py; do
        [ -f "$hook" ] || continue
        cp "$hook" "$HOOKS_DIR/"
        chmod +x "$HOOKS_DIR/$(basename "$hook")"
        HOOKS_INSTALLED=$((HOOKS_INSTALLED + 1))
    done
    echo "Installed: $HOOKS_INSTALLED observability hooks to $HOOKS_DIR/"

    # Register hooks in settings.json
    if [ "$JQ_AVAILABLE" = true ] && [ -f "$SETTINGS" ]; then
        echo "Registering obs hooks in settings.json..."
        "$PYTHON" "$SCRIPT_DIR/scripts/register_obs_hooks.py" "$SETTINGS" "$HOOKS_DIR"
    else
        echo "WARNING: Could not register hooks (jq or settings.json missing)"
        echo "         Hooks are installed but may not fire without manual registration"
    fi
fi

# --- Summary ---

echo ""
echo "=== Setup Complete ==="
echo "  Restart Claude Code to activate."
if [ "$WITH_OBS" = true ]; then
    echo "  Statusline + observability hooks installed."
else
    echo "  Statusline installed. Run with --with-obs for observability hooks."
fi
echo ""
echo "  Optional: customize theme:"
echo "    cp $SCRIPT_DIR/qline.example.toml ~/.config/qline.toml"
echo ""
echo "  Nerd Font required for glyphs — install on your LOCAL terminal:"
echo "    https://github.com/ryanoasis/nerd-fonts"
