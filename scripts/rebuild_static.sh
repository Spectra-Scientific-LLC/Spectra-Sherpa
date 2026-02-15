#!/usr/bin/env bash
# Rebuild the Vue frontend directly into the Python package static/ dir.
#
# Vite is configured (frontend/vite.config.ts) to output directly to
# src/spectra_sherpa/static/, so no separate sync/copy step is needed.
#
# Usage:
#   ./scripts/rebuild_static.sh          # full build (npm ci + build)
#   ./scripts/rebuild_static.sh --quick  # build only (skip npm ci)
#
# Prerequisites: Node.js 18+ and npm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
STATIC_DIR="$REPO_ROOT/src/spectra_sherpa/static"

QUICK=false
if [[ "${1:-}" == "--quick" ]]; then
  QUICK=true
fi

if [[ "$QUICK" == false ]]; then
  echo "Installing frontend dependencies..."
  cd "$FRONTEND_DIR"
  npm ci
fi

echo "Building frontend → $STATIC_DIR ..."
cd "$FRONTEND_DIR"
npm run build

if [[ ! -f "$STATIC_DIR/index.html" ]]; then
  echo "Error: $STATIC_DIR/index.html not found after build." >&2
  exit 1
fi

echo "Done. Static assets in $STATIC_DIR are up to date."
