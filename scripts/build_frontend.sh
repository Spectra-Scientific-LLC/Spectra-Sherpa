#!/usr/bin/env bash
# Build the Vue frontend and sync dist into the Python package static/ dir.
# Prefer scripts/rebuild_static.sh for new workflows (supports --sync flag).
#
# Usage:
#   ./scripts/build_frontend.sh
#
# Prerequisites: Node.js 18+ and npm; rsync

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/rebuild_static.sh" "$@"
