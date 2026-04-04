#!/bin/bash
# Install qLine statusline.py + obs_utils.py to ~/.claude/
# and add statusLine binding to ~/.claude/settings.json
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEST_DIR="$HOME/.claude"
DEST="$DEST_DIR/statusline.py"
OBS_SRC="$SCRIPT_DIR/src/obs_utils.py"
OBS_DEST="$DEST_DIR/obs_utils.py"
SETTINGS="$DEST_DIR/settings.json"

echo "=== qLine Install ==="

# --- Pre-flight checks ---

# Python version
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
    echo "NOTE: Python $PY_VERSION detected — tomllib requires 3.11+."
    echo "      TOML config (~/.config/qline.toml) will be ignored; defaults used."
    echo "      Install 'tomli' (pip install tomli) for TOML support on 3.10."
fi

echo "Python: $PYTHON ($PY_VERSION)"

# Ensure ~/.claude exists
if [ ! -d "$DEST_DIR" ]; then
    echo "ERROR: $DEST_DIR does not exist. Is Claude Code installed?"
    exit 1
fi

# Check for jq (needed for settings.json patching)
if ! command -v jq > /dev/null 2>&1; then
    echo "WARNING: jq not found — cannot patch settings.json automatically."
    echo "         You'll need to manually add statusLine config (see README)."
    JQ_AVAILABLE=false
else
    JQ_AVAILABLE=true
fi

# --- Install files ---

cp "$SCRIPT_DIR/src/statusline.py" "$DEST"
chmod +x "$DEST"
echo "Installed: $DEST"

# Install obs_utils.py (observability support)
if [ -f "$OBS_SRC" ]; then
    cp "$OBS_SRC" "$OBS_DEST"
    echo "Installed: $OBS_DEST"
else
    echo "NOTE: obs_utils.py not found in repo — obs modules will be disabled"
fi

# Install context_overhead.py (overhead monitor module)
OVERHEAD_SRC="$SCRIPT_DIR/src/context_overhead.py"
OVERHEAD_DEST="$DEST_DIR/context_overhead.py"
if [ -f "$OVERHEAD_SRC" ]; then
    cp "$OVERHEAD_SRC" "$OVERHEAD_DEST"
    echo "Installed: $OVERHEAD_DEST"
fi

# Install shared scripts (obs_utils.py, hook_utils.py)
SCRIPTS_DIR="$DEST_DIR/scripts"
mkdir -p "$SCRIPTS_DIR"
for script in "$SCRIPT_DIR/scripts/"*.py; do
    [ -f "$script" ] || continue
    cp "$script" "$SCRIPTS_DIR/"
    echo "Installed: $SCRIPTS_DIR/$(basename "$script")"
done

# Install observability hooks
HOOKS_DIR="$DEST_DIR/hooks"
mkdir -p "$HOOKS_DIR"
HOOKS_INSTALLED=0
for hook in "$SCRIPT_DIR/hooks/obs-"*.py; do
    [ -f "$hook" ] || continue
    cp "$hook" "$HOOKS_DIR/"
    chmod +x "$HOOKS_DIR/$(basename "$hook")"
    HOOKS_INSTALLED=$((HOOKS_INSTALLED + 1))
done
if [ "$HOOKS_INSTALLED" -gt 0 ]; then
    echo "Installed: $HOOKS_INSTALLED observability hooks to $HOOKS_DIR/"
else
    echo "NOTE: No obs hooks found in repo — observability will be limited"
fi

# Fix shebang only if `python3` doesn't exist or is too old
if ! command -v python3 > /dev/null 2>&1; then
    # python3 missing — use whatever we found
    REAL_PYTHON=$(command -v "$PYTHON")
    sed -i "1s|.*|#!$REAL_PYTHON|" "$DEST"
    echo "Shebang updated to: #!$REAL_PYTHON"
elif [ "$PYTHON" != "python3" ]; then
    # python3 exists but we picked a different one (e.g., python3.11)
    # Check if python3 is actually too old
    PY3_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
    if [ "$PY3_MINOR" -lt 10 ]; then
        REAL_PYTHON=$(command -v "$PYTHON")
        sed -i "1s|.*|#!$REAL_PYTHON|" "$DEST"
        echo "Shebang updated to: #!$REAL_PYTHON"
    fi
fi

# --- Patch settings.json ---

if [ "$JQ_AVAILABLE" = true ] && [ -f "$SETTINGS" ]; then
    if jq -e 'has("statusLine")' "$SETTINGS" > /dev/null 2>&1; then
        echo "statusLine binding already present in $SETTINGS"
    else
        BACKUP="$DEST_DIR/backups/statusline-install-$(date +%Y%m%d-%H%M%S)"
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
            echo "ERROR: failed to create valid JSON — settings.json unchanged"
        fi
    fi
elif [ ! -f "$SETTINGS" ]; then
    echo "NOTE: $SETTINGS not found — creating minimal config"
    echo '{"statusLine":{"type":"command","command":"'"$DEST"'"}}' | jq . > "$SETTINGS" 2>/dev/null || \
    echo '{"statusLine":{"type":"command","command":"'"$DEST"'"}}' > "$SETTINGS"
fi

# --- Post-install summary ---

echo ""
echo "=== Setup Complete ==="
echo "  Restart Claude Code to activate."
echo ""
echo "  Optional: copy the example config to customize:"
echo "    cp $(dirname "$0")/qline.example.toml ~/.config/qline.toml"
echo ""
echo "  Nerd Font required for glyphs — install on your LOCAL terminal:"
echo "    https://github.com/ryanoasis/nerd-fonts"
