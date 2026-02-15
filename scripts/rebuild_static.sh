#!/usr/bin/env bash
# Rebuild the Vue frontend and sync dist/ into the Python package static/ dir.
#
# Usage:
#   ./scripts/rebuild_static.sh          # full build + sync
#   ./scripts/rebuild_static.sh --sync   # sync only (skip npm ci/build)
#
# Prerequisites: Node.js 18+ and npm; rsync

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"
STATIC_DIR="$REPO_ROOT/src/spectra_sherpa/static"

SYNC_ONLY=false
if [[ "${1:-}" == "--sync" ]]; then
  SYNC_ONLY=true
fi

if [[ "$SYNC_ONLY" == false ]]; then
  echo "Installing frontend dependencies..."
  cd "$FRONTEND_DIR"
  npm ci

  echo "Building frontend..."
  npm run build
fi

if [[ ! -d "$FRONTEND_DIR/dist" ]]; then
  echo "Error: frontend/dist/ does not exist. Run without --sync first." >&2
  exit 1
fi

echo "Syncing dist/ → static/ ..."
rsync -a --delete "$FRONTEND_DIR/dist/" "$STATIC_DIR/"

echo "Done. Static assets in $STATIC_DIR are up to date."
