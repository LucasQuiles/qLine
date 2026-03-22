#!/bin/bash
# Update qLine to the latest version
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== qLine Update ==="

cd "$SCRIPT_DIR"
git pull --ff-only || { echo "ERROR: git pull failed — resolve manually"; exit 1; }
exec ./install.sh
