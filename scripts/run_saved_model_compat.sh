#!/usr/bin/env bash
# Run the saved-model compatibility check the way CI does.
#
#   bash scripts/run_saved_model_compat.sh WORK_DIR [SUMMARY_FILE]
#
# Upgrade mode runs once per reviewed reference release in
# saved_model_upgrade_baseline.json (fit with that PyPI release, apply with the
# candidate). Round-trip mode then fits and applies with the candidate itself.
# Run from packages/spectra-sherpa (monorepo) or the repository root (public)
# after `poetry install`. Exits non-zero if any mode fails.
set -uo pipefail

work_dir="${1:?usage: run_saved_model_compat.sh WORK_DIR [SUMMARY_FILE]}"
summary="${2:-/dev/null}"
mkdir -p "$work_dir"
status=0

# Run the console script directly so stopping the server stops it, not a
# wrapper process.
candidate="$(poetry env info --path)/bin/spectra-sherpa"
versions="$(python -c "import json; print(' '.join(json.load(open('scripts/saved_model_upgrade_baseline.json'))['reference_versions']))")"
if [ -z "$versions" ]; then
  echo "::error::saved_model_upgrade_baseline.json lists no reference releases"
  exit 1
fi

for version in $versions; do
  python -m venv "$work_dir/ref-$version"
  if ! "$work_dir/ref-$version/bin/pip" install --quiet "spectra-sherpa==$version"; then
    echo "::error::could not install reference release $version"
    status=1
    continue
  fi
  poetry run python scripts/saved_model_upgrade_check.py \
    --reference-command "$work_dir/ref-$version/bin/spectra-sherpa" \
    --reference-version "$version" \
    --candidate-command "$candidate" \
    --work-dir "$work_dir/upgrade-$version" \
    --report "$work_dir/upgrade-$version.md" || status=1
  cat "$work_dir/upgrade-$version.md" >> "$summary" 2>/dev/null || true
done

poetry run python scripts/saved_model_upgrade_check.py --mode round-trip \
  --candidate-command "$candidate" \
  --work-dir "$work_dir/round-trip" \
  --report "$work_dir/round-trip.md" || status=1
cat "$work_dir/round-trip.md" >> "$summary" 2>/dev/null || true

exit $status
