#!/usr/bin/env bash
# Build the Vue frontend and copy dist into the Python package static/ dir.
#
# Usage:
#   ./scripts/build_frontend.sh
#
# Prerequisites: Node.js 18+ and npm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
STATIC_DIR="$REPO_ROOT/src/spectrasherpa_lite/static"

echo "Building frontend..."
cd "$FRONTEND_DIR"
npm ci
npm run build

echo "Copying dist to $STATIC_DIR..."
rm -rf "$STATIC_DIR"
mkdir -p "$STATIC_DIR"
cp -r "$FRONTEND_DIR/dist/"* "$STATIC_DIR/"

echo "Done. Frontend assets are in $STATIC_DIR"
